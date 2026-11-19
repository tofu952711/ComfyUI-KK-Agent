> **当前执行策略：31.9秒及以下直接反推；超过31.9秒且不超过60秒先裁成两段，再反推。** 第一个文本框为用户要求，第二个为反推系统提示词，新增第三个「详细分段要求（31.9＜时长≤60秒）」。无论第三框是否填写，均由AI结合剧情、分镜、前两框改编目标及参考图判断切点，最多两段；脚本只执行实际裁切。先完成实际裁切，再启动第二框反推。短视频不读取、不发送第三框；超过60秒明确报错。现有五个VIDEO端口保留兼容，仅分段时使用前两个；不分段时五个VIDEO接口全部阻止下游保存。下方旧并行／五段策略已被此策略替代。

> **当前接口：image1—image10 + video1—video5。** 图片均为可选的通用参考，含义由用户要求／系统提示词说明；未连接的编号不重排。保留原来的提示词、分析证据、状态三个输出，在后面增加五个VIDEO输出。超过31.9秒且不超过60秒时，AI需通过set_video_segments提交两段连续覆盖全片的秒数，节点才会实际裁切；31.9秒及以下没有VIDEO输出，不保存整片。分段视频包含原音轨，采用CPU H.264/AAC编码；输出存于VIDEO内存对象，任务临时目录清理后仍有效，需要长期保存请接SaveVideo。旧人物／商品连线迁移到image1／image2，文本控件顺序不变。

> **节点精简：仅保留「DSH Agent 完整视频反推」。** 已删除提示词引擎、帧阵列拼图、视频反推（独立 Key）的节点实现与注册，并移除对应旧示例。现有工作流请使用 full_video_workflow.json 或 full_video_api.json；本地与云端入口均只提供完整视频节点。下方历史文档提到的旧节点已不再提供。

> **当前行为：两个文本框。** 完整视频节点第一个框「本次用户要求」发送为用户输入，第二个框「系统提示词（原Skill正文）」发送为模型系统提示词；第二个框默认为空，可直接粘贴规则，也可右键转为输入连接文本节点。插件不再内置或加载爆款裂变 Skill。旧工作流若仅显示一个框，请重新添加完整视频节点。原有视频预处理、CPU声音工具、重试及任务清理保留。下方旧版本中的内置爆款裂变说明已不适用。

# RunningHub 公开工作流版（0.7.2）

**CPU 说话人分析**：按需 MCP 工具 `diarize_speakers` 使用 CPU，部署安装普通 `sherpa-onnx`；模型需预置或在部署时下载。详见 [部署和调用说明](SPEAKER-ANALYSIS.md)。任务运行时不下载权重。

**0.8.4 图片完整性修复**：完整视频节点将 DeepSeek 协议在文件上传失败后的 Base64 图片预算提高至128 MiB，禁用自动省略参考图；超限明确报错。同素材离线回退验证20张图片全部保留。Skill按用户要求仅删除“不编造材质或功效”一句，其他正文不变。

**0.8.3 更新：完整视频专用工作流请用 `examples/full_video_workflow.json`**，详见 [完整视频反推说明](VIDEO-PROMPT.md)。它接收 VIDEO、人物图、商品图，内置概览、每秒4帧动作序列、切点四帧对照、按需补帧和本地转写，首轮加载原版爆款裂变技能。本文件下方的「仅抽帧、没有音轨工具」描述仅适用于旧帧阵列节点；旧版0.7.4的额外创作约束已移除，完整视频路径遵循原 Skill。ASR 需要平台提供 sherpa-onnx 和本地 SenseVoice 权重，源码包不含权重。

0.8.3 增加声音补正：本地分析声音变化，对疑点提供口型与回应连续帧，并允许 agent 用 `analyze_voices` 局部复核。它模仿 Codex 当时的取证方法，不固定声音人数，不把音高变化直接当作换人；原版 Skill 保持不变。

目标：每位使用者在工作流节点里填写自己的 DeepSeek 官方 Key，本地 Harness agent 调用 `deepseek-flash` 和技能反推视频提示词。无需右下角 DSH 面板，不依赖发布者电脑的设置。

## 用户怎么用

导入 `examples/runninghub_video_workflow.json`。接线：

已安装用户提供的「爆款裂变」技能 `viral-variation`。使用 `examples/runninghub_viral_workflow.json`，或将节点「任务」选为「爆款裂变」。该任务按技能输出完整简体中文结构：参考素材、故事与场景、动作与摄影机、对白与声音、背景音乐；不转成原 MiniMax H3 英文格式，也不额外输出营销分析报告。新技能保留用户压缩包中的原始文件，随云端源码包一起交付。

```text
加载视频 → DSH 帧阵列拼图 → DSH Agent 视频反推（独立 Key） → 保存文本/后续生成节点
                  时间轴 ↗
```

在「DSH Agent 视频反推（独立 Key）」节点中：

| 输入 | 值 |
| --- | --- |
| API Key | 当前使用者自己的 DeepSeek 官方密钥，发布模板留空 |
| Base URL | `https://api.deepseek.com/anthropic` |
| 分析模型 ID | `deepseek-flash` |
| 接口协议 | `deepseek-messages` |
| 任务 | 默认「爆款裂变」 |
| 反推要求 | 按需要填写 |

Key 是 DeepSeek 官方平台的模型密钥，和 RunningHub 平台自身的 Key 不同。节点输出「提示词」「分析」「状态」三个 STRING，可连接后续工作流。「爆款裂变」的中文正文完整放在提示词输出中，分析输出为空；其他任务沿用 MiniMax H3 英文格式与中文分析。分析模型为 DeepSeek Flash。

