"""Real Comfy scheduler: short-video processing/save overlaps A model inference.

Uses only a localhost model gateway and a synthetic video. No paid API calls.
"""
import argparse
import asyncio
from contextlib import contextmanager
import importlib.util
import io as stdio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types

parser = argparse.ArgumentParser()
parser.add_argument("--comfy-root", required=True, type=Path)
parser.add_argument("--reverse-fails", action="store_true")
parser.add_argument("--file-like", action="store_true")
parser.add_argument("--audio-bindings", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
job = tempfile.TemporaryDirectory(prefix="dsh-a-scheduler-")
DATA = Path(job.name)
os.environ["DSH_BRIDGE_DATA_DIR"] = str(DATA / "diagnostics")
sys.path[:0] = [str(args.comfy_root), str(ROOT / "tests")]
from aiohttp import web
server = types.ModuleType("server")
server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(
    routes=web.RouteTableDef(), send_sync=lambda *a, **k: None, client_id=None, last_node_id=None))
sys.modules["server"] = server
spec = importlib.util.spec_from_file_location("dsh_a_scheduler", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
pkg = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pkg
spec.loader.exec_module(pkg)
from comfy_api.latest import InputImpl, Types, io
from comfy_execution.graph_utils import ExecutionBlocker
from comfy_extras.nodes_video import SaveVideo
from execution import PromptExecutor, CacheType, validate_prompt
import folder_paths
import nodes
import torch
import av
from fractions import Fraction
from test_video_preparation import PreparedGateway

folder_paths.set_output_directory(str(DATA / "output"))
folder_paths.set_temp_directory(str(DATA / "previews"))
pixels = torch.zeros((24, 64, 96, 3))
pixels[..., 0] = 1
source_path = DATA / "source.mp4"
InputImpl.VideoFromComponents(Types.VideoComponents(images=pixels, frame_rate=Fraction(12))).save_to(str(source_path))
original_bytes = source_path.read_bytes()
source_video = InputImpl.VideoFromFile(stdio.BytesIO(original_bytes) if args.file_like else str(source_path))
started, processed, saved = threading.Event(), threading.Event(), threading.Event()
events = []


def on_request(body, index):
    if index == 2:
        return  # independent A reviewer receives the draft after video saving
    assert index == 1, "A must not split or repeat inference"
    assert all(not tool["function"]["name"].endswith("set_video_segments") for tool in body["tools"])
    if args.audio_bindings:
        wire=json.dumps(body,ensure_ascii=False)
        assert all(f"音频{i}绑定模特{i}" in wire for i in (1,2,3))
        assert "input_audio" not in wire and "waveform" not in wire
        print("A_THREE_AUDIO_BINDINGS_SENT_WITHOUT_AUDIO_CONTENT_OK")
    started.set()
    assert saved.wait(20), "Video processing/save did not run during model inference"


gateway = PreparedGateway(on_request=on_request, final_texts=["A完整反推提示词", json.dumps({"status":"approved","checks":{"consistent":True},"issues":[],"edits":[]})])
if args.reverse_fails:
    a_module = sys.modules[pkg.NODE_CLASS_MAPPINGS["DSH_FullVideoAgent"].__module__]
    original_bridge = a_module.workflow_bridge

    @contextmanager
    def failing_bridge(*a, **k):
        with original_bridge(*a, **k) as bridge:
            def fail(*a, **k):
                started.set()
                assert saved.wait(20)
                raise RuntimeError("A model failure after video saved")
            bridge.ask = fail
            yield bridge
    a_module.workflow_bridge = failing_bridge


class Source(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="ASource", inputs=[], outputs=[io.Video.Output()])

    @classmethod
    def execute(cls):
        return io.NodeOutput(source_video)


class AudioReferenceSource(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="AudioReferenceSource",inputs=[],outputs=[io.Audio.Output()])
    @classmethod
    def execute(cls):
        return io.NodeOutput({"do_not_inspect_or_transcribe": True})


class UnusedBReview(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="UnusedBReview", inputs=[], outputs=[io.String.Output()])
    @classmethod
    def execute(cls):
        raise AssertionError("A must not evaluate B review rules")


class ProcessVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="AProcessVideo", inputs=[io.Video.Input("video")], outputs=[io.Video.Output()])

    @classmethod
    def execute(cls, video):
        assert started.wait(20), "A must start inference before downstream processing completes"
        assert video is source_video, "video1 must pass through original VIDEO"
        components = video.get_components()
        assert float(components.images[..., 0].mean()) > .9
        # Stand-in for masking: perform a real decode, process pixels, and save
        # a different video, while A uses its already-staged private source.
        masked = torch.zeros_like(components.images)
        processed.set()
        events.append("processed_while_model_waiting")
        return io.NodeOutput(InputImpl.VideoFromComponents(Types.VideoComponents(
            images=masked, frame_rate=components.frame_rate, audio=components.audio)))


