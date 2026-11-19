"""Real Harness must retain references when the Files endpoint is unavailable."""
import base64
import io
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from dsh_bridge.workflow import workflow_bridge
from dsh_bridge import paths
from dsh_bridge.errors import BridgeError
from test_standalone import ModelServer
from test_video_preparation import PreparedGateway
from responses_gateway import ResponsesGateway


@pytest.mark.parametrize("protocol", ["openai-completions", "codez", "deepseek-messages"])
@pytest.mark.parametrize("count", [45, 50])
def test_complete_video_bundle_above_default_image_count_is_not_dropped(protocol, count):
    # Worst-case current source bundle: 10 references and 35 labelled sheets.
    # Unique pixels prevent attachment deduplication hiding a count regression.
    images = []
    for index in range(count):
        raw = io.BytesIO()
        Image.new("RGB", (24, 24), (index * 5, 255 - index * 5, index)).save(raw, format="PNG")
        images.append(base64.b64encode(raw.getvalue()).decode())
    gateway = (ResponsesGateway(detail=False) if protocol == "codez" else
        PreparedGateway() if protocol == "openai-completions" else ModelServer(answer="received all"))
    gateway.skill_called = True
    try:
        with workflow_bridge("offline-fake-key", gateway.url, "gpt-6.1-sol", 60, protocol) as bridge:
            bridge.cfg.update(video_prompt_only=True, video_exact_inputs=True,
                video_system_prompt="完整资料测试规则", video_user_prompt="检查完整图片资料",
                video_media_evidence="参考图与抽帧拼图对应关系")
            result = bridge.ask(bridge.session_id("full-video-image-count"), "检查完整图片资料", images)
            assert result["text"]
        assert len(gateway.requests) == 1
        body = gateway.requests[0]
        messages = body["input"] if protocol == "codez" else body["messages"]
        sent = [block for message in messages if message.get("role") == "user"
            for block in message["content"] if block["type"] in ("image", "image_url", "input_image")]
        assert len(sent) == count
        for expected, block in zip(images, sent):
            if protocol == "deepseek-messages":
                encoded = block["source"]["data"]
            else:
                url = block["image_url"] if protocol == "codez" else block["image_url"]["url"]
                encoded = url.split(",", 1)[1]
            with Image.open(io.BytesIO(base64.b64decode(expected))) as before, Image.open(io.BytesIO(base64.b64decode(encoded))) as after:
                np.testing.assert_array_equal(np.asarray(before), np.asarray(after))
    finally:
        gateway.close()


def test_full_video_image_count_still_has_a_bound():
    raw = io.BytesIO()
    Image.new("RGB", (24, 24), "red").save(raw, format="PNG")
    encoded = base64.b64encode(raw.getvalue()).decode()
    gateway = ResponsesGateway(detail=False)
    try:
        with workflow_bridge("offline-fake-key", gateway.url, "gpt-6.1-sol", 60, "codez") as bridge:
            bridge.cfg["video_prompt_only"] = True
            with pytest.raises(BridgeError, match="image-count limit"):
                bridge.ask(bridge.session_id("image-count-over-budget"), "bounded input", [encoded] * 51)
        assert gateway.requests == []
    finally:
        gateway.close()


def test_large_video_evidence_survives_files_fallback(tmp_path):
    # Unique noisy PNGs defeat deduplication and ensure the old 20 MiB
    # base64 budget is crossed without relying on personal media files.
    rng = np.random.default_rng(20261117)
    images = []
    for _ in range(20):
        image = Image.fromarray(rng.integers(0, 256, (768, 512, 3), dtype=np.uint8))
        raw = io.BytesIO()
        image.save(raw, format="PNG")
        images.append(base64.b64encode(raw.getvalue()).decode())
    assert sum(map(len, images)) > 20 * 1024 * 1024
    gateway = ModelServer(answer="all images received")
    gateway.skill_called = True
    try:
        with workflow_bridge("offline-fake-key", gateway.url, "deepseek-flash", 90,
                             "deepseek-messages") as bridge:
            bridge.cfg["video_prompt_only"] = True
            result = bridge.ask(bridge.session_id("video-images"), "按外接规则检查全部参考图。", images)
            patch = json.loads((Path(bridge.cfg["dsh_home"]) / "bridge-model.patch.yml").read_text(encoding="utf-8"))
            assert patch[0]["config"]["maxInlineRequestImageBytes"] == 128 * 1024 * 1024
        assert result["text"] == "all images received"
        assert len(gateway.requests) == 1
        blocks = [b for m in gateway.requests[0]["messages"] for b in m.get("content", []) if isinstance(b, dict)]
        sent = [b for b in blocks if b.get("type") == "image"]
        assert len(sent) == 20
        assert sum(len(b["source"]["data"]) for b in sent) > 20 * 1024 * 1024
        assert not any("image omitted" in b.get("text", "") for b in blocks)
        assert not any(e.get("type") == "image/offload" for e in result["events"])
        # All inputs use the same dimensions; compare pixels of the first two
        # important references so a 20-image count cannot hide replacement.
        for before, after in zip(images[:2], sent[:2]):
            with Image.open(io.BytesIO(base64.b64decode(before))) as a, Image.open(io.BytesIO(base64.b64decode(after["source"]["data"]))) as b:
                np.testing.assert_array_equal(np.asarray(a), np.asarray(b))
    finally:
        gateway.close()


def test_video_over_budget_fails_instead_of_omitting_references(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    shutil.copytree(paths.VENDOR_DIR / "profile", vendor / "profile")
    shutil.copytree(paths.VENDOR_DIR / "skills", vendor / "skills")
    profile = vendor / "profile/video-prompt.patch.yml"
    # Lower only this test's limit so the failure path needs no huge images.
    with profile.open("a", encoding="utf-8") as handle:
        handle.write("\n- id: llm-deepseek\n  config:\n    maxInlineRequestImageBytes: 1048576\n    inlineImageOffloadByteQuantum: 524288\n")
    monkeypatch.setattr(paths, "VENDOR_DIR", vendor)
    raw = io.BytesIO()
    Image.fromarray(np.random.default_rng(7).integers(0, 256, (768, 512, 3), dtype=np.uint8)).save(raw, format="PNG")
    gateway = ModelServer(answer="must not generate with missing references")
    gateway.skill_called = True
    try:
        with workflow_bridge("offline-fake-key", gateway.url, "deepseek-flash", 60,
                             "deepseek-messages") as bridge:
            bridge.cfg["video_prompt_only"] = True
            with pytest.raises(BridgeError):
                bridge.ask(bridge.session_id("over-budget"), "检查参考图", [base64.b64encode(raw.getvalue()).decode()])
        assert gateway.requests == []  # Files failed; no incomplete model request.
    finally:
        gateway.close()
