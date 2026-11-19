# APIMart 连接（0.4.0）

在 ComfyUI 右下角打开 **DSH → 连接设置**，选择 **APIMart / GPT 6.1 sol**。填写自己的 APIMart API Key，保存后即可运行示例工作流。无需安装本地大模型；Harness agent 在本地运行，模型推理由 APIMart 中转。

| 设置 | 值 |
| --- | --- |
| 接口协议 | OpenAI Chat Completions |
| 供应商 ID | `apimart` |
| Base URL | `https://api.apimart.ai/v1` |
| 模型 ID | `gpt-6.1-sol`（用户确认的 API ID） |
| API Key | 用户自己的 APIMart Key |

Base URL 不必带 `/chat/completions`；填完整地址也会自动移除该后缀。代理默认为空，需要时填自己的 HTTP 代理。旧版设置不会强制改为新预设，升级后请手动选择并保存。

保存后输入框清空，显示「密钥已保存；留空保留」。密钥存于 ComfyUI 用户数据目录的 `dsh_bridge/config.json`，不会写进工作流、状态接口或插件发行包。需要时可改用 `APIMART_API_KEY` / `OPENAI_API_KEY` / `DSH_BRIDGE_API_KEY` 环境变量；已保存的密钥优先。不要把含 Key 的配置文件分享出去。

## 请求方式

依据 [APIMart Chat Completions 文档](https://docs.apimart.ai/cn/api-reference/texts/general/chat-completions)，插件使用 `POST https://api.apimart.ai/v1/chat/completions`、`Authorization: Bearer ...`、`model`、`messages`、`max_tokens` 和 `stream: true`。

Harness 使用运行时内置的 OpenAI 适配器，把视频拼图/参考图编码为 `image_url` 数据 URL，把技能调用映射为流式 `tool_calls`，执行本地技能后以 `role: tool` 回传结果。没有上传原始视频文件，也不识别视频音轨。发送给接口的是抽帧图片、任务要求、技能说明和该会话的上下文。

文档所查页面主要描述文本消息，未充分列明图片和工具字段。`gpt-6.1-sol` 来自用户确认；本地适配按 OpenAI 常用的图片和工具格式实现。**尚未使用真实 Key 请求 APIMart，因此不能据此保证该中转模型支持图片和工具。** 如果真实接口拒绝 `image_url`、`tools` 或 `tool_calls`，需要确认该模型通道是否开放这些能力。

## 已验证范围

本地模拟服务验证实际 Harness 发送的请求路径、模型 ID、Bearer 鉴权、图片解码、SSE 回复、分片工具参数、真实 `video-replica` 技能读取和会话恢复。连接错误、单次请求超时、限流及服务端临时错误会在同一模型步骤内最多自动重试3次，依次等待5秒、15秒、30秒；保留已完成的工具结果，不重跑整段视频。鉴权、参数、额度或上下文错误不重试。停止或任务总超时会中止等待。点击「重连」只验证本地运行时，不代表 API Key 或模型连接验证成功。

切换协议、供应商、模型或 Base URL 后会使用独立模型上下文；原设置和会话数据仍保留。切换服务时请填写相应服务的 Key，预设切换不会自动清除已保存的 Key。
