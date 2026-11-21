"""Check real ComfyUI schemas + VIDEO nodes against a local mock model API.
Run with the ComfyUI Python: python tests/check_comfy.py --comfy-root <ComfyUI>
Requires pytest for the shared deterministic model fixture. No paid API calls.
"""
import argparse,asyncio,importlib.util,json,os,sys,tempfile,types,threading,time
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument("--comfy-root",required=True,type=Path)
parser.add_argument("--protocol",choices=["openai-completions","deepseek-messages"],default="openai-completions")
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
workspace=tempfile.TemporaryDirectory(prefix="dsh-comfy-smoke-")
DATA=Path(workspace.name)
sys.path.insert(0,str(args.comfy_root.resolve()))
sys.path.insert(0,str(ROOT/"tests"))
os.environ["DSH_BRIDGE_DATA_DIR"]=str(DATA)
from aiohttp import web
routes=web.RouteTableDef()
server=types.ModuleType("server")
preview_events = []
clips_ready = threading.Event()
def send_preview(event, data, sid=None):
    assert event == "dsh_video_segments"
    preview_events.append((time.monotonic(), data))
    if data["kind"] == "clip" and data["index"] == 2:
        clips_ready.set()
server.PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes, send_sync=send_preview))
sys.modules["server"]=server
spec=importlib.util.spec_from_file_location("dsh_comfy_smoke", ROOT/"__init__.py",submodule_search_locations=[str(ROOT)])
pkg=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=pkg
spec.loader.exec_module(pkg)
from comfy_api.latest import io,InputImpl,Types
import torch
import folder_paths
folder_paths.set_temp_directory(str(DATA / "previews"))
folder_paths.set_output_directory(str(DATA / "output"))
for name,cls in pkg.NODE_CLASS_MAPPINGS.items():
    schema=cls.define_schema()
    assert schema.node_id==name
    cls.INPUT_TYPES()
    print("REAL_COMFY_SCHEMA_OK",name)
full_inputs = pkg.NODE_CLASS_MAPPINGS["DSH_FullVideoAgent"].INPUT_TYPES()
assert "rules_text" in full_inputs["optional"]
assert not full_inputs["optional"]["rules_text"][1].get("forceInput", False)
assert full_inputs["optional"]["rules_text"][1]["multiline"]
assert full_inputs["optional"]["rules_text"][1]["default"] == ""
assert full_inputs["optional"]["rules_text"][1]["lazy"]
assert full_inputs["required"]["requirement"][1]["multiline"]
widget_names = [name for group in ("required", "optional") for name, spec in full_inputs[group].items()
                if name != "video" and not name.startswith("image")]
assert widget_names == ["api_key", "base_url", "model", "requirement", "timeout_s", "max_tokens",
                        "asr_model_dir", "api_protocol", "rules_text", "keep_audio", "segment_rules_text", "chain_b_reverse_rules_text", "reasoning_effort", "stream_usage", "chain_b_review_rules_text"], widget_names
