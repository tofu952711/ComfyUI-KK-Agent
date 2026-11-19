"""ASR paths must follow a relocated plugin, including the MCP child process."""
import importlib.util
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("configured", ["", "models/custom-asr"])
def test_relocated_plugin_resolves_asr_and_passes_it_to_mcp(tmp_path, monkeypatch, configured):
    package = tmp_path / "中文 plugin moved" / "custom_nodes" / "RenamedBridge"
    module_path = package / "dsh_bridge" / "media_workflow.py"
    module_path.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "dsh_bridge/media_workflow.py", module_path)
    spec = importlib.util.spec_from_file_location("relocated_media_workflow", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model_dir = package / (configured or "models/sensevoice")
    model_dir.mkdir(parents=True)
    for name in ("model.int8.onnx", "tokens.txt"):
        (model_dir / name).write_text("fixture")
    monkeypatch.delenv("DSH_BRIDGE_ASR_MODEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    video = SimpleNamespace(get_stream_source=lambda: source)
    bridge = SimpleNamespace(cfg={"workspace": str(tmp_path / "job")})
    module.configure_media(bridge, video, configured)
    expected = str(model_dir.resolve())
    assert bridge.cfg["media_model_dir"] == expected
    arguments = bridge.cfg["media_mcp"]["args"]
    assert arguments[arguments.index("--model-dir") + 1] == expected


def test_bundled_model_matches_distribution_manifest():
    import hashlib
    import json
    model_dir = Path(__file__).resolve().parents[1] / "models/sensevoice"
    manifest = json.loads((model_dir / "MODEL_SOURCES.json").read_text(encoding="utf-8"))
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((model_dir / name).read_bytes()).hexdigest() == digest
