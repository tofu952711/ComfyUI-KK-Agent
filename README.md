# ComfyUI KK Agent 视频反推

分析原视频和参考图，按自定义规则生成视频提示词，支持 AI 分段和视频保存。

## 安装

1. 从 [Releases](https://github.com/tofu952711/ComfyUI-KK-Agent/releases/latest) 下载 **Windows x64 完整 ZIP**。
2. 解压到 `ComfyUI/custom_nodes/`，确保目录为 `custom_nodes/ComfyUI-DSH-Bridge/__init__.py`。
3. 重启 ComfyUI 并刷新浏览器，搜索 **KK agent 视频反推**，或导入 [并行工作流示例](examples/parallel_video_workflow.json)。

完整包包含 Windows 运行时、FFmpeg/FFprobe、SenseVoice 和说话人模型。若提示缺少 `sherpa-onnx`，使用 ComfyUI 的 Python 安装 `requirements.txt`。仓库源码不包含大体积运行时和模型，直接下载源码不能替代完整包。

## 使用

- 连接原视频，可选连接 `image1—image10` 参考图，并在「本次用户要求」说明各图用途。
- 填写自己的 **API Key、Base URL、模型和接口协议**。模型须支持图片、流式回复和工具调用，详见 [接口配置](docs/APIMART.md)。
- **不足 32 秒**：填写「系统提示词（原Skill正文）」，直接生成提示词，不输出视频。
- **32—60 秒**：分别填写「链路B：分段规定」和「链路B：反推提示词规定」。AI 先实际裁出 2—5 段视频，再按实际段数并发反推，经主 AI 复核及局部修正后按段号汇总提示词。
- 超过 60 秒请先裁短。规则框默认留空，均可右键转为输入连接外部文本节点。

并行工作流接线：

```text
加载视频 → KK agent 视频反推 ─ video1—video5 → SaveVideo
                         └ 反推资料 → DSH 独立反推 → 提示词
```

SaveVideo 决定保存目录、文件名前缀和编码格式；「保留音轨」控制分段成品是否带原声。完整接线及 API 示例见 [示例说明](examples/README.md)。B 链路会先生成共用设定，再由各段独立智能体反推，最后由主 AI 复核跨段一致性和对白时长，无需重新接线；详见 [并发反推与片尾抽帧容错](docs/B-PARALLEL-REVERSE.md)。并发会重复发送共用规则和参考图，费用及速度受接口限制影响。

## 常用设置

| 设置 | 用法 |
| --- | --- |
| 思考等级 | 默认 `high`，可选 `medium`、`low`、`auto`；`auto` 使用接口默认值 |
| 模型输出上限 | 默认 `32768`，按接口能力调整 |
| 超时 | 默认 `900` 秒 |
| 本地 SenseVoice 模型目录 | 完整包留空即可；也支持相对路径或绝对路径 |
| 请求 token 用量 | 默认开启；接口不支持时可关闭，详见 [速度统计](docs/TOKEN-SPEED.md) |

API 调用需要联网并产生所用服务的费用。节点内的 **Key 和规则会随工作流保存，分享前请清空**。完整包不包含个人工作流或真实 Key。

更多用法：[节点与排错](docs/VIDEO-PROMPT.md) · [规则填写](docs/EXTERNAL-RULES.md) · [视频分段](docs/VIDEO-SEGMENTS.md) · [CPU 说话人分析](docs/SPEAKER-ANALYSIS.md) · [云端部署](docs/RUNNINGHUB.md)

基于 [sxxzwbl/ComfyUI-DSH-Bridge](https://github.com/sxxzwbl/ComfyUI-DSH-Bridge)，保留 [MIT 许可证](LICENSE) 与第三方许可证。插件附带的 14 套 Skill 保留在 `vendor/skills/`；视频反推节点使用你填写的规则，不自动加载内置创作 Skill。
