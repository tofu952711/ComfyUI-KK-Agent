# Token 速度统计

视频节点按每次模型请求记录输出用量、等待时间、耗时和结束状态，重试也单独计入。

- **请求平均 tok/s**：已报告的输出 token 总数除以对应请求耗时总和，含首内容等待，不含本地预处理与请求间工具耗时。
- **有效 tok/s**：输出 token 总数除以任务总用时，含预处理、工具和重试；用量不完整时留空。
- **首内容等待**：请求开始至首个可观测文字、思考文字或工具参数内容的时间。
- **输出 token**：接口报告并经 SDK 规范化的 `outputTokens`，不额外叠加推理 token。

接口通常在请求结束时才报告用量。运行中显示耗时和字符数；不把字符数当作 token。没有用量时显示无法计算。

「请求token用量」默认开启；Chat Completions 使用 `stream_options.include_usage`，CodeZ Responses 和 DeepSeek Messages 使用各自的用量字段。接口拒绝该参数时可关闭，用量缺失不影响耗时记录。

数据保存在 ComfyUI 用户目录 `default/dsh_bridge/token-speed/`。每个节点保存最新 JSON，`history.jsonl` 达 5 MiB 时轮换保留上一份；刷新可恢复最近统计。记录不含 Key、素材或提示词正文。

「分析证据」输出包含 `token_speed`；本地接口 `GET /dsh_bridge/token_speed?node_id=<节点ID>` 可读取最近统计。
