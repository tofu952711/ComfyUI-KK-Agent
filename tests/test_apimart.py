"""Real bundled Harness against a deterministic OpenAI Chat Completions gateway."""
from __future__ import annotations

import base64
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dsh_bridge import config
from dsh_bridge.sdk_backend import SDKRuntime


class OpenAIGateway:
    def __init__(self):
        self.requests = []
        self.headers = []
        self.paths = []
        self.status = 200
        self.statuses = []
        self.request_times = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                outer.requests.append(body)
                outer.request_times.append(__import__('time').monotonic())
                outer.paths.append(self.path)
                outer.headers.append({key.lower(): value for key, value in self.headers.items()})
                status = outer.statuses.pop(0) if outer.statuses else outer.status
                if status != 200:
                    raw = json.dumps({"error": {"message": "mock gateway rejected the request", "type": "server_error"}}).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                def chunk(delta, reason=None):
                    return {"id": "chatcmpl_local", "object": "chat.completion.chunk", "created": 1,
                            "model": "gpt-6.1-sol", "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}
                returned_skill = any(message.get("role") == "tool" for message in body["messages"])
                if returned_skill:
                    answer = "=== ANALYSIS ===\n本地中转模拟：蓝色方块，声音未提供。\n=== PROMPT ===\nA blue square moves left to right. Static Shot."
                    chunks = [chunk({"role": "assistant", "content": ""}),
                              chunk({"content": answer}), chunk({}, "stop")]
                else:
                    chunks = [chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "call_skill",
                                      "type": "function", "function": {"name": "skill", "arguments": ""}}]}),
                              chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"name":"video-'}}]}),
                              chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'replica"}'}}]}),
                              chunk({}, "tool_calls")]
                chunks.append({"id": "chatcmpl_local", "object": "chat.completion.chunk", "created": 1,
                               "model": "gpt-6.1-sol", "choices": [],
                               "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
                raw = ("".join("data: " + json.dumps(item, ensure_ascii=False) + "\n\n" for item in chunks)
                       + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def gateway():
    gateway = OpenAIGateway()
    yield gateway
    gateway.close()


def settings(tmp_path, gateway):
    return {**config.DEFAULTS, "api_key": "local-apimart-test-key", "base_url": gateway.url,
            "dsh_home": str(tmp_path / "home"), "workspace": str(tmp_path / "workspace"),
            "startup_timeout_s": 30, "request_timeout_s": 30}


def test_apimart_image_streamed_tool_and_resume(tmp_path, gateway):
    cfg = settings(tmp_path, gateway)
    runtime = SDKRuntime(cfg)
    image = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(image, format="PNG")
    blocks = [{"type": "text", "text": "remember-apimart-1701; use video-replica to analyze this image"},
              {"type": "image", "mimeType": "image/png", "data": base64.b64encode(image.getvalue()).decode()}]
    try:
        runtime.start()
        assert not gateway.requests  # A handshake has no model bill.
        result = runtime.run("apimart-integration", blocks, 30)
        assert "left to right" in result["text"]
        assert len(gateway.requests) == 2
        assert all(path == "/v1/chat/completions" for path in gateway.paths)
        assert all(body["model"] == "gpt-6.1-sol" and body["stream"] is True for body in gateway.requests)
        assert all(headers.get("authorization") == "Bearer local-apimart-test-key" for headers in gateway.headers)
        body = gateway.requests[0]
        assert body["max_tokens"] == cfg["max_tokens"]
        assert not {"store", "reasoning_effort", "stream_options", "max_completion_tokens"}.intersection(body)
        assert not any(message["role"] == "developer" for message in body["messages"])
        assert any(tool["function"]["name"] == "skill" for tool in body["tools"])
        images = [block for message in body["messages"] if isinstance(message.get("content"), list)
                  for block in message["content"] if block.get("type") == "image_url"]
        assert images and images[0]["image_url"]["url"].startswith("data:image/")
        tool_results = [message for message in gateway.requests[-1]["messages"] if message["role"] == "tool"]
        assert tool_results and "video-replica" in json.dumps(tool_results)
        assert result["usage"]
        # Credentials belong only in the worker environment, never in a patch.
        assert cfg["api_key"] not in (tmp_path / "home/bridge-model.patch.yml").read_text(encoding="utf-8")
        runtime.stop()
        runtime = SDKRuntime(cfg)
        followup = runtime.run("apimart-integration", [{"type": "text", "text": "continue"}], 30)
        assert followup["text"]
        assert "remember-apimart-1701" in json.dumps(gateway.requests[-1]["messages"])
    finally:
        runtime.stop()


@pytest.mark.parametrize("status", [400, 401, 403])
def test_apimart_error_does_not_repeat_billable_request(tmp_path, gateway, status):
    gateway.status = status
    runtime = SDKRuntime(settings(tmp_path, gateway))
    try:
        with pytest.raises(Exception):
            runtime.run("api-error", [{"type": "text", "text": "hello"}], 15)
        assert len(gateway.requests) == 1
        assert not runtime.alive
    finally:
        runtime.stop()


def test_apimart_settings_and_old_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APIMART_API_KEY", "env-apimart-secret")
    config.reset_cache()
    try:
        cfg = config.load()
        assert cfg["api_protocol"] == "openai-completions" and cfg["model"] == "gpt-6.1-sol"
        assert cfg["api_key"] == "env-apimart-secret"
        assert config.validate_updates({"base_url": "https://api.apimart.ai/v1/chat/completions/"})["base_url"] == "https://api.apimart.ai/v1"
        for invalid in ({"api_protocol": "unknown"}, {"provider": "bad route"}, {"base_url": "https://api.apimart.ai/v1?key=secret"}):
            with pytest.raises(ValueError):
                config.validate_updates(invalid)
        config.save({"model": "gpt-6.1-sol"})
        from dsh_bridge import paths
        assert "env-apimart-secret" not in paths.config_file().read_text(encoding="utf-8")
        paths.config_file().write_text(json.dumps({"provider": "deepseek-official", "model": "deepseek-flash",
                                                  "base_url": "https://api.deepseek.com/anthropic"}), encoding="utf-8")
        assert config.load(refresh=True)["api_protocol"] == "deepseek-messages"
        assert config.save({"max_tokens": 8192})["api_protocol"] == "deepseek-messages"
    finally:
        config.reset_cache()


def test_switching_route_uses_separate_model_context():
    from dsh_bridge.bridge import Bridge
    bridge = Bridge()
    try:
        before = bridge.session_id("same-node")
        bridge._cfg = {**bridge.cfg, "model": "another-model"}
        assert bridge.session_id("same-node") != before
        assert bridge.session_id("same-node") == bridge.session_id("same-node")
    finally:
        bridge.close()
