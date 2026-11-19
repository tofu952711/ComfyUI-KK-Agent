"""Concurrency, plan revisions and job lifetime without paid model calls."""
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge import parallel_video as module

INFO = {"duration_seconds": 2, "fps": 10}
FIRST = [{"start": 0, "end": 1}, {"start": 1, "end": 2}]
SECOND = [{"start": 0, "end": .5}, {"start": .5, "end": 2}]


def save_plan(output, ranges):
    path = output / "video_segments.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"segments": ranges}), encoding="utf-8")
    temporary.replace(path)


def test_revision_discards_inflight_result(tmp_path, monkeypatch):
    began, release, published = threading.Event(), threading.Event(), threading.Event()
    calls, clips = [], []
    def encode(source, output, info, keep_audio, *, ranges, check_current, on_clip):
        calls.append(ranges)
        if len(calls) == 1:
            began.set()
            assert release.wait(3)
        check_current()
        on_clip(1, ranges[0], b"encoded", .01)
        return [ranges], {}
    monkeypatch.setattr(module, "build_video_outputs", encode)
    def notify(kind, **data):
        if kind == "clip":
            clips.append(data)
            published.set()
    save_plan(tmp_path, FIRST)
    with module.ParallelVideoOutputs(None, tmp_path, INFO, notify=notify) as cutter:
        assert began.wait(3)
        save_plan(tmp_path, SECOND)
        release.set()
        assert published.wait(3)  # Published before finish() is called.
        values, evidence = cutter.finish()
        assert values == [SECOND]
        assert [clip["revision"] for clip in clips] == [2]
        assert evidence["plan_revision"] == 2
    assert not cutter._thread.is_alive()


def test_no_plan_and_encoder_failure(tmp_path, monkeypatch):
    calls = []
    def encode(*args, ranges, **kwargs):
        calls.append(ranges)
        return ["whole"], {}
    monkeypatch.setattr(module, "build_video_outputs", encode)
    with module.ParallelVideoOutputs(None, tmp_path, INFO) as cutter:
        assert not calls  # Fallback starts only after the model has finished.
        assert cutter.finish()[0] == ["whole"]
    assert calls == [None]
    def fail(*args, **kwargs):
        raise OSError("disk test failure")
    monkeypatch.setattr(module, "build_video_outputs", fail)
    with pytest.raises(RuntimeError, match="disk test failure"):
        with module.ParallelVideoOutputs(None, tmp_path, INFO) as cutter:
            cutter.finish()
    assert not cutter._thread.is_alive()


def test_model_failure_joins_encoder_before_cleanup(tmp_path, monkeypatch):
    began, stopped = threading.Event(), threading.Event()
    def encode(*args, check_current, **kwargs):
        began.set()
        while True:
            if stopped.wait(.01):
                check_current()
    monkeypatch.setattr(module, "build_video_outputs", encode)
    save_plan(tmp_path, FIRST)
    with pytest.raises(ValueError, match="model failed"):
        with module.ParallelVideoOutputs(None, tmp_path, INFO) as cutter:
            assert began.wait(3)
            stopped.set()
            raise ValueError("model failed")
    assert not cutter._thread.is_alive()
