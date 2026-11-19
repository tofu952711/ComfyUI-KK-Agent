"""Developer-only: assemble the Windows x64 runtime; never runs at plugin startup."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.12.10"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, help="Already downloaded official Python embedded ZIP")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--packages-ready", action="store_true", help="Validate existing pinned packages instead of pip")
    args = parser.parse_args()
    bundle = ROOT / "vendor" / "windows-x64"
    packages = bundle / "packages"
    if not args.packages_ready:
        if packages.exists() and any(packages.iterdir()):
            parser.error("packages is not empty; use a fresh directory or --packages-ready")
        command = [sys.executable, "-m", "pip", "install", "--target", str(packages),
                   "--only-binary=:all:", "--no-compile", "--no-deps", "--python-version", "3.12",
                   "--platform", "win_amd64", "--implementation", "cp", "--abi", "cp312",
                   "-r", str(ROOT / "requirements-sdk.txt")]
        if args.proxy:
            command += ["--proxy", args.proxy]
        subprocess.run(command, check=True)
    versions = {dist.metadata["Name"].lower().replace("_", "-"): dist.version
                for dist in importlib.metadata.distributions(path=[str(packages)])}
    for line in (ROOT / "requirements-sdk.txt").read_text(encoding="utf-8").splitlines():
        if "==" in line and not line.startswith("#"):
            name, expected = line.split("==")
            if versions.get(name) != expected:
                raise RuntimeError(f"Pinned package missing or mismatched: {name}")
    if args.archive:
        payload = args.archive.read_bytes()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"https": args.proxy} if args.proxy else {}))
        with opener.open(PYTHON_URL, timeout=120) as response:
            payload = response.read()
    if hashlib.sha256(payload).hexdigest() != PYTHON_SHA256:
        raise RuntimeError("Python archive SHA256 mismatch")
    import io
    python = bundle / "python"
    python.mkdir(parents=True, exist_ok=True)
    with ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            (python / name).resolve().relative_to(python.resolve())
        archive.extractall(python)
    # Embedded Python ignores PYTHONPATH and the host's site-packages.
    (python / "python312._pth").write_text("python312.zip\n.\n../packages\n", encoding="utf-8")
    required = ["python/python.exe", "python/python312.dll", "python/python312.zip", "python/python312._pth",
                "packages/deepseek_harness/__init__.py", "packages/pydantic/__init__.py",
                "packages/pydantic_core/_pydantic_core.cp312-win_amd64.pyd",
                "packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-win-x64.exe",
                "packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-win-x64-rg.exe"]
    if not all((bundle / name).is_file() for name in required):
        raise RuntimeError("Portable runtime incomplete")
    (bundle / "bundle.json").write_text(json.dumps({
        "platform": "windows-x64", "python_version": PYTHON_VERSION,
        "python_source": PYTHON_URL, "python_archive_sha256": PYTHON_SHA256,
        "sdk_version": versions["deepseek-harness-sdk"],
        "runtime_version": versions["deepseek-harness-runtime-bin"],
        "packages": versions, "required_files": required,
    }, indent=2), encoding="utf-8")
    print(f"Portable runtime ready: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