爆款裂变技能规则可处理音轨与精确切点，但当前插件只提供抽帧拼图，不提供音轨转写或自动补抽帧。任务会明确这些证据限制，不假称听过原声或核实未采样的切镜。可在「反推要求」补充已核实的对白、时间信息和商品信息，在「参考图用途」说明参考图职责。

**公开发布或分享前，清空 API Key。** 普通节点文本会保存在工作流 JSON 和平台任务输入记录中；本插件无法改变平台对任务输入的保存规则。每位使用者运行自己的副本时填写自己的 Key。

每次执行创建独立临时 Harness home、工作目录和会话；不使用发布者保存的模型密钥，不把使用者的 Key 写入共享 `config.json`，不保存到本地 DSH 面板。运行结束后关闭该运行时并清理临时目录。连接错误、单次请求超时、限流及服务端临时错误会在同一模型步骤内最多自动重试3次，依次等待5秒、15秒、30秒；保留已完成的工具结果，不重跑整段视频。鉴权、参数、额度或上下文错误不重试。停止或任务总超时会中止等待。

## 平台部署条件

`ComfyUI-DSH-Bridge-RunningHub-Source.zip` 是交给平台部署的源码包，**不代表已经在 RunningHub 上架或验收**。包含两个标准节点、官方技能及配置，不包含 Windows `.exe`、本地面板和私人数据。

上传工作流 JSON 只包含图和参数，不会自动安装插件代码。必须先让 RunningHub 的工作环境能够提供这两个自定义节点。具体安装/上架入口需按平台当前流程处理，本次没有登录 RunningHub 或提交插件。

平台维护者需将插件放入 `ComfyUI/custom_nodes/ComfyUI-DSH-Bridge`，在平台 Python 环境安装该源码包的 `requirements.txt` 并重启 ComfyUI。官方 SDK 会安装同版本、对应系统的原生运行时；不是在使用者的电脑安装。要求 Python 3.10+、近期 ComfyUI 的 V3/VIDEO 接口、原生子进程执行权限、临时目录可写，以及能联网访问 DeepSeek 官方 API。Pillow、numpy、aiohttp、torch 使用 ComfyUI 环境。

普通运行时不下载运行资源，不需要桌面版、系统 Node 或独立网页端口。如果平台禁止原生子进程或不安装此 SDK，就不能仅靠修改工作流 JSON 使用 Harness agent，需要另行部署 agent 服务。

## 验证范围

Windows 上已使用官方 Harness 原生运行时与本地 DeepSeek Messages / OpenAI 模拟接口，检查图片传入、真实技能读取、节点输出、不同 Key 和上下文的并行隔离、临时数据清理。云端源码包另从新目录解压验证。Linux 路由不会选用 Windows bundle；本机没有 Linux 验证环境，尚未做 Linux 或真实 RunningHub 验收。

已在 Windows 使用真实 DeepSeek 官方 Key 跑通 31.2 秒视频抽帧、人物与商品双参考图、Harness agent 及爆款裂变技能调用。2026-11-17 实测 agent 耗时 109.797 秒，本次整体运行 116.047 秒（复用已准备的抽帧）。模型第二轮输出用量为 15579 tokens；使用 32768 上限。成稿格式及技能调用通过，精确切镜、商品卖点与口播时长仍需人工复核。尚未通过 RunningHub 部署验收。

RunningHub 官方[工作流接入示例](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287342)介绍通过 `nodeInfoList` 修改节点输入；如果通过平台 API 调用，可按示例工作流节点 ID，将本节点的 `api_key`、`base_url`、`model` 作为输入参数。本说明不将 RunningHub API Key 用作 DeepSeek 官方 Key。

## DeepSeek 官方接口依据

[视觉文档](https://api-docs.deepseek.com/guides/vision)说明 `deepseek-flash` 支持图片输入；[Anthropic 兼容接口](https://api-docs.deepseek.com/guides/anthropic_api)支持图片、`tool_use`、`tool_result`，Base URL 为 `https://api.deepseek.com/anthropic`。使用 DeepSeek 开放平台的 API Key。

2026-11-17 在用户关闭 VPN 后，对官方 `/models` 发起不带 Key 的直接请求，约 1.18 秒返回 HTTP 401，验证当前网络可达，没有调用付费模型。不带 Key 返回 401 属正常鉴权响应。

此版本默认分析模型由 GPT 6.1 sol 改为 DeepSeek Flash；DeepSeek 官方 Key 不能调用 GPT。仍保留 APIMart/OpenAI 兼容路由，若要使用，需同时改为 `openai-completions`、APIMart 地址、`gpt-6.1-sol` 和对应 Key。旧 0.5 工作流不含协议字段时，原 OpenAI 路由会保留；请导入本版示例获得 DeepSeek 默认设置。

可分别连接「参考图」和「参考图2」，例如人物与商品各一张，在「参考图用途」标注 `@图片1=人物；@图片2=产品`。两张图片分别传入模型，不合并成一张，不会只取图片批次的第一张。

0.7.3 会将达到输出上限的回复报告为 `output_limit`，不将截断提示词作为成功结果。运行时保留本次结束原因、正文/推理字符数和用量计数用于诊断，不保存推理正文，当前版本按上文固定间隔重试临时模型错误。

0.7.4 在工作流节点增加「模型输出上限」，默认 32768，包含推理 token；可按所用模型能力与费用需求调整。加强抽帧证据约束：抽帧数量不是镜头数量，采样间隔不是镜头时长。新商品的价格、优惠、库存和未核实功效需用户提供，不应从旧商品照搬或自行编造。