assert full_inputs['optional']['stream_usage'][1]['default'] is True
assert full_inputs["optional"]["reasoning_effort"][1]["default"] == "high"
assert set(full_inputs["optional"]["reasoning_effort"][1]["options"]) == {"high", "medium", "low", "auto"}
assert full_inputs["optional"]["segment_rules_text"][1]["multiline"]
assert full_inputs["optional"]["segment_rules_text"][1]["default"] == ""
assert full_inputs["optional"]["segment_rules_text"][1]["lazy"]
assert full_inputs["optional"]["chain_b_reverse_rules_text"][1]["multiline"]
assert full_inputs["optional"]["chain_b_reverse_rules_text"][1]["default"] == ""
assert full_inputs["optional"]["chain_b_reverse_rules_text"][1]["lazy"]
review_spec = full_inputs["optional"]["chain_b_review_rules_text"][1]
assert review_spec["multiline"] and review_spec["lazy"] and "最终复核" in review_spec["default"]
assert full_inputs["optional"]["keep_audio"][1]["default"] is True
assert all(f"image{i}" in full_inputs["optional"] for i in range(1, 11))
assert "person" not in full_inputs["required"] and "product" not in full_inputs["required"]
schema = pkg.NODE_CLASS_MAPPINGS["DSH_FullVideoAgent"].define_schema()
assert [output.io_type for output in schema.outputs] == ["STRING"] * 3 + ["VIDEO"] * 5
# A real ComfyUI VIDEO object with a short synthetic color sequence.
images=torch.zeros((24,64,96,3),dtype=torch.float32)
images[:12,:,:,2]=1
images[12:,:,:,0]=1
from fractions import Fraction
video=InputImpl.VideoFromComponents(Types.VideoComponents(images=images,frame_rate=Fraction(12)))
sheet_tensor=images[:1]
bridge=importlib.import_module("dsh_comfy_smoke.dsh_bridge").BRIDGE
assert set(pkg.NODE_CLASS_MAPPINGS) == {"DSH_FullVideoAgent","DSH_VideoSegments","DSH_VideoReverse"}
assert set(pkg.NODE_DISPLAY_NAME_MAPPINGS) == set(pkg.NODE_CLASS_MAPPINGS)
for retired in ("dsh_nodes.py", "dsh_sheet.py", "dsh_workflow.py"):
    assert not (ROOT / "nodes" / retired).exists()
cloud = types.ModuleType("dsh_comfy_smoke.cloud_check")
cloud.__package__ = pkg.__name__
exec(compile((ROOT / "scripts/cloud_init.py.tpl").read_text(encoding="utf-8"),
             "cloud_init.py.tpl", "exec"), cloud.__dict__)
