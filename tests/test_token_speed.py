"""Test actual bundled streams, retries, persistence, and incomplete usage."""
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_apimart import OpenAIGateway, settings
from dsh_bridge.sdk_backend import SDKRuntime
from dsh_bridge.token_speed import SpeedRun, SpeedReader, latest_snapshot, latest_file


def test_real_stream_requests_and_retry_are_separate_and_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_BRIDGE_DATA_DIR', str(tmp_path / 'data'))
    gateway = OpenAIGateway()
    gateway.statuses = [503, 200, 200]
    cfg = {**settings(tmp_path, gateway), 'stream_usage': True}
    runtime = SDKRuntime(cfg)
    monitor = SpeedRun('92', cfg['model'])
    runtime.cfg['_token_monitor'] = monitor
    try:
        with monitor:
            result = runtime.run('token-speed-integration', [{'type':'text','text':'load video-replica'}], 30)
        assert len(result['token_speed']) == 3
        failed, *good = result['token_speed']
        assert failed['average_tps'] is None and failed['finish_reason'] == 'error'
        assert failed['failure_code']
        assert all(r['output_tokens'] == 50 and r['average_tps'] > 0 for r in good)
        assert all(r['first_token_seconds'] is not None for r in good)
        assert all(body['stream_options']['include_usage'] for body in gateway.requests)
        saved = latest_snapshot('92')
        assert saved['status'] == 'completed' and saved['output_tokens'] == 100
        assert saved['failed_requests'] == 1
        assert saved['effective_tps'] is None  # Unreported failed attempts are not silently treated as zero.
        assert saved['average_tps'] == round(100 / sum(r['elapsed_seconds'] for r in good), 2)
        raw = latest_file('92').read_text(encoding='utf-8')
        assert 'local-apimart-test-key' not in raw and 'load video-replica' not in raw
        assert (tmp_path / 'data/token-speed/history.jsonl').exists()
    finally:
        runtime.stop()
        gateway.close()


def test_tail_keeps_partial_line_and_finishes_before_temporary_cleanup(tmp_path):
    path = tmp_path / 'stream.jsonl'
    received = []
    reader = SpeedReader(path, received.append)
    reader.start()
    path.write_bytes(b'{"kind":"start"')
    reader._drain()
    assert received == []
    with path.open('ab') as handle:
        handle.write(b',"request_id":"one"}\n')
    reader.close()
    assert received == [{'kind':'start','request_id':'one'}]


def test_stale_persisted_run_does_not_appear_running_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_BRIDGE_DATA_DIR', str(tmp_path))
    monitor = SpeedRun('../92', 'test')
    monitor.publish(save=True)
    assert latest_snapshot('../92')['status'] == 'interrupted'
    with monitor:
        assert latest_snapshot('../92')['status'] == 'running'
    assert latest_snapshot('../92')['status'] == 'completed'
    assert latest_file('../92').parent == tmp_path / 'token-speed'


def test_failure_keeps_live_attempt_without_inventing_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_BRIDGE_DATA_DIR', str(tmp_path))
    with pytest.raises(ValueError), SpeedRun('92', 'test') as monitor:
        monitor.handle({'kind':'start','request_id':'one','elapsed_seconds':0,'output_tokens':None,'average_tps':None})
        raise ValueError('cancel')
    saved = latest_snapshot('92')
    assert saved['status'] == 'error'
    assert saved['output_tokens'] is None and saved['average_tps'] is None
    assert saved['requests'][0]['finish_reason'] == 'interrupted'
