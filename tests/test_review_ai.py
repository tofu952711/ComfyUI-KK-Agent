"""Independent final-review config: no fallback or credential mixing."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dsh_bridge.review_ai import resolve_review_ai
MAIN=dict(api_key="main-local-key",base_url="https://main.invalid/v1",model="main-model",api_protocol="codez")

@pytest.mark.parametrize("value",[None,{}, {"review_ai":"沿用当前AI"},
    {"review_ai":"沿用当前AI","api_key":object(),"base_url":object(),"model":object()}])
def test_inherit_does_not_read_custom_fields(value):
    assert resolve_review_ai(value,**MAIN)==MAIN

@pytest.mark.parametrize("protocol",["openai-completions","deepseek-messages","codez"])
def test_custom_is_independent(protocol):
    custom=dict(review_ai="自定义",api_key="review-local-key",base_url="https://review.invalid/v1/",
                model="review-model",api_protocol=protocol)
    assert resolve_review_ai(custom,**MAIN)==dict(api_key="review-local-key",base_url="https://review.invalid/v1",model="review-model",api_protocol=protocol)

@pytest.mark.parametrize("field,value",[("api_key",""),("base_url"," "),("model",None),("api_protocol","bad"),("base_url","not-a-url")])
def test_custom_invalid_fails_without_falling_back(field,value):
    custom=dict(review_ai="自定义",api_key="review-local-key",base_url="https://review.invalid/v1",model="review-model")
    custom[field]=value
    with pytest.raises(ValueError):resolve_review_ai(custom,**MAIN)

@pytest.mark.parametrize("value",["自定义",{"review_ai":"bad"}])
def test_invalid_mode(value):
    with pytest.raises(ValueError):resolve_review_ai(value,**MAIN)
