# 云端部署

云端需要先安装插件及依赖，单独上传工作流 JSON 不会安装节点。Windows 完整 ZIP 包含 Windows 原生运行时，不能直接用于 Linux 平台；本项目尚未完成 RunningHub 线上部署验收。

## 平台环境

- Python 3.10+，支持 V3 / VIDEO 接口的近期 ComfyUI。
- 使用平台的 Python 安装 `requirements.txt`，提供 Pillow、numpy、PyAV、torch 和 aiohttp。
- 安装 FFmpeg / FFprobe，允许启动本地子进程、读写临时目录并访问所选模型接口。
- 预置 `models/sensevoice/` 的 SenseVoice 权重与词表；说话人模型见 [部署说明](SPEAKER-ANALYSIS.md)。普通任务运行时不下载权重。

准备完整模型文件后可用 `python scripts/package_cloud.py --output <目标ZIP路径>` 生成云端源码包。该包通过云端入口提供标准节点，不加载本地面板和前端扩展。源码仓库本身不含大体积模型，模型来源与许可证在 `models/` 中。

## 工作流

使用 `examples/full_video_workflow.json` 或对应 API 格式，接线和规则见 [视频反推](VIDEO-PROMPT.md)。云端包不提供浏览器自动迁移，需导入适合该环境的工作流。

每位使用者填写自己的模型服务 Key、地址、模型及接口协议；RunningHub 平台 Key 不能代替模型服务 Key。公开模板必须清空 Key，私有规则也应删除。平台可能记录任务输入，请按平台规则管理凭据。

分段视频需要连接平台可用的 SaveVideo，文本保存节点也须由平台提供。若平台禁止原生子进程或无法安装官方 SDK/runtime，无法只靠修改工作流 JSON 运行此插件。
