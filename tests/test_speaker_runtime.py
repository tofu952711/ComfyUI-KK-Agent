"""The CPU runtime check does not install packages or inspect accelerators."""
from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("speaker_runtime_setup", ROOT / "scripts/setup_speaker_runtime.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_check_only_imports_speech_runtime(monkeypatch, capsys, flags):
    monkeypatch.setattr(sys, "argv", ["setup_speaker_runtime.py", *flags])
    def load(name):
        assert name == "sherpa_onnx"
        return SimpleNamespace(__version__="test")
    monkeypatch.setattr(setup.importlib, "import_module", load)
    assert setup.main() == 0
    assert '"provider": "cpu"' in capsys.readouterr().out


def test_missing_runtime_has_install_guidance(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["setup_speaker_runtime.py"])
    def missing(name):
        raise ImportError(name)
    monkeypatch.setattr(setup.importlib, "import_module", missing)
    with pytest.raises(RuntimeError, match="requirements.txt"):
        setup.main()
