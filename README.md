# ComfyUI KK Agent 视频反推

ComfyUI 视频分析与反推插件，本仓库发布本机整理版本；基于原项目的 MIT 许可证保留原作者署名。

## 安装与使用

1. 从本仓库 Releases 下载完整 Windows x64 ZIP。仓库源码不包含大体积运行时和模型，直接下载源码不能替代完整包。
2. 将 ZIP 中的 `ComfyUI-DSH-Bridge` 文件夹解压到 `ComfyUI/custom_nodes/`，重启 ComfyUI，并刷新浏览器。
3. 添加 **KK agent 视频反推** 节点，或导入 `examples/parallel_video_workflow.json`。
4. 填写自己的 API Key、接口地址、模型与规则；示例中的 Key 和规则输入为空。
5. 不足 32 秒执行 A 反推；32—60 秒执行 B 分段和反推。B 的 VIDEO 输出连接标准 SaveVideo，反推资料连接独立反推节点。

完整 Windows 包包含运行时、FFmpeg/FFprobe、SenseVoice 与说话人模型，也保留插件附带的 14 套 Skill 文件。当前视频反推节点使用用户提供的规则，不自动加载这些内置创作 Skill。没有将个人工作流、运行记录或真实 API Key 打包。

节点输入的 API Key 和规则会随用户保存的工作流写入 JSON，分享工作流前需自行清空。源码与完整包均保留上游名称、许可证及第三方来源信息。

以下保留原版本说明，其中历史节点、行为及版本号可能与当前版本不同，以当前代码和以上说明为准。

---

