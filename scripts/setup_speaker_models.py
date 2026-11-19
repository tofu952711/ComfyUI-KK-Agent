"""Deployment-time downloads only; ~34 MB of FP32 speaker models, no ASR.

Run with the ComfyUI Python. Runtime tools never invoke this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = BASE + "/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = BASE + "/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
SEGMENTATION_SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"
# Published in the upstream speaker-recongition-models/checksum.txt.
EMBEDDING_SHA256 = "f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11"


def download(url, path, expected):
    if sys.platform == "win32" and shutil.which("curl.exe"):
        # Windows curl uses the OS certificate store, including enterprise roots.
        subprocess.run(["curl.exe", "--fail", "--location", "--silent", "--show-error", "--retry", "2",
                        "--connect-timeout", "20", "--max-time", "600", "--output", str(path), url], check=True)
    else:
        with urllib.request.urlopen(url, timeout=120) as response, path.open("wb") as target:
            shutil.copyfileobj(response, target)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"SHA256 mismatch: {path.name}; no models installed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=Path(os.environ.get(
        "DSH_BRIDGE_SPEAKER_MODEL_DIR", "") or ROOT / "models/speaker-diarization"))
    args = parser.parse_args()
    destination = args.model_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="dsh-speakers-") as temporary:
        staging = Path(temporary)
        archive = staging / "segmentation.tar.bz2"
        embedding = staging / "speaker_embedding.onnx"
        print("Downloading segmentation (~7 MB archive)...", flush=True)
        download(SEGMENTATION_URL, archive, SEGMENTATION_SHA256)
        print("Downloading speaker embedding (~28 MB)...", flush=True)
        download(EMBEDDING_URL, embedding, EMBEDDING_SHA256)
        # Extract exact regular-file members; never extract arbitrary archive paths.
        with tarfile.open(archive, "r:bz2") as bundle:
            for member_name, output in (("model.onnx", "segmentation.onnx"),
                                        ("LICENSE", "LICENSE.segmentation")):
                member = bundle.getmember("sherpa-onnx-pyannote-segmentation-3-0/" + member_name)
                if not member.isfile():
                    raise RuntimeError("Unexpected segmentation archive member")
                with bundle.extractfile(member) as source, (staging / output).open("wb") as target:
                    shutil.copyfileobj(source, target)
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("segmentation.onnx", "speaker_embedding.onnx", "LICENSE.segmentation"):
            source = staging / name
            temporary_target = destination / (name + ".download")
            shutil.copyfile(source, temporary_target)
            temporary_target.replace(destination / name)
        (destination / "MODEL_SOURCES.json").write_text(json.dumps({
            "segmentation": {"url": SEGMENTATION_URL, "archive_sha256": SEGMENTATION_SHA256,
                             "upstream": "https://huggingface.co/pyannote/segmentation-3.0"},
            "embedding": {"url": EMBEDDING_URL, "sha256": EMBEDDING_SHA256,
                          "upstream": "https://modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common",
                          "license": "Apache-2.0; see upstream model card"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Speaker models ready: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
