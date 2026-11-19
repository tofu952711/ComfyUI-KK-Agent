"""Assert reasoning controls on actual bundled Harness HTTP requests, locally."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_apimart import OpenAIGateway
from responses_gateway import ResponsesGateway
from dsh_bridge.workflow import workflow_bridge
from dsh_bridge.config import validate_updates


@pytest.mark.parametrize("protocol,effort", [("openai-completions", "high"),
    ("openai-completions", "medium"), ("openai-completions", "low"), ("openai-completions", "auto"),
    ("codez", "high"), ("codez", "medium"), ("codez", "low"), ("codez", "auto")])
def test_effort_on_initial_tool_and_continuation_requests(protocol, effort):
    gateway = ResponsesGateway() if protocol == "codez" else OpenAIGateway()
    try:
        with workflow_bridge("local-fake-key", gateway.url, "gpt-6.1-sol", 45,
                             protocol, reasoning_effort=effort) as bridge:
            session = bridge.session_id("reasoning-tools")
            bridge.ask(session, "Local only: load video-replica")
            bridge.ask(session, "Continue in the same session")
        assert len(gateway.requests) == 3
        for body in gateway.requests:
            if protocol == "codez":
                if effort == "auto":
                    assert not body.get("reasoning", {}).get("effort")
                else:
                    assert body["reasoning"]["effort"] == effort
                assert "reasoning_effort" not in body
                continue
            if effort == "auto":
                assert "reasoning_effort" not in body
            else:
                assert body["reasoning_effort"] == effort
            assert body["model"] == "gpt-6.1-sol"
        if protocol == "codez":
            assert all(path == "/v1/responses" for path in gateway.paths)
            assert any(m.get("type") == "function_call_output" for m in gateway.requests[1]["input"])
        else:
            assert any(m["role"] == "tool" for m in gateway.requests[1]["messages"])
    finally:
        gateway.close()


def test_messages_high_enables_thinking_and_effort():
    from test_standalone import ModelServer
    gateway = ModelServer()
    try:
        with workflow_bridge("local-fake-key", gateway.url, "deepseek-flash", 45,
                             "deepseek-messages", reasoning_effort="high") as bridge:
            bridge.ask(bridge.session_id("messages-high"), "Local only: load video-replica")
        assert len(gateway.requests) == 2
        assert all(body["thinking"]["type"] == "enabled" for body in gateway.requests)
        assert all(body["output_config"]["effort"] == "high" for body in gateway.requests)
    finally:
        gateway.close()


@pytest.mark.parametrize("protocol", ["openai-completions", "codez"])
def test_unsupported_effort_is_not_silently_downgraded_or_retried(protocol):
    gateway = ResponsesGateway() if protocol == "codez" else OpenAIGateway()
    gateway.status = 400
    try:
        with workflow_bridge("local-fake-key", gateway.url, "gpt-6.1-sol", 30,
                             protocol, reasoning_effort="high") as bridge:
            with pytest.raises(Exception, match="400|rejected|BAD_REQUEST"):
                bridge.ask(bridge.session_id("unsupported-effort"), "Local only")
        assert len(gateway.requests) == 1
        if protocol == "codez":
            assert gateway.requests[0]["reasoning"]["effort"] == "high"
        else:
            assert gateway.requests[0]["reasoning_effort"] == "high"
    finally:
        gateway.close()


@pytest.mark.parametrize("value", ["none", "invalid", "", None, 1, [], {}])
def test_invalid_choice_fails_before_media_or_model(value):
    with pytest.raises(ValueError, match="思考等级"):
        validate_updates({"reasoning_effort": value})
    with pytest.raises(ValueError, match="思考等级"):
        with workflow_bridge("local-fake-key", "http://127.0.0.1:1/v1", "gpt-6.1-sol", 30,
                             reasoning_effort=value):
            pytest.fail("Invalid choice reached workflow")
