"""Actual media decoding and official Harness wire tests; no paid endpoints."""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading

import av
import numpy as np
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.media_tools import MediaTools
from dsh_bridge.video_preparation import prepare_video, initial_request, sampling_plan, prepared_evidence_text
from dsh_bridge.workflow import workflow_bridge


@pytest.fixture
def staged(tmp_path):
    output = tmp_path / "media-analysis"
    output.mkdir()
    video = tmp_path / "source-video.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("libx264", rate=12)
        stream.width, stream.height, stream.pix_fmt = 96, 128, "yuv420p"
        for index in range(24):
            rgb = np.zeros((128, 96, 3), dtype=np.uint8)
            rgb[:, :, 0 if index < 13 else 2] = 255
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return output


def test_candidates_real_frames_no_audio_and_job_cache(staged, monkeypatch):
    report, shots, transcript = prepare_video(staged)
    assert transcript["has_audio"] is False
    assert report["video"]["duration_seconds"] == 2
    assert any(abs(c["time"] - 13/12) < .000001 and not c["verified"] for c in shots["candidate_cuts"])
    # Rounded candidate seconds must still select the cut frame itself, not
    # inadvertently advance another frame at fractional-rate timestamps.
    cut_sheet = next(s for s in report["sheets"] if s["kind"] == "候选切点四帧对照")
    assert cut_sheet["actual_times"] == [.916667, 1.0, 1.083333, 1.333333]
    assert report["coverage"]["dense_step_seconds"] == .25
    assert any(s["kind"] == "全片密集动作与运镜对照" for s in report["sheets"])
    tools = MediaTools(staged.parent / "source-video.mp4", staged)
    meta, _ = tools.frames([.1, 1.1])
    assert all(t <= a < t + 1/12 + .001 for t, a in zip(meta["requested_times"], meta["actual_times"]))
    index = tools._frame_index
    with Image.open(staged / index[tools._time_key(.1)]["file"]) as image:
        assert np.asarray(image).mean((0, 1))[0] > 240
    with Image.open(staged / index[tools._time_key(1.1)]["file"]) as image:
        assert np.asarray(image).mean((0, 1))[2] > 240
    for invalid in ([float("nan")], [-.1], [2], list(np.arange(13) / 10)):
        with pytest.raises(ValueError):
            tools.frames(invalid)
    # A fresh MCP process shares only this job's immutable evidence. Cached
    # requests must not decode the video or reload an ASR recognizer.
    fresh = MediaTools(staged.parent / "source-video.mp4", staged)
    fresh.info()
    monkeypatch.setattr(av, "open", lambda *a, **k: pytest.fail("unnecessary repeated decode"))
    assert fresh.shots() == shots
    assert fresh.transcribe() == transcript
    fresh.frames([.1, 1.1])


def test_dense_sampling_bounds_and_fractional_cut_context():
    cuts = {"candidate_cuts": [{"time": .01, "score": .5}, {"time": 3599.95, "score": .4}],
            "candidate_intervals": [{"start": 0, "end": .01}, {"start": .01, "end": 3599.95}]}
    plan = sampling_plan({"duration_seconds": 3600, "fps": 30}, cuts)
    assert len(plan["dense"]) <= 241 and len(plan["overview"]) <= 61
    assert all(0 <= t < 3600 for key in ("dense", "overview", "cut_context", "short") for t in plan[key])
    assert plan["dense_step"] > .25  # reduced long-clip coverage is disclosed
    plan = sampling_plan({"duration_seconds": .02, "fps": 30}, {"candidate_cuts": [], "candidate_intervals": []})
    assert plan["dense"] == [0]


def test_shared_material_text_preserves_evidence_and_actual_image_slots(staged):
    report, shots, transcript = prepare_video(staged)
    text = prepared_evidence_text(report, shots, transcript, [2, 10])
    assert "随请求第1张图 = image2 = @图片2" in text
    assert "随请求第2张图 = image10 = @图片10" in text
    assert "从随请求第3张开始" in text
    for label, value in (("视频信息：", report["video"]), ("采样覆盖：", report["coverage"]),
                         ("候选切点：", shots["candidate_cuts"]), ("音轨自动转写：", transcript),
                         ("声音变化复核证据：", report["voice_evidence"])):
        assert label + json.dumps(value, ensure_ascii=False) in text
    for sheet in report["sheets"]:
        assert sheet["kind"] in text and json.dumps(sheet["actual_times"]) in text
    assert "插件时长策略" not in text and "最终交付要求" not in text and "/viral-variation" not in text


