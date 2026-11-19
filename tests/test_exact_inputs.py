"""Assert the actual provider payload, including literal prompts and tool rounds."""
import base64
import io
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_standalone import ModelServer
from test_video_preparation import PreparedGateway
from responses_gateway import ResponsesGateway
from dsh_bridge.workflow import workflow_bridge
from dsh_bridge.sdk_backend import instruction_role


@pytest.mark.parametrize("protocol", ["openai-completions", "deepseek-messages", "codez"])
@pytest.mark.parametrize("long_system", [False, True])
@pytest.mark.parametrize("with_media", [False, True])
def test_exact_two_textboxes_reach_real_provider_without_runtime_text(protocol, long_system, with_media, tmp_path):
    system = '  爆款裂变skill\n固定交付结构\n【自定义章节】\n保留 {{literal}} 和空白。\n  '
    if long_system:
        system += '完整规则正文。' * 3000 + '\n【固定交付结构末尾标记】'
    user = '  使用爆款裂变skill，图1人物、图2商品。\n  '
    media = '视频信息：{"duration_seconds": 12}\n音轨自动转写：素材台词\n候选切点：[]' if with_media else ''
    gateway = (ResponsesGateway(detail=False) if protocol == "codez" else
               PreparedGateway() if protocol == "openai-completions" else ModelServer(answer="完成"))
    gateway.skill_called = True
    ref = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(ref, "PNG")
    encoded = base64.b64encode(ref.getvalue()).decode()
    audit = tmp_path / "request-audit.jsonl"
    try:
        with workflow_bridge("local-fake-key", gateway.url, "gpt-6.1-sol", 30, protocol) as bridge:
            bridge.cfg.update(video_prompt_only=True, video_exact_inputs=True,
                              video_system_prompt=system, video_user_prompt=user,
                              video_media_evidence=media, _request_audit_file=str(audit))
            bridge.ask(bridge.session_id("exact-input-test"), user, [encoded])
        assert len(gateway.requests) == 1
        import hashlib
        records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
        assert len(records) == 1
        record = records[0]
        assert record["stage"] == "outgoing_request"
        assert record["system_exact"] is True and record["user_exact"] is True
        assert record["media_evidence_exact"] is True
        assert record["media_evidence_characters"] == len(media)
        assert record["media_evidence_sha256"] == hashlib.sha256(media.encode()).hexdigest()
        assert record["system_characters"] == len(system)
        assert record["system_sha256"] == hashlib.sha256(system.encode()).hexdigest()
        assert record["initial_image_blocks"] == 1
        assert 'local-fake-key' not in audit.read_text(encoding="utf-8")
        assert system not in audit.read_text(encoding="utf-8")
        body = gateway.requests[0]
        if protocol == "openai-completions":
            system_text = [m["content"] for m in body["messages"] if m["role"] == "system"]
            assert system_text == [system]
        elif protocol == "deepseek-messages":
            blocks = body["system"]
            assert (blocks if isinstance(blocks, str) else ''.join(b["text"] for b in blocks)) == system
        else:
            assert body["instructions"] == system
            assert gateway.paths == ["/v1/responses"]
        messages = body["input"] if protocol == "codez" else body["messages"]
        users = [m for m in messages if m.get("role") == "user"]
        text = [b["text"] for m in users for b in m["content"] if b["type"] in ("text", "input_text")]
        assert text == ([user, media] if media else [user])
        image_type = "input_image" if protocol == "codez" else "image_url" if protocol == "openai-completions" else "image"
        assert sum(b["type"] == image_type for m in users for b in m["content"]) == 1
        assert not any(m.get("role") == "developer" for m in messages)
        assert "工作流规则优先级" not in json.dumps(body, ensure_ascii=False)
    finally:
        gateway.close()


@pytest.mark.parametrize("protocol,host,model,exact,expected", [
    ("openai-completions", "https://api.zdjapi.com", "gpt-6.1-sol", True, "developer"),
    ("codez", "https://api.zdjapi.com/v1", "gpt-6.1-sol", True, "developer"),
    ("deepseek-messages", "https://api.zdjapi.com", "gpt-6.1-sol", True, "system"),
    ("openai-completions", "https://other.example/v1", "gpt-6.1-sol", True, "system"),
    ("openai-completions", "https://api.zdjapi.com.other.example", "gpt-6.1-sol", True, "system"),
    ("openai-completions", "https://api.zdjapi.com", "other-model", True, "system"),
    ("openai-completions", "https://api.zdjapi.com", "gpt-6.1-sol", False, "system"),
])
def test_gateway_compatibility_is_limited_to_verified_route(protocol,host,model,exact,expected):
    assert instruction_role(dict(api_protocol=protocol,base_url=host,model=model,video_exact_inputs=exact))==expected


def test_developer_role_preserves_long_rules_and_images_at_wire(tmp_path, monkeypatch):
    import dsh_bridge.sdk_backend as backend
    monkeypatch.setattr(backend, "instruction_role", lambda cfg: "developer")
    gateway=PreparedGateway()
    system="完整系统规则正文。" * 2100 + "\n【固定交付结构末尾】"
    user="图1人物、图2商品。"
    ref=io.BytesIO()
    Image.new("RGB",(32,32),"green").save(ref,"PNG")
    encoded=base64.b64encode(ref.getvalue()).decode()
    audit=tmp_path/"developer-audit.jsonl"
    try:
        with workflow_bridge("fake-key",gateway.url,"gpt-6.1-sol",30,"openai-completions") as bridge:
            bridge.cfg.update(video_prompt_only=True,video_exact_inputs=True,
                video_system_prompt=system,video_user_prompt=user,_request_audit_file=str(audit))
            bridge.ask(bridge.session_id("developer-wire-test"),user,[encoded])
        body=gateway.requests[0]
        assert body["messages"][0]=={"role":"developer","content":system}
        assert not any(m["role"]=="system" for m in body["messages"])
        assert [b["text"] for m in body["messages"] if m["role"]=="user"
            for b in m["content"] if b["type"]=="text"]==[user]
        assert sum(b["type"]=="image_url" for m in body["messages"] if m["role"]=="user" for b in m["content"])==1
        record=json.loads(audit.read_text(encoding="utf-8"))
        assert record["instruction_role"]=="developer"
        assert record["system_exact"] and record["user_exact"]
        assert record["system_characters"]==len(system)
    finally:
        gateway.close()
