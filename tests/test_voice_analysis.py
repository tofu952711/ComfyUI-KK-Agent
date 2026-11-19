"""Acoustic evidence must not turn pitch or silence into speaker identities."""
import json
import sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.voice_analysis import analyze
from dsh_bridge.video_preparation import voice_context
from dsh_bridge.media_tools import MediaTools


def tone(freq, duration=1.5, gain=.1):
    time = np.arange(round(duration * 16000)) / 16000
    return (gain * (np.sin(2 * np.pi * freq * time) + .25 * np.sin(2 * np.pi * freq * 2 * time))).astype(np.float32)


def test_acoustic_change_is_not_a_speaker_count():
    report = analyze(np.concatenate([tone(150), tone(310)]), offset=5)
    assert report["speaker_count"] is None
    assert any(abs(c["time"] - 6.5) < .35 for c in report["change_candidates"])
    assert report["windows"][0]["pitch_median_hz"] == pytest.approx(150, abs=5)
    assert report["windows"][-1]["pitch_median_hz"] == pytest.approx(310, abs=8)
    assert all("speaker_id" not in c and "gender" not in c for c in report["change_candidates"])
    json.dumps(report, allow_nan=False)


def test_gain_change_and_silence_do_not_force_extra_speakers():
    same_pitch = analyze(np.concatenate([tone(180), tone(180, gain=.3)]))
    assert not same_pitch["change_candidates"]
    for samples in [np.zeros(32000), np.zeros(0), np.zeros(300)]:
        report = analyze(samples)
        assert not report["change_candidates"] and report["speaker_count"] is None
        assert not any(w["pitch_median_hz"] for w in report["windows"])
        json.dumps(report, allow_nan=False)


def test_candidate_frame_bounds_and_transcript_context():
    report = analyze(np.concatenate([tone(150), tone(310)]))
    frames = voice_context(report, {"tokens": ["问", "答"], "timestamps": [1., 2.]}, 3, 12)
    assert frames and all(0 <= t <= 3 - 1/12 for _, times in frames for t in times)
    assert report["change_candidates"][0]["transcript_context"]["before"] == "问"
    assert report["change_candidates"][0]["transcript_context"]["after"] == "答"


def test_local_voice_range_uses_original_video_seconds(tmp_path, monkeypatch):
    video = tmp_path / "placeholder.mp4"
    video.touch()
    tools = MediaTools(video, tmp_path / "analysis")
    monkeypatch.setattr(tools, "audio_samples", lambda: (np.concatenate([tone(150), tone(310)]), .25))
    monkeypatch.setattr(tools, "info", lambda: {"duration_seconds": 3.5})
    result = tools.analyze_voices(start=1., end=2.5)
    assert result["range"] == {"start": 1., "end": 2.5}
    assert result["speaker_count"] is None
    for start, end in [(-1, 2), (2, 1), (0, float("inf")), (0, 4)]:
        with pytest.raises(ValueError):
            tools.analyze_voices(start=start, end=end)
    cached = tools.analyze_voices()
    monkeypatch.setattr(tools, "audio_samples", lambda: pytest.fail("unnecessary audio decode"))
    assert tools.analyze_voices() == cached
