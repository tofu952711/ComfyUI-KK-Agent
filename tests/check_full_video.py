"""Run the real ComfyUI full-video node against localhost; no real API key.

python tests/check_full_video.py --comfy-root <ComfyUI> --video <mp4>
    --person <jpg> --product <png> --output <verification-directory>
"""
import argparse
import asyncio
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import shutil
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--plugin-root", type=Path)
for name in ("comfy-root", "video", "person", "product", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
args = parser.parse_args()
test_root = Path(__file__).resolve().parents[1]
root = args.plugin_root or test_root
sys.path.insert(0, str(args.comfy_root))
sys.path.insert(0, str(test_root / "tests"))
from test_video_preparation import PreparedGateway
import numpy as np
import torch
from PIL import Image, ImageOps

entry = root / "scripts/cloud_init.py.tpl"
loader = SourceFileLoader("full_video_smoke", str(entry if entry.is_file() else root / "__init__.py"))
spec = importlib.util.spec_from_loader(loader.name, loader, is_package=True)
pkg = importlib.util.module_from_spec(spec)
pkg.__path__ = [str(root)]
sys.modules[loader.name] = pkg
loader.exec_module(pkg)
node = pkg.NODE_CLASS_MAPPINGS["DSH_FullVideoAgent"]
node.INPUT_TYPES()
from comfy_api.latest import InputImpl
video = InputImpl.VideoFromFile(str(args.video))
refs = []
for path in (args.person, args.product):
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        refs.append(torch.from_numpy(np.asarray(image).copy()).float().unsqueeze(0) / 255)

args.output.mkdir(parents=True, exist_ok=True)
def observer(stage, bridge, output):
    if stage == "finished":
        shutil.copytree(output, args.output / "media-analysis", dirs_exist_ok=True)

gateway = PreparedGateway(detail=True)
async def run():
    output = await node.execute(video=video, image1=refs[0], image2=refs[1],
        api_key="local-test-fake-key", base_url=gateway.url, model="gpt-6.1-sol",
        requirement="以图1人物、图2商品反推。", rules_text="外接测试规则：按画面与音轨证据输出中文提示词。", api_protocol="openai-completions",
        timeout_s=90, _observer=observer)
    text, evidence, status = output.result[:3]
    assert status == "ok" and text == "本地测试提示词完成"
    assert len(gateway.requests) == 2
    records = json.loads(evidence)
    assert len(records["agent_tool_calls"]) == 1
    assert records["agent_tool_calls"][0].endswith("get_frames")
    first = gateway.requests[0]
    wire = json.dumps(first, ensure_ascii=False)
    assert "外接测试规则：按画面与音轨证据输出中文提示词。" in wire
    assert "<skill_content" not in wire and "/viral-variation" not in wire
    assert not any(t["function"]["name"] == "skill" for t in first["tools"])
    images = [b for m in first["messages"] if isinstance(m.get("content"), list)
              for b in m["content"] if b.get("type") == "image_url"]
    assert len(images) == len(records["preparation.json"]["sheets"]) + 2
    summaries = {"status": status, "requests": len(gateway.requests), "first_request_images": len(images),
                 "tools": [t["function"]["name"] for t in first["tools"]],
                 "timings": records["timings"], "preprocessing": records["preparation.json"]["timings"],
                 "model_is_mock": True, "real_prompt_quality_tested": False}
    (args.output / "node-evidence.json").write_text(evidence, encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=True))
try:
    asyncio.run(run())
finally:
    gateway.close()
