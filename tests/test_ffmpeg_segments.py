"""Real FFmpeg exports, frame alignment, audio policy and atomic publication."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge import ffmpeg_segments
from dsh_bridge.media_tools import MediaTools


@pytest.fixture
def source(tmp_path):
    ffmpeg, _ = ffmpeg_segments.executables()
    path = tmp_path / "source.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-n", "-f", "lavfi", "-i",
        "testsrc2=size=96x64:rate=12:duration=2", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264",
        "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return path


@pytest.mark.parametrize("keep_audio", [True, False])
@pytest.mark.parametrize("count", [2, 5])
def test_ai_tool_exports_before_return_and_preserves_all_frames(source, tmp_path, keep_audio, count):
    tools = MediaTools(source, tmp_path / "analysis")
    tools._write_json("duration_policy.json", {"chain": "B", "phase": "segment", "keep_audio": keep_audio})
    requested = ([{"start": 0, "end": .99}, {"start": .99, "end": 2}] if count == 2 else
        [{"start": i * .4, "end": (i + 1) * .4} for i in range(5)])
    result = tools.set_video_segments(requested)
    assert result["status"] == "ready" and result["materialized"]
    assert result["executor"] == "ai_invoked_media_tool" and result["tool_backend"] == "ffmpeg"
    assert result["requested_segments"] == requested
    if count == 2:
        assert result["segments"] == [{"start": 0, "end": 1}, {"start": 1, "end": 2}]
    assert result["count"] == count
    assert result["frame_coverage_validated"]
    assert result["source_frames"] == sum(result["exported_frames"]) == 24
    assert result["keep_audio"] == keep_audio
    assert all(abs(duration - 2 / count) < .1 for duration in result["actual_durations"])
    _, ffprobe = ffmpeg_segments.executables()
    for name in result["files"]:
        path = tools.output / name
        assert path.is_file() and path.stat().st_size > 0
        inspected = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        streams = json.loads(inspected.stdout)["streams"]
        assert any(item["codec_type"] == "audio" for item in streams) == keep_audio
    published = (tools.output / "video_segments.json").read_bytes()
    # Failed corrections cannot replace previously finished tool outputs.
    with pytest.raises(ValueError):
        tools.set_video_segments([{"start": 0, "end": .8}, {"start": .9, "end": 2}])
    assert (tools.output / "video_segments.json").read_bytes() == published
    tools._write_json("duration_policy.json", {"chain": "B", "phase": "reverse"})
    with pytest.raises(ValueError, match="禁止修改"):
        tools.set_video_segments(requested)
    assert (tools.output / "video_segments.json").read_bytes() == published
