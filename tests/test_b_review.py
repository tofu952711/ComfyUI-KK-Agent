"""Guard final-review patches against accidental timeline or document damage."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.b_review import CHECKS, parse_review, apply_review, dialogue_timing_hints


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
    ("0—2秒", "0—3秒", "时间轴"),
    ("@图片1", "@图片2", "素材编号"),
    ("【动作与摄影机】", "【其他章节】", "章节"),
    ("不存在原文", "新文", "唯一匹配"),
    ("重复", "新文", "唯一匹配")])
def test_patch_must_match_exactly_and_preserve_protected_fields(old, new, error):
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


def test_dialogue_duration_is_a_hint_not_automatic_truncation():
    text = '【对白与声音】\n- **约2.4—6.5秒｜同一女性画外音：**“它现在这个价格，真的让我感觉到，我之前零零散散买的，简直是个冤大头。”\n【背景音乐】'
    hints = dialogue_timing_hints(text)
    assert hints[0]["characters"] == 30
    assert hints[0]["characters_per_second"] == 7.32
