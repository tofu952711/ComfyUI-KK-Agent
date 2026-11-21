"""Apply the two consistency checks without rejecting explanatory corrections."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.b_review import CHECKS, parse_review, apply_review


def decision(edits=None):
    return {"status": "corrected" if edits else "approved", "checks": {k: True for k in CHECKS},
            "issues": [], "edits": edits or []}


def test_approved_preserves_all_body_text():
    draft = [{"segment_index": 1, "text": "【动作与摄影机】\n0—2秒，@图片1保持人物。"}]
    final = apply_review(draft, parse_review(json.dumps(decision())))
    assert final[0]["text"] == draft[0]["text"]
    assert final[0]["reviewed"] and final[0]["review_edits"] == 0
    assert "reviewed" not in draft[0]


@pytest.mark.parametrize("old,new,error", [
    ("不存在原文", "新文", "唯一匹配"),
    ("重复", "新文", "唯一匹配")])
def test_patch_must_match_exactly(old, new, error):
    draft = [{"segment_index": 1, "text": "【动作与摄影机】\n0—2秒，@图片1。重复重复。"}]
    review = decision([{"segment_index": 1, "old": old, "new": new, "reason": "test"}])
    with pytest.raises(RuntimeError, match=error):
        apply_review(draft, review)


def test_multiple_disjoint_edits_apply_to_original_coordinates():
    draft = [{"segment_index": 1, "text": "开头右手，中间商品，结尾右后方。"}]
    review = decision([{"segment_index": 1, "old": "右手", "new": "左手托住", "reason": "持握一致"},
                       {"segment_index": 1, "old": "右后方", "new": "左前方", "reason": "位置一致"}])
    assert apply_review(draft, review)[0]["text"] == "开头左手托住，中间商品，结尾左前方。"
    overlap = copy.deepcopy(review)
    overlap["edits"].append({"segment_index": 1, "old": "结尾右后方", "new": "结尾", "reason": "test"})
    with pytest.raises(RuntimeError, match="重叠"):
        apply_review(draft, overlap)


@pytest.mark.parametrize("change", [
    {"checks": {}}, {"checks": {k: "true" for k in CHECKS}},
    {"status": "corrected"}, {"status": "approved", "edits": [{"anything": 1}]},
    {"status": "blocked"}])
def test_invalid_or_blocked_review_cannot_pass(change):
    review = {**decision(), **change}
    with pytest.raises(RuntimeError):
        parse_review(json.dumps(review))


def test_review_requires_only_the_two_selected_checks():
    review = decision()
    assert tuple(review["checks"]) == ("人物商品声线场景一致", "跨段位置持握开封衔接")
    assert parse_review(json.dumps(review)) == review


def test_review_can_clarify_dialogue_at_an_existing_cut_without_changing_slots():
    line = '- **约5.73—6.65秒｜主播，出镜说话：**“这是商品。”'
    revised = '- **约5.73—6.65秒｜主播，先画外解说，约5.80秒叠化转入人物后出镜说话：**“这是商品。”'
    draft = [{"segment_index": 1, "text": "【动作与摄影机】\n约3.90—5.80秒，商品特写。\n约5.80—7.00秒，叠化转入人物。\n【对白与声音】\n" + line}]
    review = decision([{"segment_index": 1, "old": line, "new": revised, "reason": "对齐既有叠化点"}])
    final = apply_review(draft, review)
    assert final[0]["text"].endswith(revised)
    assert final[0]["reviewed"] and final[0]["review_edits"] == 1
    assert draft[0]["text"].endswith(line)


def test_review_cannot_remove_the_entire_body():
    draft = [{"segment_index": 1, "text": "唯一正文"}]
    review = decision([{"segment_index": 1, "old": "唯一正文", "new": "", "reason": "test"}])
    with pytest.raises(RuntimeError, match="正文为空"):
        apply_review(draft, review)


@pytest.mark.parametrize("checks", [
    {"自定义审核项": True},
    {"台词与表演说明一致": True, "价格证据": True, "素材数量": True},
])
def test_custom_check_names_are_accepted(checks):
    value = {**decision(), "checks": checks}
    assert parse_review(json.dumps(value)) == value


@pytest.mark.parametrize("checks", [
    {"新增审核项": False}, {**dict.fromkeys(CHECKS, True), "新增审核项": False},
    {" ": True}, {"新增审核项": 1},
])
def test_custom_failed_or_invalid_check_cannot_pass(checks):
    with pytest.raises(RuntimeError):
        parse_review(json.dumps({**decision(), "checks": checks}))
