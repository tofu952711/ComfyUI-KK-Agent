"""Source package for platform deployment; never ships operator credentials."""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "ComfyUI-DSH-Bridge-RunningHub-Source.zip")
    output = parser.parse_args().output.resolve()
    asr_dir = ROOT / "models" / "sensevoice"
    asr_manifest = json.loads((asr_dir / "MODEL_SOURCES.json").read_text(encoding="utf-8"))
    for name, digest in asr_manifest["sha256"].items():
        if hashlib.sha256((asr_dir / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Bundled SenseVoice checksum mismatch: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        def write(name, data):
            archive.writestr(f"{ROOT.name}/{name}", data)
        for folder in ("dsh_bridge", "nodes", "vendor/skills", "vendor/profile", "vendor/plugins"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                    write(path.relative_to(ROOT).as_posix(), path.read_bytes())
        write("__init__.py", (ROOT / "scripts/cloud_init.py.tpl").read_bytes())
        write("README.md", (ROOT / "docs/RUNNINGHUB.md").read_text(encoding="utf-8").replace(
            "(VIDEO-PROMPT.md)", "(docs/VIDEO-PROMPT.md)").replace(
            "(SPEAKER-ANALYSIS.md)", "(docs/SPEAKER-ANALYSIS.md)"))
        write("LICENSE", (ROOT / "LICENSE").read_bytes())
        write("requirements.txt", (ROOT / "requirements.txt").read_bytes())
        write("scripts/setup_speaker_models.py", (ROOT / "scripts/setup_speaker_models.py").read_bytes())
        write("scripts/setup_speaker_runtime.py", (ROOT / "scripts/setup_speaker_runtime.py").read_bytes())
        write("docs/SPEAKER-ANALYSIS.md", (ROOT / "docs/SPEAKER-ANALYSIS.md").read_bytes())
        for name in (*asr_manifest["sha256"], "MODEL_SOURCES.json"):
            write(f"models/sensevoice/{name}", (asr_dir / name).read_bytes())
        # Speaker weights are small and public. Include only this known model
        # directory if deployment preparation has installed it; no local media.
        for name in ("segmentation.onnx", "speaker_embedding.onnx", "LICENSE.segmentation", "MODEL_SOURCES.json"):
            path = ROOT / "models/speaker-diarization" / name
            if path.is_file():
                write(f"models/speaker-diarization/{name}", path.read_bytes())
        write("docs/VIDEO-PROMPT.md", (ROOT / "docs/VIDEO-PROMPT.md").read_bytes())
        for name in ("full_video_workflow.json", "full_video_api.json", "parallel_video_workflow.json", "parallel_video_api.json"):
            write(f"examples/{name}", (ROOT / "examples" / name).read_bytes())
        write("BUILD_INFO.json", json.dumps({"version": "0.8.7", "kind": "cloud-source",
              "codez_protocol": "openai-completions; user-supplied endpoint/key/model",
              "model": "deepseek-flash", "api": "https://api.deepseek.com/anthropic", "api_protocol": "deepseek-messages", "frontend_required": False,
              "native_runtime": "platform must install requirements.txt; not bundled",
              "speaker_runtime": "CPU only; standard sherpa-onnx; no release pin",
              "bundled_asr": "SenseVoiceSmall INT8", "asr_model_path": "models/sensevoice",
              "runninghub_deployed": False}, indent=2))
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any("windows-x64" in name or name.endswith(("/config.json", "/install.bat")) for name in archive.namelist())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"{output}\nBytes: {output.stat().st_size}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
