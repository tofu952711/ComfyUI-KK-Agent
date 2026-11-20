"""Skip only undecodable B tail samples, retaining strict A/frame validation."""
import json
from pathlib import Path
import sys

import av
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.media_tools import MediaTools
from dsh_bridge.b_video_preparation import BTailMediaTools, prepare_b_video
from dsh_bridge.b_segment_media import SegmentMediaTools


@pytest.fixture
def last_frame_cut(tmp_path):
    source = tmp_path / "source-video.mp4"
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "yuv420p"
        for index in range(60):
            rgb = np.zeros((64, 96, 3), dtype=np.uint8)
            rgb[:, :, 0 if index < 59 else 2] = 255
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return source


def test_b_skips_missing_tail_and_a_stays_strict(last_frame_cut, tmp_path):
    request = [0., .5, 1.9833335]
    strict = MediaTools(last_frame_cut, tmp_path / "a")
    with pytest.raises(ValueError, match="超出可解码"):
        strict.cache_frames(request, sequential=True)
    tools = BTailMediaTools(last_frame_cut, tmp_path / "b")
    assert tools.cache_frames(request, sequential=True) == [0., .5]
    assert tools.skipped_tail_times == {1.9833335}
    assert tools.last_decodable_time == pytest.approx(59/30)
    assert tools._time_key(1.9833335) not in tools._frame_index
    meta, image = tools.frames([.5, 1.9833335])
    assert image and meta["requested_times"] == [.5]
    assert meta["skipped_tail_times"] == [1.9833335]
    with pytest.raises(ValueError, match="全部位于最后真实帧"):
        tools.frames([1.9833335])
    for bad in [[-1], [2], [float("nan")]]:
        with pytest.raises(ValueError):
            tools.cache_frames(bad)


def test_b_full_preparation_keeps_rows_and_discloses_skip(last_frame_cut, tmp_path):
    output = tmp_path / "prepared"
    output.mkdir()
    report, shots, transcript = prepare_b_video(output)
    assert report["video"]["duration_seconds"] == 2
    assert report["coverage"]["skipped_tail_times"]
    assert report["coverage"]["short_interval_frames"] == 0
    assert transcript["has_audio"] is False
    for sheet in report["sheets"]:
        assert max(sheet["actual_times"]) <= 59/30 + 1e-6
        assert (output / sheet["file"]).is_file()
        if sheet["kind"] == "候选切点四帧对照":
            assert len(sheet["actual_times"]) == len(sheet["candidate_cut_times"]) * 4
    assert json.loads((output / "b_tail_sampling.json").read_text(encoding="utf-8"))["skipped_times"]
    # Child tool calls apply the same B-only tail policy and keep local labels.
    (output / "b_segment_scope.json").write_text(json.dumps({"start": 1., "end": 2.,
        "context_start": .5, "context_end": 2., "index": 2, "count": 2}), encoding="utf-8")
    child = SegmentMediaTools(last_frame_cut, output)
    meta, _ = child.frames([1.5, 1.9833335])
    assert meta["local_times"] == [.5]
    assert meta["skipped_tail_times"] == [1.9833335]


def test_b_does_not_hide_interior_decode_misses(last_frame_cut, tmp_path, monkeypatch):
    tools = BTailMediaTools(last_frame_cut, tmp_path / "b")
    def missing(*args, **kwargs):
        raise ValueError("请求时间超出可解码视频范围，请稍向前取帧")
    monkeypatch.setattr(MediaTools, "cache_frames", missing)
    with pytest.raises(ValueError, match="超出可解码"):
        tools.cache_frames([.5])
    assert not tools.skipped_tail_times
