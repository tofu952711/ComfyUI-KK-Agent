"""Actual Comfy scheduler: stock SaveVideo writes while DSH reverse is pending."""
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
import time
import types

parser=argparse.ArgumentParser()
parser.add_argument("--comfy-root",required=True,type=Path)
parser.add_argument("--reverse-fails",action="store_true")
parser.add_argument("--review-linked",action="store_true")
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
job=tempfile.TemporaryDirectory(prefix="dsh-real-scheduler-")
DATA=Path(job.name)
os.environ["DSH_BRIDGE_DATA_DIR"]=str(DATA/"diagnostics")
sys.path[:0]=[str(args.comfy_root),str(ROOT/"tests")]
from aiohttp import web
events=[]
server=types.ModuleType("server")
server.PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(
    routes=web.RouteTableDef(),send_sync=lambda *a,**k:None,client_id=None,last_node_id=None))
sys.modules["server"]=server
spec=importlib.util.spec_from_file_location("dsh_stage_scheduler",ROOT/"__init__.py",submodule_search_locations=[str(ROOT)])
pkg=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=pkg
spec.loader.exec_module(pkg)
from comfy_api.latest import InputImpl,io
from comfy_extras.nodes_video import SaveVideo
import folder_paths
folder_paths.set_output_directory(str(DATA/"output"))
folder_paths.set_temp_directory(str(DATA/"previews"))
import nodes
from execution import PromptExecutor,CacheType,validate_prompt
from test_video_preparation import PreparedGateway
from b_parallel_gateway import BParallelGateway
from dsh_stage_scheduler.dsh_bridge.ffmpeg_segments import executables