> **CodeZ 思考等级适配（2026-11-19）：** 依据 [CodeZ 官方配置文档](https://docs.codezsy.com/codez/#codex-cli-使用指南)，`codez` 配置使用 `/v1/responses`，通过 `reasoning.effort` 发送高中低，auto不显式指定等级。第二框原文放入独立 `instructions`，第一框、共用素材资料、参考图及视频拼图保持完整，工具续轮保留推理状态和工具结果。zdjapi域名仍走原Chat Completions和既有developer角色兼容；`openai-completions`与`deepseek-messages`不切换。审计记录实际协议和发送等级，服务端是否采用需结合其响应／日志确认。

> **接口角色兼容（2026-11-19）：** 已对照复现 api.zdjapi.com 的 gpt-6.1-sol 不遵从 system 指令、但遵从 developer 指令。仅此线路／模型的A链路，将第二框原文通过 developer 指令角色发送；仍是独立高优先级规则消息，不拼入第一框，不改正文，不增加提示文字。其他Chat Completions线路和Messages协议保持 system；CodeZ Responses使用独立instructions。发送校验记录 instruction_role、原文字数／哈希、图片数量，位置为用户数据目录 dsh_bridge/request-audit。

> **独立链路路由（2026-11-19）：** 脚本读取VIDEO实际时长，不四舍五入，只按时长选择：不足32秒（包含31.95秒）进入A，32至60秒进入B；超过60秒或无效时长报错。A严格保留第一框用户文本、第二框系统文本的原文，另外默认携带共用素材资料：视频信息、采样覆盖、切点候选、音轨转写、声音证据、参考图对应关系以及带时间标签的抽帧拼图和说明。A不分段、不复核。B先将「B分段规定」原文作为系统规则，由AI主动调用set_video_segments工具，工具使用FFmpeg实际剪出2—5段并用FFprobe校验；成功后在独立会话中以「B反推提示词规定」原文作为系统规则，传递已切出的范围及共用素材，生成提示词。两阶段均携带第一框原文、参考图和预处理资料，素材只准备一次。B不读取A的系统规则。CodeZ与zdjapi沿用各自既有协议及思考等级适配。

> **完整视频图片限额：** A与B的每个阶段最多接收50张图片（参考图和抽帧拼图合计），完整保留既有素材。当前60秒内预处理与10张参考图的组合最多约45张，不再被DSH默认20张限额拦截；超过50张明确报错。单图及总字节限制沿用原配置，其他节点不变。

> **节点布局更新：** 本次用户要求、A系统提示词、B分段规定、B反推提示词规定的输入区最低高度分别为120、260、140、260像素，节点最小宽度520像素。B反推规定紧接在B分段规定下方，两个框独立保存，支持连接外部文本节点。旧工作流自动补空的新框，保留已有规则、思考等级及用量开关。移除底部固定320像素的视频预览／状态区，结果仍由原输出端口返回。更新节点定义后需重启ComfyUI并刷新浏览器。

> **思考等级：节点新增下拉框，默认 high。** 可选high（高）、medium（中）、low（低）、auto（接口默认，不显式指定）。A的反推与工具续轮使用同一等级。Chat Completions发送reasoning_effort，CodeZ Responses发送reasoning.effort；DeepSeek Messages通过官方SDK映射为thinking与output_config.effort。接口拒绝时明确报错，不静默删除参数或降级。新增控件追加在原控件之后，旧工作流默认high，保留已保存的其他等级。不会修改第二框的系统提示词。

> **当前执行策略：A与B相互独立。** 入口先路由，再进入各自实现；提示词内容不能改变路由。第三框为「链路B：分段规定」，下方为「链路B：反推提示词规定」。A仅请求A规则上游，B仅请求两个B规则上游。B由AI判断段数与切点，并通过工具完成实际裁切；父节点只接收工具成品，不自动均分、不补执行裁切。未实际调用工具、裁切失败或反推空响应均报错，不再返回空提示词冒充成功。B反推阶段不提供分段工具，也不会回退至A。下方历史分段策略不再适用。

> **当前接口：image1—image10 + video1—video5。** 图片为A/B共用素材的可选参考，编号不重排。保留提示词、分析证据、状态三个输出及五个VIDEO端口，控件顺序兼容旧工作流。A不生成视频；B按工具完成的段数返回video1—videoN，其余VIDEO分支阻止下游执行。工具成品读入内存，任务临时目录清理后仍能连接SaveVideo保存。keep_audio控制B成品音轨。分析证据记录实际范围、源帧覆盖校验、分阶段调用、规则哈希、审计文件与耗时。Windows插件随包提供FFmpeg/FFprobe；其他平台需安装这两个命令。

> **保存与反推并行：** 新增「DSH 视频分析／B分段（并行入口）」与「DSH 独立反推（与保存并行）」两个执行节点。入口切完后立刻返回VIDEO，独立反推节点使用反推资料继续处理，外面的标准SaveVideo同时获得视频并保存；输出目录、文件名前缀和编码格式完全由SaveVideo节点决定，插件不自行保存、不固定文件夹。临时分析目录在反推结束时清理，VIDEO缓冲区不依赖临时文件。刷新加载旧的完整视频→SaveVideo工作流时自动拆分连线：字符串接独立反推，VIDEO仍接SaveVideo，并为缺少的video1—video5保存分支复制现有SaveVideo设置；没有输出的VIDEO分支会被阻止。A仍不足32秒直接反推，新反推节点仅传递A成品，不重复请求。未连接SaveVideo的旧工作流与API调用保留原串行行为。

> **链路A使用前两个文本框。** 完整视频节点第一个框「本次用户要求」发送为用户输入，第二个框「系统提示词（原Skill正文）」发送为模型系统提示词；第二个框默认为空，可直接粘贴规则，也可右键转为输入连接文本节点。插件不再内置或加载爆款裂变 Skill。旧工作流若仅显示一个框，请重新添加完整视频节点。原有视频预处理、CPU声音工具、重试及任务清理保留。下方旧版本中的内置爆款裂变说明已不适用。

# ComfyUI-DSH-Bridge 免安装版（Windows x64）

**0.8.7 CodeZ 接入**：两个独立 Key 视频节点的「接口协议」新增 `codez`，面板连接设置也提供 CodeZ 选项。当前使用 OpenAI Responses 协议（zdjapi域名保留Chat Completions）；Base URL（所选线路的 `/v1` 地址）、Key 和模型均由用户填写，不自动替换地址、Key、模型或代理设置。CodeZ 使用自己的 Key，不能与其他平台通用；原有规则输入、视频处理和输出上限保持原样。

**0.8.5 内置台词转写模型**：Windows 便携包及云端源码包均携带 SenseVoiceSmall INT8 权重、词表、来源与许可证。完整视频节点的「本地SenseVoice模型目录」留空即可，默认使用插件自身 `models/sensevoice/`，移动安装目录后仍自动定位；不查找用户电脑的模型缓存，不在任务中下载模型。可选覆盖路径支持绝对路径或相对于插件的路径。语音运行库由 ComfyUI 环境安装 `requirements.txt` 提供。

**CPU 说话人分析**：agent 可调用 `diarize_speakers` 获取估计人数、每人时间段和声学音色指标，使用 CPU 按需加载，不增加节点接线。部署仅需普通 sherpa-onnx 和预置模型，详见 [说话人分析](docs/SPEAKER-ANALYSIS.md)。

**0.8.4 图片完整性修复**：完整视频节点将 DeepSeek 协议在文件上传失败后的 Base64 图片预算提高至128 MiB，禁用自动省略参考图；超限明确报错。同素材离线回退验证20张图片全部保留。Skill按用户要求仅删除“不编造材质或功效”一句，其他正文不变。

**0.8.3 完整视频反推专用路径**：使用 `examples/full_video_workflow.json` 和「DSH Agent 完整视频反推」。一次预处理概览、每秒4帧动作序列、切点四帧对照及本地音轨转写，首轮直接加载原版爆款裂变技能，保留 DSH agent 按需补看能力。配置、依赖及本地验证见 [专用说明](docs/VIDEO-PROMPT.md)。以下面板及帧阵列说明适用于旧节点；旧 ZIP 不包含本次更新，云端请使用重新生成的源码包。

0.8.3 增加声音补正：本地分析声音变化，对疑点提供口型与回应连续帧，并允许 agent 用 `analyze_voices` 局部复核。它模仿 Codex 当时的取证方法，不固定声音人数，不把音高变化直接当作换人；原版 Skill 保持不变。

基于 [sxxzwbl/ComfyUI-DSH-Bridge](https://github.com/sxxzwbl/ComfyUI-DSH-Bridge) 的本地改造版本。

**RunningHub 公开工作流请使用 0.7.2 的 [云端说明](docs/RUNNINGHUB.md) 和 `examples/runninghub_video_workflow.json`。** 新节点「DSH Agent 视频反推（独立 Key）」直接接收每位使用者的 API Key、地址和模型，不依赖右下角面板；云端节点默认 DeepSeek 官方 `deepseek-flash`，填官方 Key。云端源码包 `ComfyUI-DSH-Bridge-RunningHub-Source.zip` 需要平台先安装插件和对应系统的 Harness 运行时；尚未在 RunningHub 上架验收。

0.7.4 已安装用户提供的「爆款裂变」skill。节点已默认选择任务「爆款裂变」，也可导入 `examples/runninghub_viral_workflow.json`，输出该技能规定的完整中文提示词。原始文件位于 `vendor/skills/viral-variation/`，没有改写技能正文。工作流模型输出上限默认 32768，已跑通真实视频抽帧、双参考图、Harness 技能和 DeepSeek Flash；本地 agent 实测约 110 秒，尚未做 RunningHub 部署验收。

**安装一个 ComfyUI 插件，使用 Harness agent 分析视频和参考图并生成提示词。无需安装 DeepSeek Harness 桌面版，也无需单独安装 Node.js 或启动 3080 网页端。**

## 直接使用（Windows x64 免安装包）

1. 关闭 ComfyUI，把 `ComfyUI-DSH-Bridge-Windows-Portable.zip` 解压到 `ComfyUI/custom_nodes/`，得到 `custom_nodes/ComfyUI-DSH-Bridge/__init__.py`。避免多套一层目录。
2. 重启 ComfyUI。**无需运行 install.bat、pip 或首次启动下载。** 包内已经包含独立 Python、官方 SDK、本地 Harness 原生运行时及其依赖；Pillow、numpy、aiohttp 使用 ComfyUI 自带版本。
3. 点击右下角 **DSH → 连接设置**，选择 **APIMart / GPT 6.1 sol**，填写自己的 APIMart API Key 并保存。默认模型 ID 为 `gpt-6.1-sol`。可点击「重连」检查本地运行时，握手不调用模型。
4. 把 `examples/video_reverse_workflow.json` 拖入 ComfyUI，在加载视频节点选择自己的视频，运行工作流。提示词保存到 `output/DSH/`。

适用 Windows x64、Python 3.10+、支持 V3 / VIDEO 类型的近期 ComfyUI。该免安装包包含 Windows 原生二进制，不适用于 Linux、macOS 或 Windows ARM64。

插件启动和本地运行时不依赖下载；视频分析仍通过模型 API 联网调用并计费，需要有效的 API Key。密钥保存在 ComfyUI 用户数据目录，不进入工作流或状态接口。APIMart 可选环境变量：`APIMART_API_KEY`、`OPENAI_API_KEY`；通用变量为 `DSH_BRIDGE_API_KEY`。已保存的 Key 优先于环境变量。

升级时先移走旧插件文件夹，再解压本免安装包；保留 `ComfyUI/user/default/dsh_bridge/` 可继续使用原设置和会话。GitHub 上游仓库仍是原版，不能用上游源码替代此完整二进制包。

## 使用

```text
加载视频（VIDEO） → DSH 帧阵列拼图 → 帧阵列图 → DSH 提示词引擎 → 提示词文本
                                   时间轴 ───→ 帧阵列时间轴
加载参考图 ─────────────────────────────────→ 参考图
```

节点保留「视频复刻、人物替换、服装替换、动作迁移、风格迁移、图像编辑指令」和自动判断。第一版沿用原项目 MiniMax H3 输出规范：英文提示词，中文分析。原有输出槽是「提示词」「状态」，分析和图片映射在面板里查看。详细接线见 [examples/README.md](examples/README.md)。

通过面板继续追问或基于上一版修改。同一会话可以接着讨论。不同任务请用新会话名，防止素材相互影响。「停止」会关闭本插件当前运行时；下一轮自动重启。连接错误、单次请求超时、限流及服务端临时错误会在同一模型步骤内最多自动重试3次，依次等待5秒、15秒、30秒；保留已完成的工具结果，不重跑整段视频。鉴权、参数、额度或上下文错误不重试。停止或任务总超时会中止等待。

## 数据与技能

完整视频节点内置 **Token速度监视**：显示每次请求和全任务平均 tok/s、输出 token、首内容等待、耗时与失败次数，并持久保存统计。刷新工作流后可恢复最近记录。节点“请求token用量”默认开启；接口未返回用量时只显示耗时，不估算速度。口径和记录位置见 [docs/TOKEN-SPEED.md](docs/TOKEN-SPEED.md)。

所有设置、媒体、会话和 Harness home 都在 `ComfyUI/user/default/dsh_bridge/`。插件不会扫描或复用桌面版的 `~/.dsh`。卸载插件时默认保留这些数据。

内置技能首次运行会复制到 `.../dsh_bridge/harness/skills/`。可以修改那里或增加自己的 SKILL.md；已有文件不会被自动覆盖。修改规则后新建会话。未提供音轨时只能分析画面，不会自动识别对白。当前采用均匀抽帧拼图，不包含 agent 动态补抽帧功能。

0.4.0 默认使用 **APIMart / OpenAI Chat Completions**：供应商 ID `apimart`，Base URL `https://api.apimart.ai/v1`，模型 ID `gpt-6.1-sol`，实际请求 `/v1/chat/completions`。采用 Bearer 鉴权、流式回复、`image_url` 图片和 `tool_calls` 技能调用。具体设置与验证范围见 [docs/APIMART.md](docs/APIMART.md)。

面板也保留 DeepSeek 官方预设（DeepSeek Messages 协议、`https://api.deepseek.com/anthropic`、`deepseek-flash`、`DEEPSEEK_API_KEY`）。自定义中转可选择两种协议。实际服务与模型需要同时支持图片、流式回复和工具调用；本地模拟通过不能证明中转端的这些能力。切换协议、供应商、模型或地址后使用独立上下文。旧版配置会保留原连接，请主动选择 APIMart 预设并保存。

## 检查与开发

```powershell
& '你的ComfyUI的python.exe' scripts/check_standalone.py
& '你的ComfyUI的python.exe' scripts/check_standalone.py --handshake
```

SDK/runtime 固定为 `0.2.2rc2`，自带 Python 3.12.10。ComfyUI 通过标准输入输出调用包内独立 Python 工作进程，工作进程再调用官方 SDK，避免修改 ComfyUI 的 Python 依赖。不启动额外监听端口。第三方许可证保留在 `vendor/windows-x64/python/LICENSE.txt` 和各包的 `.dist-info/licenses/` 中。

开发方案比较见 [docs/STANDALONE.md](docs/STANDALONE.md)，原始项目说明保存在 [docs/README.upstream.md](docs/README.upstream.md)。该改造保留原 MIT LICENSE；SDK 及随附运行时的第三方许可证以官方包内声明为准。

开发验证方法见 [tests/README.md](tests/README.md)。本版已在 Windows x64 / Python 3.12 验证真实 SDK、ComfyUI V3 schema 与合成视频链路；模型接口使用本地模拟响应，尚未验证真实 API 的视频分析质量。
