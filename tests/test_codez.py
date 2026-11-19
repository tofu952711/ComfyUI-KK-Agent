"""CodeZ preset uses its own route/key and retains vision and tool support."""
import base64
import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from responses_gateway import ResponsesGateway
from dsh_bridge.sdk_backend import provider_api
from dsh_bridge import config
from dsh_bridge.workflow import workflow_bridge


def test_codez_preserves_user_settings_without_reusing_other_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "settings"))
    monkeypatch.setenv("DSH_BRIDGE_API_KEY", "unrelated-global-key")
    monkeypatch.setenv("APIMART_API_KEY", "unrelated-apimart-key")
    monkeypatch.delenv("CODEZ_API_KEY", raising=False)
    config.reset_cache()
    try:
        updates = config.validate_updates({"api_protocol": "codez", "base_url": "https://my-codez.example/v1",
                                          "provider": "apimart", "model": "account-model", "proxy_url": "http://127.0.0.1:1"})
        assert updates["base_url"] == "https://my-codez.example/v1"
        assert updates["provider"] == "codez"
        assert updates["proxy_url"] == "http://127.0.0.1:1"
        assert updates["model"] == "account-model"
        saved = config.save(updates)
        assert not saved["api_key"]
        assert config.save({"model": "account-model"})["base_url"] == "https://my-codez.example/v1"
        monkeypatch.setenv("CODEZ_API_KEY", "codez-env-key")
        assert config.load(refresh=True)["api_key"] == "codez-env-key"
    finally:
        config.reset_cache()


def test_codez_real_runtime_streams_images_and_tools():
    gateway = ResponsesGateway()
    image = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(image, "PNG")
    try:
        with workflow_bridge("codez-test-key", gateway.url, "gpt-6.1-sol", 45,
                             "codez") as bridge:
            assert bridge.cfg["provider"] == "codez"
            assert bridge.cfg["base_url"] == gateway.url
            assert bridge.cfg["api_protocol"] == "codez"
            result = bridge.ask(bridge.session_id("codez"), "load video-replica",
                                [base64.b64encode(image.getvalue()).decode()])
            assert "left to right" in result["text"]
            assert len(gateway.requests) == 2
            assert all(p == "/v1/responses" for p in gateway.paths)
            assert all(h["authorization"] == "Bearer codez-test-key" for h in gateway.headers)
            assert any(block.get("type") == "input_image"
                       for message in gateway.requests[0]["input"]
                       if isinstance(message.get("content"), list) for block in message["content"])
            assert any(m.get("type") == "function_call_output" for m in gateway.requests[1]["input"])
            assert any(m.get("encrypted_content") == "local-replay-proof" for m in gateway.requests[1]["input"])
    finally:
        gateway.close()


def test_codez_protocol_does_not_change_zdjapi_or_other_protocols():
    for host in ("zdjapi.com", "api.zdjapi.com", "other.zdjapi.com"):
        assert provider_api({"api_protocol": "codez", "base_url": f"https://{host}/v1"}) == "openai-completions"
    for host in ("codezsy.com", "api-s.codezsy.com", "api.zdjapi.com.other.example"):
        assert provider_api({"api_protocol": "codez", "base_url": f"https://{host}/v1"}) == "openai-responses"
    assert provider_api({"api_protocol": "openai-completions", "base_url": "https://api-s.codezsy.com/v1"}) == "openai-completions"
    assert provider_api({"api_protocol": "deepseek-messages", "base_url": "https://api-s.codezsy.com"}) == "deepseek-messages"
