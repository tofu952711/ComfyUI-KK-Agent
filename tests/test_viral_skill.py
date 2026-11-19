"""Check installed skill provenance, routing, and an actual Harness skill read."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_standalone import ModelServer
from dsh_bridge import presets
from dsh_bridge.sdk_backend import prepare_home
from dsh_bridge.workflow import workflow_bridge

HEADINGS = ("【参考素材】", "【故事与场景】", "【动作与摄影机】", "【对白与声音】", "【背景音乐】")


def test_viral_skill_installed_verbatim_and_uses_chinese_contract(tmp_path):
    root = Path(__file__).resolve().parents[1]
    skill = root / "vendor/skills/viral-variation/SKILL.md"
    # User requested only removing this clause from the original Skill.
    content = skill.read_bytes()
    assert "不编造材质或功效".encode() not in content
    anchor = "遮挡及前后镜头状态。此类必要动作修改".encode()
    original = content.replace(anchor, "遮挡及前后镜头状态；不编造材质或功效。此类必要动作修改".encode())
    assert hashlib.sha256(original).hexdigest() == "5958a599c5e2327b3e7743c962290e33cffe634049f8150093682f7999f01947"
    assert presets.task_id("爆款裂变") == "viral-variation"
    prompt = presets.task_brief("viral-variation", requirement="换成参考图里的商品")
    assert "先调用 skill 工具加载 viral-variation" in prompt
    assert "完整简体中文" in prompt
    assert "正文一律英文" not in prompt and "h3-prompt-writing" not in prompt
    home = prepare_home({"dsh_home": str(tmp_path / "harness"), "workspace": str(tmp_path / "workspace")})
    assert (home / "skills/viral-variation/SKILL.md").read_bytes() == skill.read_bytes()


def test_actual_harness_reads_new_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_BRIDGE_DATA_DIR", str(tmp_path / "shared"))
    answer = "请根据以下1个参考素材生成视频。\n" + "\n".join(HEADINGS)
    gateway = ModelServer(skill_name="viral-variation", answer=answer)
    try:
        with workflow_bridge("local-skill-test-key", gateway.url, "deepseek-flash", 30, "deepseek-messages") as bridge:
            result = bridge.ask(bridge.session_id("viral-test"), presets.task_brief("viral-variation"))
            assert result["text"] == answer
            assert len(gateway.requests) == 2
            results = [block for message in gateway.requests[-1]["messages"]
                       if isinstance(message.get("content"), list) for block in message["content"]
                       if isinstance(block, dict) and block.get("type") == "tool_result"]
            assert results and not any(block.get("is_error") for block in results)
            content = json.dumps(results, ensure_ascii=False)
            assert "爆款裂变" in content and "固定交付结构" in content
            # Check the assembled model request, not just the profile source:
            # SDK file-mention guidance must not reinterpret media labels.
            for request in gateway.requests:
                system = json.dumps(request.get("system") or [m for m in request["messages"] if m["role"] == "system"], ensure_ascii=False)
                assert "Tokens prefixed with @ are paths" not in system
                assert "是素材引用标签，不是文件路径" in system
                assert "真实文件路径" in system
            assert any(tool["name"] == "read" for tool in gateway.requests[0]["tools"])
    finally:
        gateway.close()
