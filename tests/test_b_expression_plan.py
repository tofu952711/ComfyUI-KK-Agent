"""Malformed allocations must not silently reach concurrent workers."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from b_parallel_gateway import planned_shared
from dsh_bridge.b_expression_plan import validate_expression_plan, segment_assignment_text


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_every_segment_receives_its_own_allocation(count):
    segments = [{"start": i * 10.1234567, "end": (i + 1) * 10.1234567} for i in range(count)]
    contract = planned_shared(segments)
    assert validate_expression_plan(contract, segments) == {
        key: contract[key] for key in ("全片营销策略", "分段表达计划")}
    for i in range(1, count + 1):
        text = segment_assignment_text(contract, i)
        assigned = json.loads(text.splitlines()[2])
        assert assigned == contract["分段表达计划"][i - 1]
        assert "原片本来存在的重复" in text and "人物、商品和声音等共用描述仍完整保留" in text


@pytest.mark.parametrize("fault", ["missing_strategy", "missing_plan", "missing_segment", "extra_segment",
    "wrong_index", "bool_index", "reordered", "changed_cut", "bool_time", "nan_time", "blank_duty", "wrong_type"])
def test_incomplete_or_wrong_range_plan_is_rejected(fault):
    segments = [{"start": 0, "end": 24.858192}, {"start": 24.858192, "end": 54.98832165498832}]
    contract = copy.deepcopy(planned_shared(segments))
    plans = contract["分段表达计划"]
    if fault == "missing_strategy": contract.pop("全片营销策略")
    elif fault == "missing_plan": contract.pop("分段表达计划")
    elif fault == "missing_segment": plans.pop()
    elif fault == "extra_segment": plans.append(copy.deepcopy(plans[-1]))
    elif fault == "wrong_index": plans[1]["segment_index"] = 1
    elif fault == "bool_index": plans[0]["segment_index"] = True
    elif fault == "reordered": plans.reverse()
    elif fault == "changed_cut": plans[1]["start"] = 25
    elif fault == "bool_time": plans[0]["start"] = False
    elif fault == "nan_time": plans[0]["start"] = float("nan")
    elif fault == "blank_duty": plans[1]["台词推进"] = "  "
    elif fault == "wrong_type": plans[1]["重点卖点"] = []
    with pytest.raises(RuntimeError, match="未派发子任务"):
        validate_expression_plan(contract, segments)


def test_non_marketing_and_no_product_need_no_fabricated_selling_points():
    segments = [{"start": 0, "end": 20}, {"start": 20, "end": 40}]
    contract = planned_shared(segments)
    contract["全片营销策略"] = "非营销剧情，无商品和营销卖点，按原故事推进。"
    for plan in contract["分段表达计划"]:
        plan["重点卖点"] = "无，保留本段原有剧情与对白。"
    assert validate_expression_plan(contract, segments)["分段表达计划"][1]["重点卖点"].startswith("无")
