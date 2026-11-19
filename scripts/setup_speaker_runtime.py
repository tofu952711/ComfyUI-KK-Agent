"""Check the standard CPU speech runtime without changing the environment."""
from __future__ import annotations

import argparse
import importlib
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Check only; this script never installs packages")
    parser.parse_args()
    try:
        runtime = importlib.import_module("sherpa_onnx")
    except ImportError as exc:
        raise RuntimeError("缺少CPU语音运行库，请先安装 requirements.txt") from exc
    print(json.dumps({"provider": "cpu", "sherpa_onnx": runtime.__version__,
                      "installs_packages": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
