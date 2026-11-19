"""Exercise request retries using the real bundled Harness and a local API."""
import threading
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_apimart import OpenAIGateway, settings
from dsh_bridge.errors import BridgeError
from dsh_bridge.sdk_backend import SDKRuntime


def test_three_retries_after_tool_keep_results_and_exact_schedule(tmp_path):
    gateway = OpenAIGateway()
    gateway.statuses = [200, 503, 503, 503, 200]
    cfg = settings(tmp_path, gateway)
    cfg['request_timeout_s'] = 90
    runtime = SDKRuntime(cfg)
    try:
        result = runtime.run('retry-after-tool', [{'type': 'text', 'text': 'load video-replica'}], 90)
        assert 'left to right' in result['text']
        assert len(gateway.requests) == 5  # Tool round, then four model attempts.
        assert len([e for e in result['events'] if e['type'] == 'tool/call']) == 1
        retries = [e['data'] for e in result['events'] if e['type'] == 'llm/retry']
        assert [e['delayMs'] for e in retries] == [5000, 15000, 30000]
        assert [e['retry'] for e in retries] == [1, 2, 3]
        for request in gateway.requests[1:]:
            assert request == gateway.requests[1]  # Same model step, no task restart.
            assert any(m['role'] == 'tool' for m in request['messages'])
        for index, delay in enumerate([5, 15, 30], 2):
            assert gateway.request_times[index] - gateway.request_times[index - 1] >= delay - .2
    finally:
        runtime.stop()
        gateway.close()


@pytest.mark.parametrize('stop_kind', ['cancel', 'timeout'])
def test_stop_during_retry_wait_never_submits_again(tmp_path, stop_kind):
    gateway = OpenAIGateway()
    gateway.status = 503
    runtime = SDKRuntime(settings(tmp_path, gateway))
    scheduled = threading.Event()
    errors = []
    def run():
        try:
            runtime.run('stop-retry', [{'type': 'text', 'text': 'hello'}],
                        2 if stop_kind == 'timeout' else 30,
                        lambda event: scheduled.set() if event == 'llm/retry' else None)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=run)
    try:
        worker.start()
        assert scheduled.wait(15)
        if stop_kind == 'cancel':
            assert runtime.cancel()
        worker.join(15)
        assert not worker.is_alive()
        assert len(gateway.requests) == 1
        assert isinstance(errors[0], BridgeError)
        assert errors[0].code == ('cancelled' if stop_kind == 'cancel' else 'timeout')
    finally:
        runtime.stop()
        worker.join(15)
        gateway.close()
