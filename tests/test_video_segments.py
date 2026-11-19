"""A rejected AI plan must never produce missing, overlapping or extra clips."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.video_segments import validate_segments
from dsh_bridge.media_tools import MediaTools


@pytest.mark.parametrize("plan", [
    [], [{"start": i, "end": i + 1} for i in range(6)],
    [{"start": 0, "end": 0}], [{"start": -1, "end": 2}],
    [{"start": 0.1, "end": 2}], [{"start": 0, "end": 1}],
    [{"start": 0, "end": 3}], [{"start": False, "end": 2}],
    [{"start": 0, "end": float("nan")}], [{"start": 0, "end": float("inf")}],
    [{"start": 0, "end": "2"}], [{"start": 0}],
    [{"start": 0, "end": 1}, {"start": 1.01, "end": 2}],
    [{"start": 0, "end": 1.1}, {"start": 1, "end": 2}],
])
def test_bad_plan_rejected(plan):
    with pytest.raises(ValueError):
        validate_segments(plan, 2, 30)


def test_final_time_rounding_and_latest_successful_plan(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"not decoded in this validation test")
    tool = MediaTools(video, tmp_path / "evidence")
    tool._cache["info"] = {"duration_seconds": 31.2, "fps": 30}
    first = tool.set_video_segments([{"start": 0, "end": 15}, {"start": 15, "end": 31.19}])
    assert first["segments"][-1]["end"] == 31.2
    with pytest.raises(ValueError):
        tool.set_video_segments([{"start": 5, "end": 31.2}])
    assert json.loads((tool.output / "video_segments.json").read_text(encoding="utf-8")) == first
    second = tool.set_video_segments([{"start": 0, "end": 31.2}])
    assert json.loads((tool.output / "video_segments.json").read_text(encoding="utf-8")) == second
