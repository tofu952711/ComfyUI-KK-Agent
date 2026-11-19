"""Duration gates, default cuts and immutable output limits."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.duration_routing import route_duration, ask_segment_plan
from dsh_bridge.media_tools import MediaTools, definitions

@pytest.mark.parametrize("seconds,chain", [(.1,"A"),(30.9,"A"),(31,"A"),(31.9,"A"),
    (31.900001,"A"),(31.95,"A"),(31.999999,"A"),(32,"B"),(32.000001,"B"),(59.99,"B"),(60,"B")])
def test_exact_duration_gates(seconds, chain):
    state = route_duration(seconds)
    assert state["chain"] == chain
    assert state["duration_seconds"] == seconds
    assert state["split_required"] == (chain == "B")
    assert state["count"] == (None if chain == "B" else 0)

@pytest.mark.parametrize("seconds", [0,-1,60.001,61,float("nan"),float("inf")])
def test_unsupported_duration_fails_before_model(seconds):
    with pytest.raises(ValueError):
        route_duration(seconds)

def test_ai_plan_and_locked_tools(tmp_path):
    info = {"duration_seconds":32,"fps":30}
    ranges = [{"start":0,"end":12.3},{"start":12.3,"end":32}]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"metadata injected, no decoding")
    tools = MediaTools(source,tmp_path/"media")
    tools._cache["info"] = info
    tools._write_json("duration_policy.json", {"phase":"segment"})
    tools.set_video_segments(ranges)
    for bad in ([{"start":0,"end":32}],
                [{"start":0,"end":10},{"start":10,"end":20},{"start":20,"end":32}]):
        with pytest.raises(ValueError, match="两段"):
            tools.set_video_segments(bad)
    tools._write_json("duration_policy.json", {"phase":"reverse"})
    with pytest.raises(ValueError, match="禁止修改"):
        tools.set_video_segments(ranges)
    assert json.loads((tools.output/"video_segments.json").read_text(encoding="utf-8"))["segments"] == ranges
    assert "set_video_segments" not in {tool["name"] for tool in definitions(allow_segments=False)}
    schema = next(tool for tool in definitions() if tool["name"] == "set_video_segments")["inputSchema"]
    assert schema["properties"]["segments"]["maxItems"] == 5


def test_planning_omission_corrected_once_and_stops_if_still_missing(tmp_path):
    info={"duration_seconds":32,"fps":30}
    calls=[]
    def ask(session,prompt,images=None,**kwargs):
        calls.append((session,prompt,images))
        if len(calls)==2:
            (tmp_path/"video_segments.json").write_text(json.dumps({"segments":[
                {"start":0,"end":12.3},{"start":12.3,"end":32}]}),encoding="utf-8")
        return {"events":[],"text":"plan done"}
    bridge=SimpleNamespace(session_id=lambda label:label,ask=ask)
    ranges,answer,corrections=ask_segment_plan(bridge,"third field",["source-sheet"],tmp_path,info,10,None)
    assert len(ranges)==2 and corrections==1
    assert calls[0][0]==calls[1][0] and calls[1][2] is None
    (tmp_path/"video_segments.json").unlink()
    bridge.ask=lambda *a,**k:{"events":[],"text":"still forgot"}
    with pytest.raises(RuntimeError,match="未开始反推任务"):
        ask_segment_plan(bridge,"third field",[],tmp_path,info,10,None)
