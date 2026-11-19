"""Speaker identity comes from clustering, never from a change in pitch.

Native config construction is exercised with a deterministic inference stub;
real-model timings are verified separately and are not claimed by these tests.
"""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.media_tools import MediaTools, definitions
from dsh_bridge.speaker_analysis import SpeakerAnalyzer, availability, settings


@pytest.fixture
def native_stub(tmp_path, monkeypatch):
    import sherpa_onnx
    directory = tmp_path / "models"
    directory.mkdir()
    for name in ("segmentation.onnx", "speaker_embedding.onnx"):
        (directory / name).write_bytes(b"test model placeholder")
    calls = []
    segments = [SimpleNamespace(speaker=8, start=0., end=1.2),
                SimpleNamespace(speaker=3, start=.8, end=2.),
                SimpleNamespace(speaker=8, start=2., end=3.)]

    class Engine:
        def __init__(self, config):
            calls.append(config)

        def process(self, samples):
            return SimpleNamespace(sort_by_start_time=lambda: segments)

    monkeypatch.setattr(sherpa_onnx, "OfflineSpeakerDiarization", Engine)
    monkeypatch.setenv("DSH_BRIDGE_SPEAKER_MODEL_DIR", str(directory))
    monkeypatch.setenv("DSH_BRIDGE_SPEAKER_PROVIDER", "cpu")
    return directory, calls, segments


def test_native_config_ids_original_timeline_and_overlap(native_stub):
    directory, calls, _ = native_stub
    analyzer = SpeakerAnalyzer(directory, "cpu")
    t = np.arange(48000) / 16000
    samples = (.1 * np.sin(2 * np.pi * 160 * t)).astype(np.float32)
    report = analyzer.analyze(samples, offset=.25)
    assert len(calls) == 1 and calls[0].embedding.provider == "cpu"
    assert calls[0].clustering.num_clusters == -1
    assert report["speaker_count"] == 2
    assert [s["speaker_id"] for s in report["segments"]] == ["speaker_0", "speaker_1", "speaker_0"]
    assert report["segments"][0]["start"] == .25
    # Each voice excludes the 0.4s mixed interval from its acoustic statistics.
    assert report["speakers"][0]["acoustic_features"]["analyzed_windows"] < 2 * 50
    assert report["speakers"][0]["acoustic_features"]["pitch_median_hz"] == pytest.approx(160, abs=5)
    assert report["speakers"][0]["acoustic_features"]["spectral_centroid_median_hz"] > 0
    assert all("gender" not in s for s in report["speakers"])
    json.dumps(report, allow_nan=False)
    analyzer.analyze(samples)
    assert len(calls) == 1  # ONNX sessions reused within this process.
    analyzer.analyze(samples, num_speakers=2)
    assert len(calls) == 2 and calls[-1].clustering.num_clusters == 2


def test_model_update_reloads_sessions(native_stub):
    directory, calls, _ = native_stub
    analyzer = SpeakerAnalyzer(directory, "cpu")
    analyzer.analyze(np.zeros(48000))
    (directory / "speaker_embedding.onnx").write_bytes(b"updated weights of different size")
    analyzer.analyze(np.zeros(48000))
    assert len(calls) == 2


def test_no_audio_never_loads_model_and_no_speech_is_not_one_speaker(native_stub):
    directory, calls, segments = native_stub
    analyzer = SpeakerAnalyzer(directory, "cpu")
    assert analyzer.analyze(np.zeros(0))["status"] == "no_audio"
    assert not calls
    segments.clear()
    report = analyzer.analyze(np.zeros(16000))
    assert report["status"] == "no_speech_detected" and report["speaker_count"] == 0


@pytest.mark.parametrize("old_provider", [None, "cuda", "cpu"])
def test_cpu_is_used_even_with_old_provider_environment(native_stub, monkeypatch, old_provider):
    directory, calls, _ = native_stub
    if old_provider is None:
        monkeypatch.delenv("DSH_BRIDGE_SPEAKER_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("DSH_BRIDGE_SPEAKER_PROVIDER", old_provider)
    assert settings()["provider"] == "cpu"
    assert availability()["loaded"] is False and not calls
    SpeakerAnalyzer(directory).analyze(np.zeros(48000))
    assert calls[0].segmentation.provider == calls[0].embedding.provider == "cpu"


@pytest.mark.parametrize("options", [{"num_speakers": True}, {"num_speakers": -1},
                                     {"num_speakers": 1.5}, {"num_speakers": 21},
                                     {"threshold": float("nan")}, {"threshold": 0.}, {"threshold": True}])
def test_invalid_options_rejected_without_model(tmp_path, options):
    with pytest.raises(ValueError):
        SpeakerAnalyzer(tmp_path, "cpu").analyze(np.zeros(0), **options)


def test_missing_models_and_corrupt_samples_are_explicit(tmp_path):
    analyzer = SpeakerAnalyzer(tmp_path, "cpu")
    with pytest.raises(ValueError, match="缺少说话人模型"):
        analyzer.analyze(np.zeros(16000))
    with pytest.raises(ValueError, match="有限值"):
        analyzer.analyze(np.array([float("nan")]))


def test_job_disk_cache_and_model_change(native_stub, tmp_path, monkeypatch):
    directory, calls, _ = native_stub
    video = tmp_path / "source.mp4"
    video.touch()
    output = tmp_path / "analysis"
    monkeypatch.setattr(MediaTools, "audio_samples", lambda self: (np.zeros(48000), .25))
    first = MediaTools(video, output).diarize_speakers()
    monkeypatch.setattr(MediaTools, "audio_samples", lambda self: pytest.fail("unnecessary audio decode"))
    assert MediaTools(video, output).diarize_speakers() == first
    assert len(calls) == 1
    monkeypatch.setattr(MediaTools, "audio_samples", lambda self: (np.zeros(48000), .25))
    (directory / "segmentation.onnx").write_bytes(b"changed segmentation weights")
    second = MediaTools(video, output).diarize_speakers()
    assert second["cache_key"] != first["cache_key"] and len(calls) == 2
    third = MediaTools(video, output).diarize_speakers(threshold=.7)
    assert third["cache_key"] != second["cache_key"] and len(calls) == 3


def test_mcp_dispatch_real_stdio_no_audio(tmp_path):
    import av
    video = tmp_path / "source.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("libx264", rate=12)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuv420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), dtype=np.uint8), format="rgb24")
        for packet in list(stream.encode(frame)) + list(stream.encode()):
            container.mux(packet)
    script = Path(__file__).resolve().parents[1] / "dsh_bridge/media_server.py"
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "diarize_speakers", "arguments": {}}}]
    result = subprocess.run([sys.executable, str(script), "--video", str(video),
                             "--output", str(tmp_path / "analysis")],
                            input="".join(json.dumps(r) + "\n" for r in requests),
                            text=True, encoding="utf-8", capture_output=True, timeout=30, check=True)
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert any(t["name"] == "diarize_speakers" for t in responses[0]["result"]["tools"])
    assert "isError" not in responses[1]["result"]
    report = json.loads(responses[1]["result"]["content"][0]["text"])
    assert report["status"] == "no_audio" and report["speaker_count"] is None
    assert (tmp_path / "analysis/speaker_evidence.json").is_file()
