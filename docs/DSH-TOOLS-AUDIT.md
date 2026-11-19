# DSH 视频反推工具审核（2026-11-17）

审核范围：本地官方 `deepseek-ai/deepseek-harness` 源码，SDK/runtime 0.2.2rc2，以及本机实际启动的 SDK agent。GitHub CLI 未登录，网页读取未得到有效内容，因此不将本次审核称为对最新在线版本的确认。

| 工具或组件 | 来源 | 本次用途与状态 |
|---|---|---|
| `skill` | DSH 原生 | 加载用户原始 `viral-variation`，保持技能正文不变 |
| `read`、`read_image` | DSH 原生 | 文件与图片读取，已在 agent 工具清单中注册 |
| `glob`、`grep` | DSH 原生 | 文件定位和检索，已注册 |
| `working_directory` | DSH 原生 | 工作目录查询，已注册 |
| MCP 客户端与资源工具 | DSH 原生 | 启动本地媒体服务，将工具结果及图片交给 agent；已实测发现5个工具 |
| `pwsh` / `bash` | DSH 原生 | 可以执行外部脚本，但本次媒体测试不需要开放任意命令，保持关闭 |
| workspace-dependencies | DSH 可选组件 | 依赖已有运行资源，不等于包含视频处理或转写模型，本次不启用 |
| SenseVoice 语音输入 | DSH 实验组件 | 使用 SenseVoiceSmall ONNX + Silero VAD，主要用于语音输入，返回纯文本与耗时；非完整视频逐句对齐工具 |
| 视频切镜/抽帧整套脚本 | 未在审阅源码中发现 | 不声称 DSH 已内置；由插件通过官方 MCP 接口接入 |

## 本次实际接入的媒体工具

这些是插件提供的本地工具，由真正的 DSH agent 调用。不是 DeepSeek 模型自带脚本。

| agent 工具名 | 实现 | 已做的本地验证 |
|---|---|---|
| `mcp__video__inspect_video` | PyAV读取原视频元数据 | 用户视频31.2秒、30fps、936帧、1080×1920，1条音轨 |
| `mcp__video__detect_shots` | 相邻帧RGB差异与直方图变化 | 逐帧检测到21个切点候选；候选不是已核实镜头，需看前后帧 |
| `mcp__video__get_frames` | 按原视频时间抽帧，返回时间标签拼图 | 每次1–12帧，DSH MCP直接传图片给模型，已实际调用 |
| `mcp__video__transcribe_audio` | PyAV解码音轨 + 本地sherpa-onnx SenseVoiceSmall INT8 | 复用本机模型，转写约4.8秒；有识别错字，粗略5–10秒窗口不等于逐字对齐 |
| `mcp__video__check_draft` | 提示词与对白时槽规则检查 | 能提示采样冒充镜头、未核实商品信息和超长口播；不代替视觉与听核 |

媒体服务只接收本次视频和输出目录，不接收模型Key。DSH官方MCP客户端会清洗子进程环境中的凭据变量。服务不提供执行任意命令、修改用户素材、自动安装依赖或下载模型的入口。

## 当前测试入口与依赖

新节点 `DSH_FullVideoAgent` 直接接收原视频、人物图1、商品图2。每次执行把素材复制到临时工作目录，经 DSH agent 使用技能和媒体工具生成提示词，同时输出调用证据。旧拼图节点保留。

本地测试使用 `.verify-venv` 已有的 PyAV、Pillow、numpy，新增 `sherpa-onnx==1.13.4`，模型复用 `C:/Users/Nelly/.cache/sherpa-onnx-sensevoice/`。模型目录须含 `model.int8.onnx`、`tokens.txt`。没有目录时转写会明确失败，不会静默假装听过。

这轮先验证调用链路。Windows便携包、RunningHub源码包尚未包含这套新增节点的完整依赖交付；平台可用已有脚本替换工具内部实现，继续复用DSH与MCP接口。

## 本轮真实测试结果

2026-11-17 18:28:06开始，18:34:23完成，节点368.453秒、总计376.282秒。DeepSeek官方`deepseek-flash`通过真正Harness agent调用skill一次、视频检查一次、切镜检测一次、本地转写一次、补帧九次、草稿检查两次。五种MCP工具均实际完成，生成完整中文结构提示词。结果目录为`完整视频Agent实测/20261117-182806/`。

调用链路通过，成稿仍为待复核草稿：模型推测声线/情绪/音效、保留待确认价格库存，并存在人物商品细节漂移风险。工具证据不等于质量验收。报告中的usage仅是最后一次模型调用，不是全任务累计用量。
