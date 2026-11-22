"""Only presence and stable slot bindings; never touch waveform content."""
from pathlib import Path
import sys
import itertools
import json
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge.reference_audio import audio_bindings, attach_audio_bindings, audio_binding_text

class UntouchableAudio:
    def __bool__(self): raise AssertionError("Audio must not be inspected")
    def __getitem__(self, key): raise AssertionError("Audio must not be decoded")
    def __getattr__(self, key): raise AssertionError("Audio must not be analyzed")

@pytest.mark.parametrize("mask", list(itertools.product((False, True), repeat=3)))
def test_all_slot_combinations_are_presence_only(mask, tmp_path):
    values = tuple(UntouchableAudio() if present else None for present in mask)
    expected = [i for i,present in enumerate(mask,1) if present]
    bindings = audio_bindings(values)
    assert [v["input"] for v in bindings] == [f"audio{i}" for i in expected]
    report={"original_soundtrack":"untouched"}
    attach_audio_bindings(values,tmp_path,report)
    text=audio_binding_text(report)
    for i in range(1,4):
        assert (f"音频{i}绑定模特{i}" in text)==mask[i-1]
    assert report["original_soundtrack"]=="untouched"
    assert bool(text)==any(mask)
    assert (tmp_path/"audio_binding_evidence.json").exists()==any(mask)
    if any(mask):
        assert json.loads((tmp_path/"audio_binding_evidence.json").read_text(encoding="utf-8"))["mode"]=="presence_only"
    assert not list(tmp_path.glob("*.wav"))
    assert not (tmp_path/"reference-audio").exists()

def test_no_audio_keeps_old_evidence_unchanged(tmp_path):
    report={"existing":True}
    attach_audio_bindings((None,None,None),tmp_path,report)
    assert report=={"existing":True}
    assert not list(tmp_path.iterdir())
