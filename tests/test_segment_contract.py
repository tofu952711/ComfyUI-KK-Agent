"""Regression: a split request in the system textbox must not be silently lost."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.segment_contract import segment_request, request_notice, complete_segment_task
from dsh_bridge.media_tools import MediaTools

@pytest.mark.parametrize("text,count", [
    ("均等把视频分3段出来保存然后作为视频的素材，分段保存就不用管了，直接分析提示词", 3),
    ("把视频分3段出来保存然后作为视频的素材，分段保存，接下来分析整个视频提示词", 3),
    ("将原视频分成三段，优先自然切点", 3),
    ("视频等分为 5 段", 5), ("拆成两段视频", 2), ("分段保存", None),
])
def test_system_requests(text, count):
    request = segment_request("按爆款裂变技能，以原视频为骨架，图1人物、图2商品。",
                              text + "\n\n# 规则\n从0秒连续覆盖到视频结束，按真实动作阶段及切镜分段。")
    assert request == {"required": True, "count": count, "source": "rules_text"}
    assert "第二个文本框" in request_notice(request)

@pytest.mark.parametrize("text", [
    "从0秒连续覆盖到视频结束，按真实动作阶段及切镜分段，不机械每秒一段。",
    "如果用户要求把视频分3段出来保存，则调用工具。",
    "用户要求将视频分成3段时，请保存。",
    "示例：把视频分3段保存。",
    "```text\n把视频分3段保存\n```",
    "按规则分析，不分段",
    "按镜头分段输出提示词，每段描述视频动作和时间轴。",
])
def test_prose_examples_and_negation_not_forced(text):
    assert not segment_request("", text)["required"]

def test_user_override_and_output_count_guard(tmp_path):
    assert segment_request("本次不分段", "把视频分3段保存")["required"] is False
    assert segment_request("视频分成两段", "视频分成三段")["count"] == 2
    with pytest.raises(ValueError, match="最多输出5段"):
        segment_request("视频分成6段", "按规则分析")
    source = tmp_path / "video.mp4"
    source.write_bytes(b"not decoded")
    tools = MediaTools(source, tmp_path / "media")
    tools._cache["info"] = {"duration_seconds": 3, "fps": 30}
    request = segment_request("", "视频分3段保存")
    (tools.output / "segment_request.json").write_text(json.dumps(request), encoding="utf-8")
    good = tools.set_video_segments([{"start":i,"end":i+1} for i in range(3)])
    with pytest.raises(ValueError, match="要求输出3段"):
        tools.set_video_segments([{"start":0,"end":3}])
    assert json.loads((tools.output / "video_segments.json").read_text(encoding="utf-8")) == good

def test_one_same_session_correction_and_no_silent_fallback(tmp_path):
    request = segment_request("", "视频分3段保存")
    info = {"duration_seconds": 3, "fps": 30}
    original = {"text":"initial", "events":[{"type":"original"}]}
    calls = []
    def ask(session, prompt, **kwargs):
        calls.append((session, prompt, kwargs))
        (tmp_path / "video_segments.json").write_text(json.dumps({"segments": [
            {"start":i,"end":i+1} for i in range(3)]}), encoding="utf-8")
        return {"text":"corrected", "events":[{"type":"repair"}]}
    bridge = SimpleNamespace(ask=ask)
    result, attempts = complete_segment_task(bridge, "same-session", original, tmp_path, info,
        request, time.monotonic()+10, None)
    assert result["text"] == "corrected" and attempts == 1
    assert result["events"] == original["events"] + [{"type":"repair"}]
    assert calls[0][0] == "same-session" and "set_video_segments" in calls[0][1]
    assert "images" not in calls[0][2] and 0 < calls[0][2]["timeout"] <= 10
    assert complete_segment_task(bridge, "same-session", result, tmp_path, info, request,
        time.monotonic()+10, None) == (result, 0)
    (tmp_path / "video_segments.json").unlink()
    bridge.ask = lambda *a, **kw: {"text":"still forgot", "events":[]}
    with pytest.raises(RuntimeError, match="已补执行一次"):
        complete_segment_task(bridge, "same-session", original, tmp_path, info, request,
                              time.monotonic()+10, None)
    with pytest.raises(RuntimeError, match="时间上限"):
        complete_segment_task(bridge, "same-session", original, tmp_path, info, request,
                              time.monotonic()-1, None)
