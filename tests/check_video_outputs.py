"""CPU video/audio output checks using real ComfyUI; no model requests."""
import argparse
from fractions import Fraction
import io
import json
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--comfy-root", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.comfy_root.resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import av
import numpy as np
from comfy_execution.graph_utils import ExecutionBlocker
from dsh_bridge.video_outputs import build_video_outputs


with tempfile.TemporaryDirectory(prefix="dsh-output-check-") as job:
    source = Path(job) / "source.mp4"
    with av.open(str(source), "w") as container:
        video = container.add_stream("libx264", rate=10)
        video.width, video.height, video.pix_fmt = 96, 64, "yuv420p"
        audio = container.add_stream("aac", rate=16000)
        audio.layout = "mono"
        for index in range(20):
            rgb = np.zeros((64, 96, 3), dtype=np.uint8)
            rgb[:, :, 0 if index < 10 else 2] = 255
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 10)
            container.mux(video.encode(frame))
        wave = (.2 * np.sin(2 * np.pi * 440 * np.arange(32000) / 16000)).astype(np.float32)[None, :]
        frame = av.AudioFrame.from_ndarray(wave, format="fltp", layout="mono")
        frame.sample_rate, frame.pts, frame.time_base = 16000, 0, Fraction(1, 16000)
        container.mux(audio.encode(frame))
        container.mux(video.encode())
        container.mux(audio.encode())
    checks = []
    for count in (1, 5):
        for keep in (True, False):
            output = Path(job) / f"output-{count}-{keep}"
            output.mkdir()
            if count > 1:
                plan = [{"start": index * .4, "end": (index + 1) * .4} for index in range(count)]
                (output / "video_segments.json").write_text(json.dumps({"segments": plan}), encoding="utf-8")
            values, evidence = build_video_outputs(source, output, {"duration_seconds": 2, "fps": 10}, keep_audio=keep)
            checks.append((values, count, keep))
            assert evidence["keep_audio"] is keep and evidence["count"] == count
    source.unlink()  # Prove no returned VIDEO depends on the staged source.
    for values, count, keep in checks:
        for index, value in enumerate(values):
            if index >= count:
                assert isinstance(value, ExecutionBlocker)
                continue
            buffer = value.get_stream_source()
            buffer.seek(0)
            with av.open(buffer) as container:
                assert bool(container.streams.audio) is keep
                assert len(container.streams.video) == 1
                stream = container.streams.video[0]
                frames = list(container.decode(stream))
                assert len(frames) == (20 if count == 1 else 4)
                assert abs(float(stream.duration * stream.time_base) - 2 / count) < .05
            buffer.seek(0)
            if keep:
                with av.open(buffer) as container:
                    assert sum(frame.samples for frame in container.decode(audio=0)) > 0
            buffer.seek(0)
            # A downstream SaveVideo-style save must work after source cleanup.
            saved = io.BytesIO()
            value.save_to(saved, format="mp4", codec="h264")
            saved.seek(0)
            with av.open(saved) as container:
                assert bool(container.streams.audio) is keep
        print("VIDEO_OUTPUT_AUDIO_AND_CLEANUP_OK", count, keep)