class CheckedSave(SaveVideo):
    @classmethod
    def execute(cls, *a, **k):
        assert started.is_set() and processed.is_set()
        result = super().execute(*a, **k)
        files = list((DATA / "output").glob("A/*.mp4"))
        assert len(files) == 1
        with av.open(str(files[0])) as container:
            frames = list(container.decode(video=0))
            assert len(frames) == 24
            assert float(frames[0].to_ndarray(format="rgb24").mean()) < 3
        saved.set()
        events.append("saved_before_model_returned")
        return result


nodes.NODE_CLASS_MAPPINGS.update(pkg.NODE_CLASS_MAPPINGS)
nodes.NODE_CLASS_MAPPINGS.update(ASource=Source, AProcessVideo=ProcessVideo, SaveVideo=CheckedSave, UnusedBReview=UnusedBReview, AudioReferenceSource=AudioReferenceSource)
stage = pkg.NODE_CLASS_MAPPINGS["DSH_VideoSegments"]
stage.GET_SCHEMA()
graph = {
    "source": {"class_type": "ASource", "inputs": {}},
    "b_review": {"class_type": "UnusedBReview", "inputs": {}},
    "stage": {"class_type": "DSH_VideoSegments", "inputs": {
        "video": ["source", 0], "api_key": "local-only", "base_url": gateway.url,
        "model": "gpt-6.1-sol", "requirement": "A user", "rules_text": "A rules",
        "segment_rules_text": "", "chain_b_reverse_rules_text": "",
        "chain_b_review_rules_text": ["b_review", 0],
        "review_ai": "沿用当前AI", "review_ai.api_key": "", "review_ai.base_url": "",
        "review_ai.model": "", "review_ai.api_protocol": "openai-completions",
        "api_protocol": "openai-completions", "timeout_s": 60, "max_tokens": 2048}},
    "reverse": {"class_type": "DSH_VideoReverse", "inputs": {"context": ["stage", 8]}},
    "process": {"class_type": "AProcessVideo", "inputs": {"video": ["stage", 3]}},
    "save": {"class_type": "SaveVideo", "inputs": {"video": ["process", 0],
        "filename_prefix": "A/masked", "format": "mp4", "format.codec": "h264"}},
    "unused": {"class_type": "SaveVideo", "inputs": {"video": ["stage", 4],
        "filename_prefix": "unused", "format": "mp4", "format.codec": "h264"}},
}


if args.audio_bindings:
    for i in (1,2,3):
        graph[f"audio_source{i}"]={"class_type":"AudioReferenceSource","inputs":{}}
        graph["stage"]["inputs"][f"audio{i}"]=[f"audio_source{i}",0]

async def run():
    valid = await validate_prompt("a-overlap-test", graph, None)
    assert valid[0], valid
    executor = PromptExecutor(server.PromptServer.instance, cache_type=CacheType.CLASSIC,
                              cache_args={"ram": 0, "ram_inactive": 0})
    await executor.execute_async(graph, "a-overlap-test", execute_outputs=["reverse", "save", "unused"])
    assert executor.success == (not args.reverse_fails), executor.status_messages
    assert saved.is_set() and processed.is_set()
    assert not list((DATA / "output").glob("unused*.mp4"))
    assert source_path.read_bytes() == original_bytes
    if not args.reverse_fails:
        assert len(gateway.requests) == 2
    print("REAL_A_VIDEO1_PROCESSING_AND_SAVE_OVERLAP_OK", json.dumps({
        "file_like": args.file_like, "model_fails": args.reverse_fails, "events": events}))


try:
    asyncio.run(run())
finally:
    gateway.close()
    pkg.BRIDGE.close()
