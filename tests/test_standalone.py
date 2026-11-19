"""Offline integration tests: real Harness runtime, local deterministic model API."""
from __future__ import annotations

import base64
import importlib
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dsh_bridge import config
from dsh_bridge.errors import BridgeError
from dsh_bridge.sdk_backend import SDKRuntime, prepare_home


class ModelServer:
    def __init__(self, skill_name="video-replica", answer=None):
        self.requests = []
        self.headers = []
        self.skill_name = skill_name
        self.answer = answer
        self.stop_reason = "end_turn"
        self.skill_called = False
        self.delay = 0.0
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                raw = json.dumps({"data": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if not self.path.endswith("/messages"):
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":{"type":"not_found_error","message":"Files unsupported"}}')
                    return
                body = json.loads(raw)
                outer.requests.append(body)
                outer.headers.append({key.lower(): value for key, value in self.headers.items()})
                if outer.delay:
                    time.sleep(outer.delay)
                events = [{"type": "message_start", "message": {"id": "msg_test", "model": "deepseek-flash",
                          "usage": {"input_tokens": 100, "output_tokens": 1}}}]
                if not outer.skill_called:
                    outer.skill_called = True
                    events += [
                        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tool_test", "name": "skill", "input": {}}},
                        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": json.dumps({"name": outer.skill_name})}},
                        {"type": "content_block_stop", "index": 0},
                    ]
                    reason = "tool_use"
                else:
                    text = "=== ANALYSIS ===\n测试画面；抽样间动作未知。\n=== PROMPT ===\nA blue square remains still."
                    if outer.answer is not None:
                        text = outer.answer
                    events += [
                        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
                        {"type": "content_block_stop", "index": 0},
                    ]
                    reason = outer.stop_reason
                events += [{"type": "message_delta", "delta": {"stop_reason": reason}, "usage": {"output_tokens": 50}}, {"type": "message_stop"}]
                response = "".join(f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # Expected when the tested client cancels.
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def model():
    server = ModelServer()
    yield server
    server.close()


def settings(tmp_path, model=None):
    return {**config.DEFAULTS, "api_key": "test-not-a-real-key", "base_url": model.url if model else "http://127.0.0.1:9",
            "api_protocol": "deepseek-messages", "provider": "deepseek-official", "model": "deepseek-flash",
            "dsh_home": str(tmp_path / "harness"), "workspace": str(tmp_path / "workspace"),
            "startup_timeout_s": 30, "request_timeout_s": 30}


def test_real_runtime_skill_image_and_persisted_conversation(tmp_path, model):
    cfg = settings(tmp_path, model)
    runtime = SDKRuntime(cfg)
    image = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(image, format="PNG")
    blocks = [{"type": "text", "text": "remember-marker-7821; analyze this image and load video-replica skill"},
              {"type": "image", "mimeType": "image/png", "data": base64.b64encode(image.getvalue()).decode()}]
    try:
        runtime.start()
        assert runtime.alive
        assert not model.requests  # Handshake never calls the paid model endpoint.
        answer = runtime.run("standalone-integration", blocks, 30)
        assert "A blue square" in answer["text"]
        assert len(model.requests) == 2  # Real skill tool call + answer.
        wire = json.dumps(model.requests, ensure_ascii=False)
        assert '"type": "image"' in wire
        tools = {tool["name"] for tool in model.requests[0]["tools"]}
        assert "skill" in tools
        assert not tools.intersection({"bash", "pwsh", "write_file", "edit_file", "create_goal",
                                       "subagent_fork", "web_fetch", "web_search"})
        assert "agent-reach" not in json.dumps(model.requests[0], ensure_ascii=False)
        assert "video-replica" in json.dumps(model.requests[-1]["messages"], ensure_ascii=False)
        # Verify that the tool returned actual instructions rather than a missing-skill error.
        tool_results = [block for message in model.requests[-1]["messages"]
                        for block in message.get("content", []) if isinstance(block, dict) and block.get("type") == "tool_result"]
        assert tool_results and not any(block.get("is_error") for block in tool_results)
        runtime.stop()
        runtime = SDKRuntime(cfg)
        followup = runtime.run("standalone-integration", [{"type": "text", "text": "continue with the same reference"}], 30)
        assert followup["text"]
        assert "remember-marker-7821" in json.dumps(model.requests[-1]["messages"])
    finally:
        runtime.stop()
    assert not runtime.alive


def test_cancel_stops_real_runtime_without_retry(tmp_path, model):
    model.skill_called = True
    model.delay = 4
    runtime = SDKRuntime(settings(tmp_path, model))
    errors = []
    def run():
        try:
            runtime.run("cancel-case", [{"type": "text", "text": "wait"}], 20)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=run)
    worker.start()
    limit = time.monotonic() + 15
    while not model.requests and time.monotonic() < limit:
        time.sleep(0.05)
    assert model.requests
    with pytest.raises(BridgeError, match="busy"):
        runtime.run("other", [{"type": "text", "text": "don't queue"}], 20)
    assert runtime.cancel()
    worker.join(10)
    assert not worker.is_alive()
    assert len(model.requests) == 1
    assert errors and getattr(errors[0], "code", "") == "cancelled"
    assert not runtime.alive


def test_timeout_stops_real_runtime_without_retry(tmp_path, model):
    model.skill_called = True
    model.delay = 3
    runtime = SDKRuntime(settings(tmp_path, model))
    try:
        with pytest.raises(BridgeError, match="timeout"):
            runtime.run("timeout-case", [{"type": "text", "text": "wait"}], 0.5)
        assert len(model.requests) == 1
        assert not runtime.alive
    finally:
        runtime.stop()


@pytest.mark.parametrize("answer,reason,code", [("", "end_turn", "empty_response"),
                                               ("partial", "max_tokens", "output_limit")])
def test_empty_and_truncated_responses_have_diagnostics_without_retry(tmp_path, model, answer, reason, code):
    model.skill_called = True
    model.answer = answer
    model.stop_reason = reason
    runtime = SDKRuntime(settings(tmp_path, model))
    stages = []
    try:
        with pytest.raises(BridgeError) as failure:
            runtime.run("failed-response", [{"type": "text", "text": "private request"}], 30, stages.append)
        assert failure.value.code == code
        assert len(model.requests) == 1
        assert runtime.last_diagnostics["assistant_messages"] == 1
        assert runtime.last_diagnostics["text_chars"] == len(answer)
        assert "private request" not in json.dumps(runtime.last_diagnostics)
        assert "assistant/message" in stages
    finally:
        runtime.stop()


def test_settings_redact_secrets_and_validate():
    assert "api_key" not in config.public_config({"api_key": "secret", "model": "m"})
    assert config.public_config({"api_key": "secret"})["has_api_key"]
    assert "api_key" not in config.validate_updates({"api_key": "", "model": "m"})
    assert config.validate_updates({"clear_api_key": True})["api_key"] == ""
    for invalid in ({"request_timeout_s": -1}, {"strip_proxy_env": "false"}, {"dsh_home": "other"}, {"base_url": "file:///tmp"}):
        with pytest.raises(ValueError):
            config.validate_updates(invalid)


def test_seed_preserves_customized_skill(tmp_path):
    cfg = settings(tmp_path)
    home = prepare_home(cfg)
    skill = home / "skills" / "video-replica" / "SKILL.md"
    assert skill.is_file()
    skill.write_text("custom instructions", encoding="utf-8")
    prepare_home(cfg)
    assert skill.read_text(encoding="utf-8") == "custom instructions"


def test_environment_key_is_not_written_by_settings_save(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DSH_BRIDGE_API_KEY", "environment-only-secret")
    config.reset_cache()
    try:
        assert config.load()["api_key"] == "environment-only-secret"
        config.save({"model": "deepseek-flash"})
        from dsh_bridge import paths
        assert "environment-only-secret" not in paths.config_file().read_text(encoding="utf-8")
        assert config.load()["api_key"] == "environment-only-secret"
    finally:
        config.reset_cache()


def test_routes_settings_chat_and_validation(tmp_path, model, monkeypatch):
    import asyncio
    import types
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    # Load the real routes under a namespace package, without requiring ComfyUI.
    package = types.ModuleType("bridge_route_tests")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    routes = web.RouteTableDef()
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
    monkeypatch.setitem(sys.modules, "server", server)
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "route-data"))
    api = importlib.import_module("bridge_route_tests.routes.api")
    cfg_module = importlib.import_module("bridge_route_tests.dsh_bridge.config")
    cfg_module.save(settings(tmp_path, model))
    api.BRIDGE.reload()

    async def exercise():
        app = web.Application()
        app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/dsh_bridge/status")
            payload = await response.json()
            assert response.status == 200
            assert payload["config"]["has_api_key"]
            assert "test-not-a-real-key" not in json.dumps(payload)
            assert "api_key" not in payload["config"]
            response = await client.post("/dsh_bridge/config", json={"dsh_home": "illegal"})
            assert response.status == 400
            response = await client.post("/dsh_bridge/config", json={"api_key": "", "request_timeout_s": 60})
            assert response.status == 200
            assert "test-not-a-real-key" not in await response.text()
            assert api.BRIDGE.cfg["api_key"] == "test-not-a-real-key"
            for body in ([], {"images": "bad"}, {"text": ""}):
                response = await client.post("/dsh_bridge/chat", json=body)
                assert response.status == 400
            response = await client.post("/dsh_bridge/chat", json={"text": "analyze reference", "session": "route"})
            assert response.status == 200
            wire = await response.text()
            assert "event: done" in wire and "A blue square" in wire
            response = await client.post("/dsh_bridge/cancel")
            assert response.status == 200
            assert not (await response.json())["cancelled"]
    try:
        asyncio.run(exercise())
    finally:
        api.BRIDGE.close()


def test_portable_runs_in_host_without_site_packages(tmp_path, model):
    import subprocess
    # -S removes site-packages. Block host imports too, to catch accidental SDK use.
    script = """
import json, sys
sys.path.insert(0, sys.argv[1])
sys.modules['deepseek_harness'] = None
sys.modules['pydantic'] = None
from dsh_bridge.sdk_backend import SDKRuntime, sdk_info
assert sdk_info()['bundled'] and sdk_info()['compatible']
runtime = SDKRuntime(json.loads(sys.argv[2]))
try:
    result = runtime.run('bare-host', [{'type':'text','text':'load video-replica and analyze'}], 30)
    assert 'A blue square' in result['text']
finally:
    runtime.stop()
assert sys.modules['deepseek_harness'] is None and sys.modules['pydantic'] is None
print('PORTABLE_NO_HOST_SDK_OK')
"""
    result = subprocess.run([sys.executable, "-S", "-c", script, str(ROOT),
                             json.dumps(settings(tmp_path, model))],
                            capture_output=True, text=True, encoding="utf-8", timeout=50)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PORTABLE_NO_HOST_SDK_OK" in result.stdout
