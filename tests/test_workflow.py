"""Public workflow credentials and context must remain per execution."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_apimart import OpenAIGateway
from dsh_bridge.workflow import workflow_bridge
from dsh_bridge import config, sdk_backend


def test_workflow_requires_explicit_key():
    with pytest.raises(ValueError, match="API Key"):
        with workflow_bridge("", "https://api.apimart.ai/v1", "gpt-6.1-sol", 30):
            pytest.fail("A missing workflow key must never fall back to the operator key")


def test_workflow_output_budget_is_configurable():
    with workflow_bridge("test-not-a-key", "https://api.deepseek.com/anthropic", "deepseek-flash", 30,
                         "deepseek-messages", max_tokens=16384) as bridge:
        assert bridge.cfg["max_tokens"] == 16384
    with pytest.raises(ValueError, match="max_tokens"):
        with workflow_bridge("test-not-a-key", "https://api.deepseek.com/anthropic", "deepseek-flash", 30,
                             "deepseek-messages", max_tokens=0):
            pytest.fail("Invalid budget must fail before any API request")


def test_concurrent_workflow_keys_and_context_are_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("APIMART_API_KEY", "operator-env-key-never-use")
    config.reset_cache()
    config.save({"api_key": "operator-saved-key-never-use"})
    disk = config.paths.config_file()
    before = disk.read_bytes()
    gateways = [OpenAIGateway(), OpenAIGateway()]
    homes = []

    def run(index):
        with workflow_bridge(f"user-{index}-key", gateways[index].url, "gpt-6.1-sol", 30) as bridge:
            home = Path(bridge.cfg["dsh_home"])
            homes.append(home)
            bridge.attach_images("node", ["not-persisted"])
            result = bridge.ask(bridge.session_id("workflow"), f"private-user-{index}-material; load video-replica")
            assert "A blue square" in result["text"]
            assert home.is_dir()
        assert not home.exists()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, range(2)))
        assert len(set(homes)) == 2
        for index, gateway in enumerate(gateways):
            assert len(gateway.requests) == 2
            assert all(header["authorization"] == f"Bearer user-{index}-key" for header in gateway.headers)
            import json
            wire = json.dumps(gateway.requests)
            assert f"private-user-{index}-material" in wire
            assert f"private-user-{1-index}-material" not in wire
            assert "operator-" not in wire
        assert disk.read_bytes() == before
        assert not (disk.parent / "history.jsonl").exists()
        assert not (disk.parent / "media").exists()
    finally:
        for gateway in gateways:
            gateway.close()
        config.reset_cache()


def test_linux_does_not_select_windows_bundle(monkeypatch):
    monkeypatch.setattr(sdk_backend.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sdk_backend.importlib.metadata, "version", lambda _: sdk_backend.SDK_VERSION)
    info = sdk_backend.sdk_info()
    assert info["compatible"] and info["installed"] and not info.get("bundled")


def test_deepseek_workflow_image_skill_and_key(tmp_path, monkeypatch):
    import base64
    import io
    import json
    from PIL import Image
    from test_standalone import ModelServer
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "shared"))
    gateway = ModelServer()
    image = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(image, format="PNG")
    try:
        with workflow_bridge("official-test-key", gateway.url, "deepseek-flash", 30,
                             "deepseek-messages") as bridge:
            home = Path(bridge.cfg["dsh_home"])
            assert bridge.cfg["provider"] == "deepseek-official"
            result = bridge.ask(bridge.session_id("workflow"), "load video-replica", [base64.b64encode(image.getvalue()).decode()])
            assert "A blue square" in result["text"]
            assert len(gateway.requests) == 2
            assert all(body["model"] == "deepseek-flash" for body in gateway.requests)
            assert all(header.get("x-api-key") == "official-test-key" or
                       header.get("authorization") == "Bearer official-test-key" for header in gateway.headers)
            wire = json.dumps(gateway.requests)
            assert '"type": "image"' in wire and '"type": "tool_result"' in wire
            assert "video-replica" in wire
        assert not home.exists()
        assert not (tmp_path / "shared/config.json").exists()
    finally:
        gateway.close()