assert set(cloud.NODE_CLASS_MAPPINGS) == set(pkg.NODE_CLASS_MAPPINGS)
print("REAL_COMFY_LOCAL_AND_CLOUD_STAGE_NODES_OK")
async def run():
    full = pkg.NODE_CLASS_MAPPINGS["DSH_FullVideoAgent"]
    full.hidden = types.SimpleNamespace(unique_id="duration-policy-test")
    assert full.check_lazy_status(video=video,segment_rules_text=None)==["rules_text"]
    assert full.check_lazy_status(video=video,rules_text="A",segment_rules_text=None)==[]
    assert full.check_lazy_status(video=types.SimpleNamespace(get_duration=lambda:31.9),segment_rules_text=None)==["rules_text"]
    assert full.check_lazy_status(video=types.SimpleNamespace(get_duration=lambda:31.900001),segment_rules_text=None)==["rules_text"]
    try:
        await full.execute(video=video, api_key="", base_url="", model="",
                           requirement="本次用户要求", rules_text=" ")
    except ValueError as exc:
        assert "反推规则" in str(exc)
    else:
        raise AssertionError("Missing external rules must fail before media or API work")
    from test_video_preparation import PreparedGateway
    from comfy_execution.graph_utils import ExecutionBlocker
    # Short route must never send/read the third field, even when old rules ask for three cuts.
    for count in (0,2,10):
        gateway = PreparedGateway(detail=True)
        homes=[]
        node_module=sys.modules[full.__module__]
        try:
            slots = [2,10] if count == 2 else list(range(1,count+1))
            kwargs={f"image{i}":sheet_tensor for i in slots}
            # Metadata just below 32 must stay in A without rounding/re-routing.
            routed_video = video if count == 0 else types.SimpleNamespace(
                get_duration=lambda:31.999999, get_stream_source=video.get_stream_source,
                save_to=video.save_to)
            result=await full.execute(video=routed_video,api_key="local-only",base_url=gateway.url,
                model="gpt-6.1-sol", requirement="本次用户标记",rules_text="反推规则标记：把视频分3段保存，然后分析。",
                segment_rules_text="第三框机密标记-短片不能读取或发送",
                chain_b_reverse_rules_text="B反推机密标记-不能进入A",api_protocol="openai-completions",timeout_s=60,
                _observer=lambda stage,bridge,output: homes.append(Path(bridge.cfg["dsh_home"])) if stage=="ready" else None,**kwargs)
            evidence=json.loads(result.result[1])
            assert evidence["duration_policy.json"]["split_required"] is False
            assert evidence["duration_policy.json"]["chain"] == "A"
            assert evidence["chain"] == "A"
            audit_records=[json.loads(line) for line in Path(evidence["request_audit_file"]).read_text(encoding="utf-8").splitlines()]
            prepared=audit_records[0]
            assert prepared["stage"]=="prepared"
            assert prepared["reference_images"]==count and prepared["video_sheet_images"]>0
            outgoing=[r for r in audit_records if r["stage"]=="outgoing_request"]
            assert len(outgoing)==len(gateway.requests)
            assert all(r["system_exact"] and r["user_exact"] and r["media_evidence_exact"] for r in outgoing)
            assert all(r["media_evidence_sha256"]==prepared["media_evidence_sha256"] for r in outgoing)
            assert all(r["system_sha256"]==prepared["system_sha256"] for r in outgoing)
            assert all(r["initial_image_blocks"]==prepared["total_images"] for r in outgoing)
            assert evidence["video_outputs"]["count"]==0
            assert evidence["timings"]["video_encoding_seconds"]==0
            assert evidence["video_outputs"]["storage"].startswith("none")
            assert not evidence["segment_agent_tool_calls"]
            assert len(gateway.requests)==2
            assert all(body["reasoning_effort"]=="high" for body in gateway.requests)
            assert evidence["reasoning_effort"]=={"selected":"high","requested":"high"}
            wire=json.dumps(gateway.requests,ensure_ascii=False)
            assert "第三框机密标记" not in wire
            assert "B反推机密标记" not in wire
            first=gateway.requests[0]
            assert not any(t["function"]["name"].endswith("set_video_segments") for t in first["tools"])
            system=json.dumps([m for m in first["messages"] if m["role"]=="system"],ensure_ascii=False)
            user=json.dumps([m for m in first["messages"] if m["role"]=="user"],ensure_ascii=False)
            assert [m["content"] for m in first["messages"] if m["role"]=="system"] == ["反推规则标记：把视频分3段保存，然后分析。"]
            assert [b["text"] for m in first["messages"] if m["role"]=="user" for b in m["content"] if b["type"]=="text"] == ["本次用户标记", evidence["media_input"]["text"]]
            for label, name in (("视频信息：", "preparation.json"), ("音轨自动转写：", "transcript.json"), ("候选切点：", "shot_candidates.json")):
                assert label in evidence["media_input"]["text"] and name in evidence
            assert evidence["media_input"]["sent_to_ai"] is True
            assert not any(t in json.dumps(first,ensure_ascii=False) for t in ("插件时长策略", "最终交付要求", "第二框系统提示词", "request preview", "Current working directory"))
            assert not any(data["kind"] in ("start", "reverse_start", "complete") for _,data in preview_events)
            assert "反推规则标记" in system and "反推规则标记" not in user
            assert "本次用户标记" in user and "本次用户标记" not in system
            assert "<skill_content" not in wire and "/viral-variation" not in wire
            assert evidence["reference_image_slots"]==slots
            assert all(isinstance(v,ExecutionBlocker) for v in result.result[3:])
            assert not any(data["kind"]=="clip" for _,data in preview_events)
            assert homes and not homes[0].exists()
            print("SHORT_VIDEO_IGNORES_THIRD_FIELD_AND_SPLIT_TOOLS_OK",count)
        finally:
            gateway.close()
    from test_output_contract import RULES,VALID
    gateway=PreparedGateway(final_texts=[VALID])
    try:
        result=await full.execute(video=video,api_key="local-only",base_url=gateway.url,
            model="gpt-6.1-sol",requirement="按外接模板交付",rules_text=RULES,
            api_protocol="openai-completions",timeout_s=60)
        evidence=json.loads(result.result[1])
        assert result.result[0]==VALID
        assert evidence["output_compliance"]["review_turns"]==0
        assert evidence["output_compliance"]["input_mode"]=="exact_two_textboxes_with_media_evidence"
        assert evidence["timings"]["output_review_seconds"]==0
        assert len(gateway.requests)==1
        assert all(body["reasoning_effort"]=="high" for body in gateway.requests)
        assert all(isinstance(v,ExecutionBlocker) for v in result.result[3:])
        print("REAL_COMFY_EXACT_INPUTS_NO_REVIEW_AND_NO_VIDEO_OK")
    finally:
        gateway.close()
    # CodeZ Responses uses the same media bundle and actual MCP detail frames.
    from responses_gateway import ResponsesGateway
    gateway=ResponsesGateway(media=True)
    try:
        result=await full.execute(video=video,api_key="local-codez",base_url=gateway.url,
            model="gpt-6.1-sol",requirement="  用户原文\n ",rules_text="  系统原文{{literal}}\n ",
            image2=sheet_tensor,image10=sheet_tensor,segment_rules_text="第三框不能发送",
            api_protocol="codez",reasoning_effort="high",timeout_s=60)
        records=json.loads(result.result[1])
        assert len(gateway.requests)==2
        assert all(p=="/v1/responses" for p in gateway.paths)
        for body in gateway.requests:
            assert body["instructions"]=="  系统原文{{literal}}\n "
            assert body["reasoning"]["effort"]=="high"
            assert "reasoning_effort" not in body and "messages" not in body
            first_user=next(m for m in body["input"] if m.get("role")=="user")
            assert [b["text"] for b in first_user["content"] if b["type"]=="input_text"]==[
                "  用户原文\n ",records["media_input"]["text"]]
            assert sum(b["type"]=="input_image" for b in first_user["content"])==records["media_input"]["video_sheet_images"]+2
            assert "第三框不能发送" not in json.dumps(body,ensure_ascii=False)
            assert not any(t["name"].endswith("set_video_segments") for t in body["tools"])
        assert any(m.get("type")=="function_call_output" for m in gateway.requests[1]["input"])
        assert any(m.get("encrypted_content")=="local-replay-proof" for m in gateway.requests[1]["input"])
        tool_outputs=[m for m in gateway.requests[1]["input"] if m.get("type")=="function_call_output"]
        assert any(b.get("type")=="input_image" for m in tool_outputs if isinstance(m.get("output"),list) for b in m["output"])
        assert records["agent_tool_calls"]==[next(t["name"] for t in gateway.requests[0]["tools"] if t["name"].endswith("get_frames"))]
        audit=[json.loads(line) for line in Path(records["request_audit_file"]).read_text(encoding="utf-8").splitlines()]
        outgoing=[r for r in audit if r["stage"]=="outgoing_request"]
        assert len(outgoing)==2
        assert all(r["api_format"]=="responses" and r["reasoning_effort"]=="high" for r in outgoing)
        assert all(r["system_exact"] and r["user_exact"] and r["media_evidence_exact"] for r in outgoing)
        assert all(isinstance(v,ExecutionBlocker) for v in result.result[3:])
        print("REAL_COMFY_CODEZ_RESPONSES_EXACT_MEDIA_TOOL_ROUND_OK")
    finally:
        gateway.close()
    # B: real AI tool calls must create clips before concurrent reverse starts.
    from b_parallel_gateway import BParallelGateway
    class UnreadableInput:
        def __str__(self):
            raise AssertionError("B must not inspect A rules")
        def __getattr__(self, name):
            raise AssertionError(f"B must not inspect A rules: {name}")
    b_frames=images.repeat(16,1,1,1)
    b_frames[:]=0
    b_frames[(torch.arange(384)//4)%2==0,:,:,0]=1
    b_frames[(torch.arange(384)//4)%2==1,:,:,2]=1
    b_video=InputImpl.VideoFromComponents(Types.VideoComponents(
        images=b_frames,frame_rate=Fraction(12)))
    assert b_video.get_duration()==32
    assert full.check_lazy_status(video=b_video)==["segment_rules_text","chain_b_reverse_rules_text"]
    assert full.check_lazy_status(video=b_video,segment_rules_text="B")==["chain_b_reverse_rules_text"]
    assert full.check_lazy_status(video=b_video,segment_rules_text="B",chain_b_reverse_rules_text="reverse")==[]
    for missing_segment,missing_reverse in [("","B"),("B","")]:
        try:
            await full.execute(video=b_video,api_key="",base_url="",model="",requirement="user",
                rules_text=UnreadableInput(),segment_rules_text=missing_segment,
                chain_b_reverse_rules_text=missing_reverse)
        except ValueError as exc:
            assert "链路B" in str(exc)
        else:
            raise AssertionError("B must require its own two rules before preparation")
    assert full.check_lazy_status(video=b_video,segment_rules_text="B",chain_b_reverse_rules_text="reverse",chain_b_review_rules_text=None)==["chain_b_review_rules_text"]
    assert full.check_lazy_status(video=video,rules_text="A",chain_b_review_rules_text=None)==[]
    try:
        await full.execute(video=b_video,api_key="",base_url="",model="",requirement="user",
            segment_rules_text="B",chain_b_reverse_rules_text="reverse",chain_b_review_rules_text="  ")
    except ValueError as exc:
        assert "审核规定" in str(exc)
    else:
        raise AssertionError("Blank custom review must fail before API calls")
    review_rules="  自定义审核{{literal}}：只检查台词与表演说明一致性。按JSON契约返回。\n "
    user="  B用户原文\n "
    segment_rules="  B分段规定{{literal}}：根据证据调用工具分段。\n "
    reverse_rules="  B反推规定{{literal}}：逐段输出提示词。\n "
    for protocol,ranges,keep_audio in [
            ("openai-completions",[{"start":0,"end":10},{"start":10,"end":21},{"start":21,"end":32}],False),
            ("codez",[{"start":0,"end":15},{"start":15,"end":32}],True)]:
        gateway=BParallelGateway(ranges, protocol)
        homes=[]
        outputs=[]
        preparations=[]
        from dsh_comfy_smoke.dsh_bridge import b_video_preparation as b_preparation
        original_prepare=b_preparation.prepare_b_chain_media
        def track_preparation(*args):
            preparations.append(args[2]["chain"])
            return original_prepare(*args)
        def stage_observer(stage,current_bridge,output):
            homes.append(Path(current_bridge.cfg["dsh_home"]))
            outputs.append(output)
            if stage=="segmented":
                plan=json.loads((output/"video_segments.json").read_text(encoding="utf-8"))
                assert plan["materialized"] and plan["status"]=="ready"
                assert all((output/name).is_file() for name in plan["files"])
                assert len(gateway.requests)==2 # Tool and its completion; reverse has not run.
        try:
            b_preparation.prepare_b_chain_media=track_preparation
            result=await full.execute(video=b_video,api_key="local-only",base_url=gateway.url,
                model="gpt-6.1-sol",requirement=user,rules_text=UnreadableInput(),
                segment_rules_text=segment_rules,chain_b_reverse_rules_text=reverse_rules,
                api_protocol=protocol,reasoning_effort="medium",keep_audio=keep_audio,chain_b_review_rules_text=review_rules,
                image2=sheet_tensor,image10=sheet_tensor,timeout_s=90,_observer=stage_observer)
            records=json.loads(result.result[1])
            assert records["chain"]=="B" and records["chain_status"]=="completed"
            assert result.result[0].strip() and "已分段" in result.result[2]
            assert records["ai_called"] and preparations==["B"]
            assert records["video_outputs"]["segments"]==ranges
            assert records["video_outputs"]["executor"]=="ai_invoked_media_tool"
            assert records["video_outputs"]["keep_audio"]==keep_audio
            assert records["reference_image_slots"]==[2,10]
            assert records["media_input"]["sent_to_ai"]
            assert records["media_input"]["video_sheet_images"]+2>20
            assert len(gateway.requests)==4+2*len(ranges)
            assert len(gateway.review_requests)==1
            review_body=gateway.review_requests[0]
            actual_review=review_body["instructions"] if protocol=="codez" else next(m["content"] for m in review_body["messages"] if m["role"]=="system")
            assert actual_review==review_rules
            assert records["rules"]["review"]["sha256"]==__import__("hashlib").sha256(review_rules.encode()).hexdigest()
            assert records["parallel_reverse"]["review"]["status"]=="approved"
            assert gateway.peak_children==len(ranges) and not gateway.errors, gateway.errors
            assert records["parallel_reverse"]["agent_count"]==len(ranges)
            for phase,bodies in [("segment",gateway.segment_requests),
                                 ("reverse",[body for _,body in gateway.worker_requests])]:
                expected=segment_rules if phase=="segment" else reverse_rules
                for body in bodies:
                    if protocol=="codez":
                        assert body["instructions"]==expected
                        assert body["reasoning"]["effort"]=="medium"
                        texts=[b["text"] for m in body["input"] if m.get("role")=="user" for b in m["content"] if b["type"]=="input_text"]
                        names=[t["name"] for t in body["tools"]]
                    else:
                        assert [m["content"] for m in body["messages"] if m["role"]=="system"]==[expected]
                        assert body["reasoning_effort"]=="medium"
                        texts=[b["text"] for m in body["messages"] if m["role"]=="user" for b in m["content"] if b["type"]=="text"]
                        names=[t["function"]["name"] for t in body["tools"]]
                    assert texts[0].startswith(user)
                    assert any(n.endswith("set_video_segments") for n in names)==(phase=="segment")
                    assert (reverse_rules if phase=="segment" else segment_rules) not in json.dumps(body,ensure_ascii=False)
            assert len(records["segment_agent_tool_calls"])==1
            for index,segment in enumerate(ranges):
                clip=result.result[3+index]
                assert abs(clip.get_duration()-(segment["end"]-segment["start"]))<.1
                target=DATA/f"saved-{protocol}-{index}.mp4"
                clip.save_to(str(target))
                assert target.stat().st_size>0
            assert all(isinstance(v,ExecutionBlocker) for v in result.result[3+len(ranges):])
            assert all(not h.exists() for h in homes) and all(not o.exists() for o in outputs)
            for phase,file in records["request_audit_files"].items():
                audit=[json.loads(line) for line in Path(file).read_text(encoding="utf-8").splitlines()]
                outgoing=[r for r in audit if r["stage"]=="outgoing_request"]
                assert len(outgoing)==(1 if phase in ("coordinator","review") else 2)
                assert all(r["system_exact"] and r["user_exact"] and r["media_evidence_exact"] for r in outgoing)
            print("REAL_COMFY_B_AI_CUTS_THEN_CONCURRENT_SEGMENT_AGENTS_OK",protocol,len(ranges))
        finally:
            b_preparation.prepare_b_chain_media=original_prepare
            gateway.close()
    # A textual claim of segmentation cannot count as a successful cut.
    for ranges,final_texts,error in [
            (None,["我已经分段了"],"未成功调用"),
            ([{"start":0,"end":10},{"start":11,"end":32}],["plan"],"未成功调用"),
            ([{"start":0,"end":15},{"start":15,"end":32}],["分段完成", ""],"失败段号")]:
        gateway=(BParallelGateway(ranges,fail_segment=2) if error=="失败段号" else
                 PreparedGateway(segments=ranges,final_texts=final_texts))
        try:
            await full.execute(video=b_video,api_key="local-only",base_url=gateway.url,
                model="gpt-6.1-sol",requirement=user,rules_text=UnreadableInput(),
                segment_rules_text=segment_rules,chain_b_reverse_rules_text=reverse_rules,
                api_protocol="openai-completions",timeout_s=90)
        except RuntimeError as exc:
            assert error in str(exc), str(exc)
            if error=="未成功调用":assert len(gateway.requests)<=2
            print("REAL_COMFY_B_FAILURE_IS_NOT_EMPTY_SUCCESS_OK",error)
        else:
            raise AssertionError("B failure must not silently return empty success")
        finally:
            gateway.close()
    for seconds in (0,60.001,float("nan")):
        try:
            await full.execute(video=types.SimpleNamespace(get_duration=lambda:seconds),
                api_key="",base_url="",model="",requirement="",rules_text=UnreadableInput())
        except ValueError:
            pass
        else:
            raise AssertionError("Unsupported duration must fail before chain dispatch")

try:
    asyncio.run(run())
finally:
    bridge.close()
print("COMFY_SMOKE_ALL_OK")