source=DATA/"source.mp4"
ffmpeg,_=executables()
subprocess.run([ffmpeg,"-v","error","-n","-f","lavfi","-i",
    "testsrc2=size=96x64:rate=12:duration=32","-c:v","libx264",str(source)],
    check=True,capture_output=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
class Source(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="SchedulerSource",inputs=[],outputs=[io.Video.Output()])
    @classmethod
    def execute(cls):
        return io.NodeOutput(InputImpl.VideoFromFile(str(source)))

REVIEW_TEXT="  自定义阶段审核：核对台词和表演说明，返回JSON。\n "
class ReviewRulesSource(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="ReviewRulesSource",inputs=[],outputs=[io.String.Output()])
    @classmethod
    def execute(cls):
        events.append({"event":"review_rules_source_evaluated"})
        return io.NodeOutput(REVIEW_TEXT)

reverse_started=threading.Event()
reverse_done=threading.Event()
saved=threading.Event()
saved_count=0
original_save=SaveVideo.execute.__func__
class CheckedSaveVideo(SaveVideo):
    @classmethod
    def execute(cls,*args,**kwargs):
        global saved_count
        result=original_save(cls,*args,**kwargs)
        files=list((DATA/"output").glob("chosen-by-node/*.mp4"))
        assert files, "stock SaveVideo must write the files"
        assert reverse_started.is_set(), "reverse node must already be running"
        assert not reverse_done.is_set(), "SaveVideo must finish before reverse finishes"
        events.append({"event":"save_video_written","time":time.monotonic(),"files":len(files)})
        saved_count+=1
        if saved_count==2:saved.set()
        return result

original_reverse=pkg.NODE_CLASS_MAPPINGS["DSH_VideoReverse"]
class CheckedReverse(original_reverse):
    @classmethod
    async def execute(cls,context):
        reverse_started.set()
        events.append({"event":"reverse_started","time":time.monotonic()})
        try:
            result=await super().execute(context)
        except RuntimeError:
            assert saved.is_set(), "reverse failure must not remove SaveVideo files"
            reverse_done.set()
            events.append({"event":"reverse_failed_after_save","time":time.monotonic()})
            raise
        assert saved.is_set(), "all SaveVideo outputs must exist before reverse ends"
        reverse_done.set()
        events.append({"event":"reverse_finished","time":time.monotonic()})
        return result

def on_coordinator():
    assert saved.wait(15), "Comfy scheduler did not save while reverse was pending"

gateway=BParallelGateway(segments=[{"start":0,"end":16},{"start":16,"end":32}],
    fail_segment=2 if args.reverse_fails else None,on_coordinator=on_coordinator)
nodes.NODE_CLASS_MAPPINGS.update(pkg.NODE_CLASS_MAPPINGS)
nodes.NODE_CLASS_MAPPINGS.update(SchedulerSource=Source,SaveVideo=CheckedSaveVideo,DSH_VideoReverse=CheckedReverse,ReviewRulesSource=ReviewRulesSource)
# Match server discovery order: the original node is inspected before its subclass.
full=pkg.NODE_CLASS_MAPPINGS["DSH_FullVideoAgent"]
full.GET_SCHEMA()
preloaded_stage=pkg.NODE_CLASS_MAPPINGS["DSH_VideoSegments"]
preloaded_stage.GET_SCHEMA()
graph={
    "source":{"class_type":"SchedulerSource","inputs":{}},
    "segment":{"class_type":"DSH_VideoSegments","inputs":{
        "video":["source",0],"api_key":"local-only","base_url":gateway.url,"model":"gpt-6.1-sol",
        "requirement":"test","rules_text":"A must not run","api_protocol":"openai-completions",
        "segment_rules_text":"调用工具切成两段","chain_b_reverse_rules_text":"逐段反推",
        "chain_b_review_rules_text":REVIEW_TEXT,
        "timeout_s":90,"max_tokens":2048}},
    "reverse":{"class_type":"DSH_VideoReverse","inputs":{"context":["segment",8]}},
    "save1":{"class_type":"SaveVideo","inputs":{"video":["segment",3],
        "filename_prefix":"chosen-by-node/clip","format":"mp4","format.codec":"h264"}},
    "save2":{"class_type":"SaveVideo","inputs":{"video":["segment",4],
        "filename_prefix":"chosen-by-node/clip","format":"mp4","format.codec":"h264"}},
}
if args.review_linked:
    graph["review_rules"]={"class_type":"ReviewRulesSource","inputs":{}}
    graph["segment"]["inputs"]["chain_b_review_rules_text"]=["review_rules",0]
async def run():
    validation=await validate_prompt("scheduler-validation-test",graph,None)
    assert validation[0], validation
    assert set(validation[2])=={"reverse","save1","save2"}, validation
    assert preloaded_stage.RETURN_TYPES==["STRING"]*3+["VIDEO"]*5+["DSH_VIDEO_CONTEXT"]
    assert len(full.RETURN_TYPES)==8, "subclass must not modify original output schema"
    print("REAL_COMFY_PROMPT_VALIDATION_WITH_PARENT_SCHEMA_PRELOADED_OK")
    executor=PromptExecutor(server.PromptServer.instance,cache_type=CacheType.CLASSIC,
        cache_args={"ram":0,"ram_inactive":0})
    await executor.execute_async(graph,"scheduler-concurrency-test",execute_outputs=["reverse","save1","save2"])
    assert executor.success == (not args.reverse_fails),executor.status_messages
    assert saved.is_set() and reverse_done.is_set()
    assert len(gateway.requests)==(7 if args.reverse_fails else 8)
    assert len(gateway.review_requests)==(0 if args.reverse_fails else 1)
    assert gateway.peak_children==2 and not gateway.errors, gateway.errors
    assert not list((DATA/"output").glob("video/DSH/**/*")), "plugin must not choose/save any output path"
    assert len(list((DATA/"output").glob("chosen-by-node/*.mp4")))==2
    if not args.reverse_fails:
        system=next(m["content"] for m in gateway.review_requests[0]["messages"] if m["role"]=="system")
        assert system==REVIEW_TEXT
        assert any(e["event"]=="review_rules_source_evaluated" for e in events)==args.review_linked
        print("STAGED_B_CUSTOM_REVIEW_RULES_SENT_EXACTLY_OK")
    print("REAL_COMFY_SCHEDULER_STOCK_SAVEVIDEO_OVERLAPS_REVERSE_OK",json.dumps(events))
    # A releases its original video before the single deferred inference call.
    if not args.reverse_fails:
        a_gateway=PreparedGateway(final_texts=["A只反推一次"])
        try:
            from fractions import Fraction
            import torch
            from comfy_api.latest import Types
            a_video=InputImpl.VideoFromComponents(Types.VideoComponents(
                images=torch.zeros((24,32,48,3)),frame_rate=Fraction(12)))
            stage=pkg.NODE_CLASS_MAPPINGS["DSH_VideoSegments"]
            stage.hidden=types.SimpleNamespace(unique_id="scheduler-A-pass-through")
            a_result=await stage.execute(video=a_video,api_key="local-only",base_url=a_gateway.url,
                model="gpt-6.1-sol",api_protocol="openai-completions",requirement="A用户要求",
                rules_text="A规则",segment_rules_text=object(),chain_b_reverse_rules_text=object(),timeout_s=60)
            assert a_result.result[3] is a_video
            assert not a_gateway.requests
            passed=await original_reverse.execute(a_result.result[8])
            assert a_result.result[0]=="" and passed.result[0]=="A只反推一次"
            assert (await original_reverse.execute(a_result.result[8])).result[0]=="A只反推一次"
            assert len(a_gateway.requests)==1
            print("STAGED_A_RULES_ISOLATED_NO_REPEATED_AI_OK")
        finally:
            a_gateway.close()
try:
    asyncio.run(run())
finally:
    gateway.close()
    pkg.BRIDGE.close()
