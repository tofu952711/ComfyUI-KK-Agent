"""Real frames and actual bundled agents against localhost; no paid API calls."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_video_preparation import staged
from b_parallel_gateway import BParallelGateway, SHARED
from dsh_bridge import b_parallel_reverse as module
from dsh_bridge.b_segment_media import prepare_segment_bundle, SegmentMediaTools
from dsh_bridge.video_preparation import prepare_video
from dsh_bridge.token_speed import SpeedRun
from dsh_bridge.b_review import CHECKS


def configure(bridge, speed, audit, system, user, evidence, phase, images):
    bridge.cfg.update(_token_monitor=speed, _request_audit_file=str(audit),
                      video_prompt_only=True, video_exact_inputs=True,
                      video_system_prompt=system, video_user_prompt=user, video_media_evidence=evidence)


def arguments(staged, count, tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "diagnostics"))
    report, _, _ = prepare_video(staged)
    segments = [{"start": i * 2/count, "end": (i+1) * 2/count} for i in range(count)]
    audit_dir = tmp_path / "audits"
    audit_dir.mkdir()
    media = {"serverName": "video", "transport": "stdio", "command": sys.executable,
             "args": ["-u", str(module.__file__).replace("b_parallel_reverse.py", "media_server.py"),
                      "--video", str(staged.parent / "source-video.mp4"), "--output", str(staged)],
             "cwd": str(staged.parent), "startupTimeoutMs": 30000, "failOnStartupError": True}
    return dict(api_key="local-fake-key", base_url="http://127.0.0.1:1/v1", model="gpt-6.1-sol",
                timeout_s=90, max_tokens=8192, api_protocol="codez", reasoning_effort="high",
                stream_usage=True, requirement="原始用户要求：保持参考图编号。", reverse_rules="B专用逐段反推规则{{literal}}；原文不改。",
                output=staged, report=report, slots=[], refs=[], media_text="source evidence",
                segment_answer={"text": "已按画面边界实际切好视频"},
                video_record={"count": count, "segments": segments}, media_mcp=media,
                configure_stage=configure, audit_dir=audit_dir)


@pytest.mark.parametrize("protocol,count", [("openai-completions", 2), ("codez", 2), ("codez", 4)])
def test_real_isolated_agents_overlap_and_keep_rules_and_tool_images(staged, tmp_path, monkeypatch, protocol, count):
    kwargs = arguments(staged, count, tmp_path, monkeypatch)
    gateway = BParallelGateway(kwargs["video_record"]["segments"], protocol)
    kwargs.update(base_url=gateway.url, api_protocol=protocol)
    original_files = {str(p.relative_to(staged)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in staged.iterdir() if p.is_file()}
    try:
        with SpeedRun("b-test", "gpt-6.1-sol") as speed:
            text, record, audits = module.run_parallel_reverse(**kwargs, speed=speed)
            requests = speed.snapshot()["requests"]
        assert not gateway.errors, gateway.errors
        assert gateway.peak_children == count  # Barrier fails if calls are serial.
        assert len(gateway.coordinator_requests) == 1
        assert len(gateway.worker_requests) == count * 2  # Each does a real scoped get_frames call.
        assert record["agent_count"] == count
        assert record["shared_context"] == SHARED
        assert record["sum_child_seconds"] > record["parallel_wall_seconds"]
        assert [r["segment_index"] for r in record["segments"]] == list(range(1, count + 1))
        assert [text.index(f"## 第{i}段提示词") for i in range(1, count + 1)] == sorted(
            text.index(f"## 第{i}段提示词") for i in range(1, count + 1))
        assert len({r["segment_index"] for r in requests if r.get("b_agent_role") == "segment"}) == count
        assert len(audits) == count + 2
        assert len(gateway.review_requests) == 1
        assert record["review"]["status"] == "approved"
        assert all(r["reviewed"] for r in record["segments"])
        assert any(r.get("b_agent_role") == "reviewer" and r["phase"] == "review" for r in requests)
        for index, body in gateway.worker_requests:
            rules = body["instructions"] if protocol == "codez" else next(
                m["content"] for m in body["messages"] if m["role"] == "system")
            assert rules == kwargs["reverse_rules"]
            assert (body["reasoning"]["effort"] if protocol == "codez" else body["reasoning_effort"]) == "high"
        for file in audits.values():
            outgoing = [json.loads(l) for l in Path(file).read_text(encoding="utf-8").splitlines()]
            assert all(r["system_exact"] and r["user_exact"] and r["media_evidence_exact"] for r in outgoing)
            assert "local-fake-key" not in Path(file).read_text(encoding="utf-8")
        for name, digest in original_files.items():
            assert hashlib.sha256((staged / name).read_bytes()).hexdigest() == digest
        assert (Path(record["result_directory"]) / "prompts.txt").read_text(encoding="utf-8") == text
    finally:
        gateway.close()


def test_one_failed_child_preserves_other_results_without_false_success(staged, tmp_path, monkeypatch):
    kwargs = arguments(staged, 2, tmp_path, monkeypatch)
    gateway = BParallelGateway(kwargs["video_record"]["segments"], "codez", fail_segment=2)
    kwargs["base_url"] = gateway.url
    try:
        with SpeedRun("b-failure", "gpt-6.1-sol") as speed:
            with pytest.raises(RuntimeError, match="失败段号：2"):
                module.run_parallel_reverse(**kwargs, speed=speed)
        results = tmp_path / "diagnostics" / "b-results" / speed.run_id
        assert (results / "segment-1.json").is_file()
        assert not (results / "segment-2.json").exists()
        assert not (results / "prompts.txt").exists()
        assert json.loads((results / "status.json").read_text(encoding="utf-8"))["status"] == "failed"
        assert not gateway.errors
        assert not gateway.review_requests
    finally:
        gateway.close()


def test_main_contract_failure_does_not_start_children(staged, tmp_path, monkeypatch):
    kwargs = arguments(staged, 2, tmp_path, monkeypatch)
    gateway = BParallelGateway(kwargs["video_record"]["segments"], "codez", fail_coordinator=True)
    kwargs["base_url"] = gateway.url
    try:
        with SpeedRun("b-main-failure", "gpt-6.1-sol") as speed:
            with pytest.raises(RuntimeError, match="主AI未返回有效"):
                module.run_parallel_reverse(**kwargs, speed=speed)
        assert not gateway.worker_requests
    finally:
        gateway.close()


def test_segment_evidence_is_scoped_private_and_time_origin_explicit(staged):
    report, _, _ = prepare_video(staged)
    directory, text, images, scope = prepare_segment_bundle(staged, report, [2, 10], 2,
        {"start": 1., "end": 2.}, 2, SHARED)
    tools = SegmentMediaTools(staged.parent / "source-video.mp4", directory)
    assert images and "image2 = @图片2" in text and "image10 = @图片10" in text
    assert scope["duration"] == 1 and scope["local_start"] == 0
    meta, _ = tools.frames([1.25])
    assert meta["local_times"] == [.25] and meta["context_only"] == [False]
    with pytest.raises(ValueError, match="原片"):
        tools.frames([.25])
    with pytest.raises(ValueError, match="不能修改"):
        tools.set_video_segments([])
    assert tools.transcribe()["assigned_range"] == {"start": 1., "end": 2.}
    assert tools.video == (staged.parent / "source-video.mp4").resolve()


def test_timeout_cancels_running_b_agents_and_waits_for_cleanup(staged, tmp_path, monkeypatch):
    kwargs = arguments(staged, 2, tmp_path, monkeypatch)
    kwargs["timeout_s"] = .35
    active = set()
    lock = threading.Lock()
    stopped = []

    @contextmanager
    def fake_bridge(*args, **kw):
        class Fake:
            cfg = {"workspace": str(tmp_path), "dsh_home": str(tmp_path)}
            def session_id(self, label): return label
            def ask(self, *args, **kw):
                if "主AI" in self.cfg["video_system_prompt"]:
                    return {"text": json.dumps(SHARED), "usage": {}}
                with lock: active.add(self)
                while not getattr(self, "cancelled", False): time.sleep(.01)
                raise RuntimeError("cancelled mock")
            def cancel(self):
                self.cancelled = True
                stopped.append(self)
        bridge = Fake()
        bridge.cfg = dict(bridge.cfg)
        try: yield bridge
        finally:
            with lock: active.discard(bridge)
    monkeypatch.setattr(module, "workflow_bridge", fake_bridge)
    with SpeedRun("b-timeout", "mock") as speed:
        with pytest.raises(RuntimeError, match="整体超时"):
            module.run_parallel_reverse(**kwargs, speed=speed)
    assert len(stopped) == 2 and not active


def test_final_review_corrections_reach_delivered_text_and_keep_drafts(staged, tmp_path, monkeypatch):
    from dsh_bridge.b_review import CHECKS
    kwargs = arguments(staged, 2, tmp_path, monkeypatch)
    original = "【动作与摄影机】\n0—1秒，两罐摆在右后方。\n【对白与声音】\n保持同一女声。"
    response = {"status": "corrected", "checks": {k: True for k in CHECKS},
                "issues": ["第二段两罐位置应与第一段一致"], "edits": [
                    {"segment_index": 2, "old": "两罐摆在右后方。", "new": "两罐保持在左前方。", "reason": "接续前段摆放"}]}
    gateway = BParallelGateway(kwargs["video_record"]["segments"], "codez", review_response=response,
        child_texts={1: "两罐放在左前方。", 2: original})
    kwargs["base_url"] = gateway.url
    try:
        with SpeedRun("b-review-correct", "gpt-6.1-sol") as speed:
            text, record, audits = module.run_parallel_reverse(**kwargs, speed=speed)
        directory = Path(record["result_directory"])
        assert "两罐保持在左前方。" in text and "两罐摆在右后方。" not in text
        assert "两罐摆在右后方。" in (directory / "draft-prompts.txt").read_text(encoding="utf-8")
        assert json.loads((directory / "segment-2.json").read_text(encoding="utf-8"))["text"] == original
        assert record["segments"][1]["review_edits"] == 1
        assert record["review"]["status"] == "corrected" and "review" in audits
        assert not gateway.errors
    finally:
        gateway.close()


@pytest.mark.parametrize("response,error", [("bad json", "有效JSON"),
    ({"status": "blocked", "checks": {k: False for k in CHECKS},
      "issues": ["跨段商品数量冲突无法修正"], "edits": []}, "最终复核未通过")])
def test_failed_review_never_delivers_unreviewed_drafts(staged, tmp_path, monkeypatch, response, error):
    kwargs = arguments(staged, 2, tmp_path, monkeypatch)
    gateway = BParallelGateway(kwargs["video_record"]["segments"], "codez", review_response=response)
    kwargs["base_url"] = gateway.url
    try:
        with SpeedRun("b-review-fails", "gpt-6.1-sol") as speed:
            with pytest.raises(RuntimeError, match=error):
                module.run_parallel_reverse(**kwargs, speed=speed)
        directory = tmp_path / "diagnostics" / "b-results" / speed.run_id
        assert (directory / "draft-prompts.txt").is_file()
        assert (directory / "segment-1.json").is_file()
        assert (directory / "segment-2.json").is_file()
        assert (directory / "review-response.json").is_file()
        assert not (directory / "prompts.txt").exists()
        assert json.loads((directory / "status.json").read_text(encoding="utf-8"))["status"] == "failed"
    finally:
        gateway.close()
