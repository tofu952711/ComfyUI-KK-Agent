# 安装与运行环境

## Windows 完整包

从仓库 Releases 下载 Windows x64 ZIP，解压到 `ComfyUI/custom_nodes/`，得到 `ComfyUI-DSH-Bridge/__init__.py`。升级时先移走旧插件目录，避免重复加载，再重启 ComfyUI 并刷新浏览器。

包内包含独立 Python、Harness SDK/runtime、FFmpeg/FFprobe、SenseVoice 和说话人模型，不需要 Harness 桌面版或系统 Node.js。声音工具由 ComfyUI 的 Python 执行；提示缺少 `sherpa-onnx` 时，用该 Python 安装 `requirements.txt`。

支持 Windows x64 与近期 ComfyUI 的 V3/VIDEO 接口。Linux/cloud 使用匹配系统的 SDK/runtime，见 [云端部署](RUNNINGHUB.md)。

## 数据位置

- 插件代码、随附模型与许可证：`ComfyUI/custom_nodes/ComfyUI-DSH-Bridge/`。
- 面板配置、会话及统计：ComfyUI 用户目录 `default/dsh_bridge/`。
- 节点填写的 Key 和规则：保存在用户自己保存的工作流 JSON。
- 本次分析素材：任务的临时目录，结束后清理。

升级保留用户目录可继续使用面板设置和统计；不要将个人用户目录放进发行包。

## 重新打包

开发者可运行 `scripts/build_portable_runtime.py` 准备锁定版本的 Windows 运行时，再准备模型和 FFmpeg 文件，最后运行 `scripts/package_standalone.py`。构建脚本只在主动执行时下载资源，不在 ComfyUI 启动时运行。

运行时清单位于完整包的 `vendor/windows-x64/bundle.json`，模型来源、哈希和许可证在 `models/` 下。打包时保留这些文件及第三方许可证。