class PreparedGateway:
    """Optionally request a real MCP detail frame before returning a draft."""
    def __init__(self, detail=False, segments=None, before_final=None, segment_call=None, on_request=None, final_texts=None):
        self.requests = []
        self.errors = []
        self.final_count = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                if on_request:
                    on_request(body, len(outer.requests))
                segment_turn = segment_call if segment_call is not None else (2 if detail else 1)
                call = (detail and len(outer.requests) == 1) or (segments is not None and len(outer.requests) == segment_turn)
                delta = {"role": "assistant"}
                if call:
                    names = [t["function"]["name"] for t in body["tools"]]
                    suffix = {"voice": "analyze_voices", "speakers": "diarize_speakers"}.get(detail, "get_frames")
                    name = next(n for n in names if n.endswith(suffix))
                    arguments = ({"start": .25, "end": 1.25} if detail == "voice" else
                                 {} if detail == "speakers" else {"times": [.25, 1.25]})
                    if segments is not None and len(outer.requests) == segment_turn:
                        name = next(n for n in names if n.endswith("set_video_segments"))
                        arguments = {"segments": segments}
                    delta["tool_calls"] = [{"index": 0, "id": "details", "type": "function",
                                            "function": {"name": name, "arguments": json.dumps(arguments)}}]
                else:
                    if before_final:
                        before_final()
                    values = final_texts or ["本地测试提示词完成"]
                    delta["content"] = values[min(outer.final_count, len(values) - 1)]
                    outer.final_count += 1
                chunk = {"id": "local-video", "object": "chat.completion.chunk", "created": 1,
                         "model": "gpt-6.1-sol", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                end = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if call else "stop"}]}
                raw = ("".join("data: " + json.dumps(x) + "\n\n" for x in (chunk, end)) + "data: [DONE]\n\n").encode()
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


@pytest.mark.parametrize("detail", [False, True, "voice", "speakers"])
def test_actual_harness_first_request_has_external_rules_evidence_and_images(staged, detail):
    import shutil
    gateway = PreparedGateway(detail)
    try:
        with workflow_bridge("local-test-fake-key", gateway.url, "gpt-6.1-sol", 60) as bridge:
            bridge.cfg["video_prompt_only"] = True
            source = Path(bridge.cfg["workspace"])
            source.mkdir(parents=True)
            shutil.copyfile(staged.parent / "source-video.mp4", source / "source-video.mp4")
            output = source / "media-analysis"
            output.mkdir()
            # Configure the same MCP server as the full-video node.
            from dsh_bridge import paths
            bridge.cfg["media_mcp"] = {"serverName": "video", "transport": "stdio", "command": sys.executable,
                "args": ["-u", str(paths.PACKAGE_DIR / "dsh_bridge/media_server.py"),
                         "--video", str(source / "source-video.mp4"), "--output", str(output)],
                "cwd": str(source), "startupTimeoutMs": 30000, "failOnStartupError": True}
            report, shots, transcript = prepare_video(output)
            rules = "外接规则标记123：按中文章节输出，保留素材中的动作与镜头。"
            requirement = "本次用户要求标记456：人物图1、商品图2。"
            bridge.cfg["video_system_prompt"] = rules
            prompt, sheets = initial_request(output, report, shots, transcript, requirement, rules, image_slots=[1, 2])
            ref = io.BytesIO()
            Image.new("RGB", (32, 32), "green").save(ref, "PNG")
            refs = [base64.b64encode(ref.getvalue()).decode()] * 2
            answer = bridge.ask(bridge.session_id("video-only"), prompt, refs + sheets)
            assert answer["text"] == "本地测试提示词完成"
            assert len(gateway.requests) == (2 if detail else 1)
            first = gateway.requests[0]
            wire = json.dumps(first, ensure_ascii=False)
            texts = []
            images = []
            for message in first["messages"]:
                blocks = message.get("content") or []
                if isinstance(blocks, str):
                    texts.append(blocks)
                else:
                    texts.extend(b.get("text", "") for b in blocks)
                    images.extend(b for b in blocks if b.get("type") == "image_url")
            combined = "\n".join(texts)
            assert rules in combined and requirement in combined
            system = json.dumps([m for m in first["messages"] if m["role"] == "system"], ensure_ascii=False)
            user = json.dumps([m for m in first["messages"] if m["role"] == "user"], ensure_ascii=False)
            assert rules in system and rules not in user
            assert requirement in user and requirement not in system
            assert combined.index(rules) < combined.index(requirement)
            assert "<skill_content" not in combined and "/viral-variation" not in combined
            assert len(images) == len(sheets) + 2
            names = {t["function"]["name"] for t in first["tools"]}
            assert not names.intersection({"read", "read_image", "glob", "grep", "working_directory"})
            assert "skill" not in names
            assert "候选切点" in wire and "视频中没有可解码音轨" in wire
            assert "声音变化复核证据" in wire
            assert any(n.endswith("analyze_voices") for n in names)
            assert any(n.endswith("diarize_speakers") for n in names)
            assert "h3-prompt-writing" not in wire
            assert "先使用 skill 工具" not in wire
            assert not (Path(bridge.cfg["dsh_home"]) / "skills").exists()
            calls = [e for e in answer["events"] if e.get("type") == "tool/call"]
            assert not any(e["data"]["name"] == "skill" for e in calls)
            if detail:
                suffix = {"voice": "analyze_voices", "speakers": "diarize_speakers"}.get(detail, "get_frames")
                assert len(calls) == 1 and calls[0]["data"]["name"].endswith(suffix)
                assert "isError" not in json.dumps(gateway.requests[-1]["messages"])
                assert (output / "tool_activity.jsonl").is_file()
                if detail == "speakers":
                    evidence = json.loads((output / "speaker_evidence.json").read_text(encoding="utf-8"))
                    assert evidence["status"] == "no_audio" and evidence["speaker_count"] is None
    finally:
        gateway.close()
