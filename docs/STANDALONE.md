# 独立插件的开发选择

基于 sxxzwbl/ComfyUI-DSH-Bridge，原始提交为 538007a。保留原有 MIT 许可证、技能、V3 节点和会话面板。原始说明保存在 README.upstream.md。

官方 DeepSeek Harness 源码已放在本插件的同级 harness-sdk-source。该目录用于核对接口，不属于插件安装包。运行依赖固定为 deepseek-harness-sdk==0.2.2rc2，SDK 自动依赖同版本的 deepseek-harness-runtime-bin。

| 方式 | 本项目的选择依据 |
| --- | --- |
| 桌面版内部 CLI + Windows 命名管道 | 原版路径；依赖桌面安装目录和内部包结构，交付不便 |
| dsh web（默认 3080） | 官方浏览器应用，适合单独运行和查看 Harness；额外启动网页服务、端口及其客户端接口，不是此插件的通信协议 |
| npm CLI | 官方发布方式，但用户需准备 Node.js；源码开发还需 pnpm 和构建步骤 |
| Python SDK + 随附运行时 | 本版采用。包内独立 Python 调用正式 SDK，ComfyUI 通过 stdio 管理工作进程，不需桌面版、系统 Node.js 或额外监听端口 |

节点与面板共享一个 SDK 实例、同一套会话。一轮任务运行时，另一轮提交返回 busy，不排入不可见队列。停止或超时会关闭插件自己的运行时；该 SDK 暂无单轮取消协议。会话落盘后可以在相同数据目录恢复。连接错误、单次请求超时、限流及服务端临时错误会在同一模型步骤内最多自动重试3次，依次等待5秒、15秒、30秒；保留已完成的工具结果，不重跑整段视频。鉴权、参数、额度或上下文错误不重试。停止或任务总超时会中止等待。

通过 sdk profile 的 patch 保留技能及图像、文本读取，关闭 shell、文件写入、调度、Office 及不需要的 agent 工具。普通 SDK 启动不下载 Office/文档运行环境。插件不加载桌面版凭据，也不需要 dsh-purge。

0.4.0 默认通过官方运行时内置 `llm-pi-ai` 适配器连接 APIMart 的 OpenAI Chat Completions 协议。配置 patch 指定 `apiKeyEnv`、`baseURL`、模型与图片能力，关闭不必要的兼容参数及供应商内置重试，使用插件统一的5/15/30秒重试；凭据只通过工作进程环境传递，不写入 patch。DeepSeek Messages 路由保留为可选预设。协议、供应商、地址、模型参与会话 ID 的路由散列，切换后不会复用旧模型上下文。模型必须支持图片和工具调用。本版沿用原项目的抽帧拼图，尚未新增 agent 动态补抽帧或音轨识别。

0.4.0 的 Windows x64 免安装包包含 CPython 3.12.10 embedded、SDK/runtime 和 Pydantic 等完整依赖，用户解压后即可加载，本地运行无需下载或 pip。二进制只针对 Windows x64；模型 API 请求仍需联网。包内 Python 通过 `_pth` 隔离，与 ComfyUI 的 site-packages 无关。打包保留第三方许可证，并排除 API Key、配置、会话、媒体缓存、pip 生成的启动器和本地测试环境。

开发者重建：用开发 Python 执行 `scripts/build_portable_runtime.py`，从官方 Python 发布站和 PyPI 获取锁定版本，再执行 `scripts/package_standalone.py`。Python embedded 压缩包的 SHA256 固定在构建脚本中；依赖锁定在 requirements-sdk.txt，实际版本清单位于二进制包的 vendor/windows-x64/bundle.json。这两个构建脚本不会在 ComfyUI 启动时运行。
