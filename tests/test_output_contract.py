"""External rules drive the contract; no creative skill is bundled."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsh_bridge.output_contract import ask_with_contract, output_contract, contract_errors, delivery_reminder


RULES = """# 外部规则测试
## 输出契约
不主动输出 JSON、表格、报告；用户明确要求的交付形式优先。
## 固定交付结构
生成实际内容。
【外部章节甲】
[实际内容]
【外部章节乙】
[实际内容]
## 内部交付检查
核对本次所有限制，不只核对格式。不输出检查记录。
"""
VALID = "生成实际内容。\n【外部章节甲】\n甲的正文\n【外部章节乙】\n乙的正文"


@pytest.mark.parametrize("text", ["随意回复", "【外部章节乙】\n乙\n【外部章节甲】\n甲",
    "【外部章节甲】\n【外部章节乙】\n乙", VALID + "\n| A | B |\n| --- | --- |\n| 1 | 2 |"])
def test_reject_missing_reordered_empty_sections_and_forbidden_table(text):
    assert contract_errors(text, output_contract(RULES))


def test_template_from_rules_and_user_format_override():
    contract = output_contract(RULES)
    assert contract["headings"] == ["【外部章节甲】", "【外部章节乙】"]
    assert not contract_errors(VALID, contract)
    assert not contract_errors(VALID + "\n" + VALID, contract)
    assert contract_errors(VALID + "\n【外部章节甲】\n未完成第二段", contract)
    overridden = output_contract(RULES, "这次请用表格输出")
    assert overridden["user_format_override"] and not overridden["headings"]
    assert not overridden["forbid_table"]
    assert not contract_errors("| A | B |\n| --- | --- |\n| 1 | 2 |", overridden)
    assert "【外部章节甲】" in delivery_reminder(RULES)
    assert "固定交付结构" not in output_contract("简单自由回答")["template"]


class DraftBridge:
    def __init__(self, drafts):
        self.drafts = iter(drafts)
        self.calls = []

    def ask(self, session, prompt, images=None, **kwargs):
        self.calls.append((session, prompt, images, kwargs))
        return {"text": next(self.drafts), "events": [{"type": "assistant/message", "data": {"usage": {"outputTokens": 20}}}]}


@pytest.mark.parametrize("draft", ["不符合规则的表格草稿", VALID])
def test_same_session_reviews_content_even_if_initial_format_is_valid(draft):
    bridge = DraftBridge([draft, VALID])
    answer, report = ask_with_contract(bridge, "same-session", "原始素材", ["image"], RULES, "本次要求", 30)
    assert answer["text"] == VALID and len(answer["events"]) == 2
    assert report["review_turns"] == 1 and report["format_check"] == "passed"
    assert report["rules_characters"] == len(RULES)
    assert len(report["rules_sha256"]) == 64
    assert [call[0] for call in bridge.calls] == ["same-session"] * 2
    assert bridge.calls[0][2] == ["image"] and bridge.calls[1][2] is None
    assert "所有内容限制" in bridge.calls[1][1] and "不得只补章节标题" in bridge.calls[1][1]
    assert bridge.calls[1][3]["timeout"] <= 30


def test_failed_review_is_error_not_success_and_no_unbounded_retries():
    bridge = DraftBridge(["草稿", "还是没有规定章节"])
    with pytest.raises(RuntimeError, match="交付检查未通过"):
        ask_with_contract(bridge, "session", "素材", [], RULES, "", 30)
    assert len(bridge.calls) == 2


def test_freeform_external_rules_do_not_force_viral_template_or_extra_call():
    bridge = DraftBridge(["任意合法形式的回答"])
    answer, report = ask_with_contract(bridge, "session", "素材", [], "用一句话输出", "", 30)
    assert answer["text"] == "任意合法形式的回答"
    assert report["review_turns"] == 0 and not report["required_headings"]


def test_actual_harness_review_retains_rules_images_and_previous_draft():
    from test_video_preparation import PreparedGateway
    from dsh_bridge.workflow import workflow_bridge
    import json
    gateway = PreparedGateway(final_texts=["错误的分析报告", VALID])
    try:
        with workflow_bridge("local-fake-key", gateway.url, "gpt-6.1-sol", 60) as bridge:
            bridge.cfg.update(video_prompt_only=True, video_system_prompt=RULES)
            answer, report = ask_with_contract(bridge, bridge.session_id("review-test"),
                "本地素材标记", [], RULES, "按规则执行", 60)
        assert answer["text"] == VALID and report["review_turns"] == 1
        assert len(gateway.requests) == 2
        messages = gateway.requests[-1]["messages"]
        assert any(RULES in m["content"] for m in messages if m["role"] == "system")
        assert "错误的分析报告" in json.dumps([m for m in messages if m["role"] == "assistant"], ensure_ascii=False)
        assert "本地素材标记" in json.dumps(messages, ensure_ascii=False)
        assert "所有内容限制" in json.dumps(messages, ensure_ascii=False)
    finally:
        gateway.close()
