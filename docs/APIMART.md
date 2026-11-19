# 接口配置

在视频节点中填写 API Key、Base URL、模型 ID 和接口协议。四项必须对应同一服务；模型需支持图片、流式回复和工具调用。

| 服务 | 接口协议 | Base URL | 模型示例 |
| --- | --- | --- | --- |
| DeepSeek 官方 | `deepseek-messages` | `https://api.deepseek.com/anthropic` | `deepseek-flash` |
| APIMart | `openai-completions` | `https://api.apimart.ai/v1` | `gpt-6.1-sol` |
| OpenAI 兼容中转 | `openai-completions` | 服务商提供的 `/v1` 地址 | 账户可用模型 |
| CodeZ | `codez` | 所选线路的 `/v1` 地址 | 账户可用模型 |

模型名称以服务商实际可用列表为准。CodeZ 使用 Responses 协议；zdjapi 域名保留 Chat Completions 兼容。选择协议不会自动替换地址、Key 或模型。不同服务的 Key 不能混用。

思考等级可选 `high`、`medium`、`low`、`auto`，默认 `high`。`auto` 不显式指定等级；接口不支持该参数时会报错。若接口拒绝 `stream_options.include_usage`，关闭节点的「请求token用量」。

## 面板设置

右下角 **DSH → 连接设置** 用于面板自身的连接，可选择预设或填写自定义服务。代理留空即可，需要时填写自己的 HTTP 代理。视频节点仍使用节点内单独填写的 Key、地址和模型。

面板保存的 Key 位于 ComfyUI 用户目录 `default/dsh_bridge/config.json`；保存后输入框清空，留空表示保留。也可使用 `APIMART_API_KEY`、`OPENAI_API_KEY` 或 `DSH_BRIDGE_API_KEY` 环境变量，已保存的 Key 优先。「重连」只检查本地运行时，不代表模型 API 鉴权成功。

## 连接异常

- 鉴权失败：检查服务商、Key 和模型是否匹配。
- 模型或参数不支持：按服务商要求调整模型、思考等级及用量开关。
- 连接、超时、限流及临时服务错误：插件最多重试 3 次，间隔 5、15、30 秒；停止或总超时会中止重试。鉴权、参数和额度错误不重试。

分享工作流前清空节点内 Key；不要分享面板的 `config.json`。
