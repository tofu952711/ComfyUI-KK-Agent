"""Real Comfy scheduler with blocking sync mask and concurrent A/B inference."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types

parser = argparse.ArgumentParser()
parser.add_argument("--comfy-root", required=True, type=Path)
parser.add_argument("--chain", choices=["A", "B"], required=True)
args = parser.parse_args()
DSH_ROOT = Path(__file__).resolve().parents[1]
ROOT = DSH_ROOT
COMFY = args.comfy_root
sys.path[:0] = [str(COMFY), str(DSH_ROOT), str(DSH_ROOT / "tests")]
temporary = tempfile.TemporaryDirectory(prefix="sync-mask-concurrency-")
DATA = Path(temporary.name)
os.environ["DSH_BRIDGE_DATA_DIR"] = str(DATA / "dsh")
from aiohttp import web
server = types.ModuleType("server")
server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(
    routes=web.RouteTableDef(), send_sync=lambda *a, **k: None, client_id=None, last_node_id=None))
sys.modules["server"] = server
spec = importlib.util.spec_from_file_location("sync_concurrency_plugin", ROOT / "__init__.py",
                                             submodule_search_locations=[str(ROOT)])
pkg = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pkg
spec.loader.exec_module(pkg)
from comfy_api.latest import InputImpl, io
from execution import PromptExecutor, CacheType, validate_prompt
import folder_paths
import nodes
from test_video_preparation import PreparedGateway
from b_parallel_gateway import BParallelGateway
from dsh_bridge.ffmpeg_segments import executables

folder_paths.set_temp_directory(str(DATA / "temp"))
folder_paths.set_output_directory(str(DATA / "output"))
source = DATA / "source.mp4"
duration = 2 if args.chain == "A" else 32
ffmpeg, _ = executables()
subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                f"testsrc2=size=96x64:rate=12:duration={duration}", "-c:v", "libx264", str(source)],
               check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
inference_started, mask_finished = threading.Event(), threading.Event()
observations = []

def concurrent_request(*unused):
    inference_started.set()
    observations.append("inference_started")
    assert mask_finished.wait(20), "mask did not complete during pending inference"

if args.chain == "A":
    approved = json.dumps({"status": "approved", "checks": {"consistent": True}, "issues": [], "edits": []})
    gateway = PreparedGateway(on_request=lambda body, index: concurrent_request() if index == 1 else None,
                              final_texts=["SYNC_CONCURRENT_DRAFT", approved])
else:
    gateway = BParallelGateway([{"start": 0, "end": 16}, {"start": 16, "end": 32}],
                               on_coordinator=concurrent_request)

class Source(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="SyncSource", inputs=[], outputs=[io.Video.Output()])

    @classmethod
    def execute(cls):
        return io.NodeOutput(InputImpl.VideoFromFile(str(source)))

class BlockingMask(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="BlockingSyncMask", inputs=[io.Video.Input("video")],
                         outputs=[], is_output_node=True)

    @classmethod
    def execute(cls, video):
        # Like actual DefaceBlur, this is a synchronous node on Comfy's
        # execution loop. It cannot service another async scheduling turn.
        observations.append("sync_mask_entered")
        assert inference_started.wait(20), "sync mask blocked inference submission"
        observations.append("sync_mask_finished_while_inference_pending")
        mask_finished.set()
        return io.NodeOutput()

nodes.NODE_CLASS_MAPPINGS.update(pkg.NODE_CLASS_MAPPINGS)
nodes.NODE_CLASS_MAPPINGS.update(SyncSource=Source, BlockingSyncMask=BlockingMask)
prefix = "DSH"
graph = {
    "source": {"class_type": "SyncSource", "inputs": {}},
    "stage": {"class_type": prefix + "_VideoSegments", "inputs": {
        "video": ["source", 0], "api_key": "local-only", "base_url": gateway.url,
        "model": "gpt-6.1-sol", "api_protocol": "openai-completions", "review_ai": "沿用当前AI",
        "requirement": "LOCAL_SYNC_CONCURRENCY", "rules_text": "Return a short draft",
        "segment_rules_text": "call set_video_segments", "chain_b_reverse_rules_text": "reverse each segment",
        "timeout_s": 90, "max_tokens": 2048}},
    "reverse": {"class_type": prefix + "_VideoReverse", "inputs": {"context": ["stage", 8]}},
    "mask": {"class_type": "BlockingSyncMask", "inputs": {"video": ["stage", 3]}},
}

async def run():
    valid = await validate_prompt("sync-concurrency", graph, None)
    assert valid[0], valid
    executor = PromptExecutor(server.PromptServer.instance, cache_type=CacheType.CLASSIC,
                              cache_args={"ram": 0, "ram_inactive": 0})
    await executor.execute_async(graph, "sync-concurrency", execute_outputs=["reverse", "mask"])
    assert executor.success, executor.status_messages
    assert mask_finished.is_set() and inference_started.is_set()
    if hasattr(gateway, "errors"):
        assert not gateway.errors, gateway.errors
    print("SYNC_MASK_CONCURRENT_INFERENCE_OK", json.dumps({"backend": prefix, "chain": args.chain,
                                                           "observations": observations}), flush=True)

try:
    asyncio.run(run())
finally:
    gateway.close()
    pkg.BRIDGE.close()
