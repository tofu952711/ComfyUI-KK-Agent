"""Build the distributable without local settings, media, sessions or Git data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"dsh_bridge", "nodes", "routes", "web", "vendor", "docs", "examples", "scripts", "tests"}
ROOT_FILES = {"__init__.py", "README.md", "LICENSE", "requirements.txt", "requirements-sdk.txt",
              "pyproject.toml", "doctor.bat", "uninstall.bat", ".gitattributes", ".gitignore"}
EXCLUDED = {"__pycache__", ".pytest_cache", ".git", "logs", "media", "user", ".venv", "native-cache"}
INSTALLERS = {"scripts/install.py", "scripts/setup_standalone.py"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "ComfyUI-DSH-Bridge-Windows-Portable.zip")
    args = parser.parse_args()
    target = args.output.resolve()
    bundle = ROOT / "vendor" / "windows-x64"
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    if not all((bundle / name).is_file() for name in manifest["required_files"]):
        raise RuntimeError("Build the complete portable runtime before packaging")
    asr_dir = ROOT / "models" / "sensevoice"
    asr_manifest = json.loads((asr_dir / "MODEL_SOURCES.json").read_text(encoding="utf-8"))
    for name, digest in asr_manifest["sha256"].items():
        if hashlib.sha256((asr_dir / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Bundled SenseVoice checksum mismatch: {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with ZipFile(target, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if relative.as_posix() in INSTALLERS or "bin" in relative.parts:
                continue
            if (not path.is_file() or any(part in EXCLUDED for part in relative.parts)
                    or path.suffix in {".pyc", ".pyo", ".log"}):
                continue
            if relative.parts[0] not in DIRECTORIES and str(relative) not in ROOT_FILES:
                model_files = {f"models/speaker-diarization/{name}" for name in
                               ("segmentation.onnx", "speaker_embedding.onnx", "LICENSE.segmentation", "MODEL_SOURCES.json")}
                model_files.update(f"models/sensevoice/{name}" for name in
                                   (*asr_manifest["sha256"], "MODEL_SOURCES.json"))
                if relative.as_posix() not in model_files:
                    continue
            archive.write(path, f"{ROOT.name}/{relative.as_posix()}")
            count += 1
        archive.writestr(f"{ROOT.name}/BUILD_INFO.json", json.dumps({
            "release": "2026.11.20", "version": "0.8.5", "sdk_runtime": "0.2.2rc2", "upstream_commit": "538007a",
            "default_api": "https://api.apimart.ai/v1", "default_model": "gpt-6.1-sol",
            "desktop_required": False, "dependencies_downloaded_during_install": False,
            "portable_platform": "windows-x64", "bundled_python": "3.12.10",
            "bundled_asr": "SenseVoiceSmall INT8", "asr_model_path": "models/sensevoice",
        }, indent=2))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        for name in (*asr_manifest["sha256"], "MODEL_SOURCES.json"):
            assert f"{ROOT.name}/models/sensevoice/{name}" in archive.namelist()
        for name in archive.namelist():
            assert not EXCLUDED.intersection(Path(name).parts)
            assert not name.endswith(("/config.json", "/bridge-sessions.json", "/history.jsonl"))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"Package: {target}\nFiles: {count + 1}\nBytes: {target.stat().st_size}\nSHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
