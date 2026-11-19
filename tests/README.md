> **当前验证策略：** 不足32秒进入A（含31.95秒），32至60秒进入独立B占位。真实ComfyUI节点测试验证A只发送两框原文，B不调用A、API或素材处理且不读取第三框。下面旧分段测试说明不再代表节点入口行为。

> **当前接口：image1—image10 + video1—video5。** 图片均为可选的通用参考，含义由用户要求／系统提示词说明；未连接的编号不重排。保留原来的提示词、分析证据、状态三个输出，在后面增加五个VIDEO输出。AI需通过set_video_segments提交1—5段连续覆盖全片的秒数，节点才会实际裁切；没有提交方案时video1为完整原视频，其余口为空。分段视频包含原音轨，采用CPU H.264/AAC编码；输出存于VIDEO内存对象，任务临时目录清理后仍有效，需要长期保存请接SaveVideo。旧人物／商品连线迁移到image1／image2，文本控件顺序不变。

> **节点精简：仅保留「DSH Agent 完整视频反推」。** 已删除提示词引擎、帧阵列拼图、视频反推（独立 Key）的节点实现与注册，并移除对应旧示例。现有工作流请使用 full_video_workflow.json 或 full_video_api.json；本地与云端入口均只提供完整视频节点。下方历史文档提到的旧节点已不再提供。

> **当前行为：两个文本框。** 完整视频节点第一个框「本次用户要求」发送为用户输入，第二个框「系统提示词（原Skill正文）」发送为模型系统提示词；第二个框默认为空，可直接粘贴规则，也可右键转为输入连接文本节点。插件不再内置或加载爆款裂变 Skill。旧工作流若仅显示一个框，请重新添加完整视频节点。原有视频预处理、CPU声音工具、重试及任务清理保留。下方旧版本中的内置爆款裂变说明已不适用。

# 开发验证

`test_speaker_runtime.py` 验证CPU语音运行库检查：仅导入 sherpa-onnx、不安装、不联网、不检测显卡，缺依赖时提供明确安装指引。

`test_speaker_analysis.py` 验证默认及旧后端环境变量下均使用CPU、两套模型的CPU配置、首次发言编号、重叠段排除、原视频时间轴、按需加载、参数与模型变更后的缓存失效，以及真实MCP stdio调度。`test_video_preparation.py` 包含官方 Harness agent 调用 diarize_speakers 的本地模拟接口链路；模拟模型接口不调用付费服务。

0.8.4 的 `test_video_image_budget.py` 使用真实Harness与拒绝Files的本地接口，验证超过旧20 MiB预算的20张图全部送达、前两张参考图像素保留，以及超限时报错而非删图成稿。Skill来源检查允许用户指定的单句删除，其余字节保持原始文件内容。

0.8.3 的 `test_voice_analysis.py` 验证声学变化候选、同音高音量变化、静音和极短片段、局部原视频时间轴与缓存；`test_video_preparation.py` 验证官方 Harness 通过 MCP 实际调用 `analyze_voices`，不把候选数当人数，不产生性别标签。

0.8.2 的 `test_video_preparation.py` 另覆盖4fps密集采样、切点四帧对照的PTS、长视频覆盖上限与极短视频边界。原版Skill文件哈希、首请求加载及用户Key隔离保持验证。完整视频节点与重新解压的源码包均用同素材通过本地模拟模型链路；真实模型另有单次实测记录，不能用模拟耗时评价真实推理速度。

0.8.1 增加 `python -m pytest tests/test_video_preparation.py -q`：真实编码视频、切点候选、切点前后帧、准确seek、无音轨、同任务缓存、首请求加载完整Skill和图片，以及可选MCP补帧。均使用本地模型模拟接口。

`check_full_video.py --comfy-root <ComfyUI> --video <视频> --person <人物图> --product <商品图> --output <验证目录>` 会运行真实完整视频节点，把脱敏证据保存在指定目录，不读取真实API配置。该验证不评价真实模型质量。

使用 ComfyUI 的 Python 环境，另装测试依赖 `pytest`。普通插件运行无需 pytest。

```powershell
python -m pytest -c tests/pytest.ini --confcutdir tests tests/test_standalone.py tests/test_apimart.py tests/test_workflow.py tests/test_viral_skill.py -q
python tests/check_comfy.py --comfy-root 'ComfyUI根目录'
python tests/check_comfy.py --comfy-root 'ComfyUI根目录' --protocol deepseek-messages
```

集成测试使用真实官方 Harness SDK 和本机原生运行时，模型端替换为仅监听 127.0.0.1 的确定性 OpenAI Chat Completions / DeepSeek Messages 测试服务。覆盖图片实际传入、流式工具参数拼接、skill 工具读取、会话恢复、停止、超时、并发拒绝、设置验证和密钥脱敏；APIMart 路由另验证 Bearer、模型 ID、请求地址、401/429/500 只提交一次、旧配置迁移和切换模型后独立上下文。测试不会调用真实付费接口。

`check_comfy.py` 加载 ComfyUI 自己的 `comfy_api.latest`，检查节点 schema，创建合成 VIDEO 并执行抽帧与提示词节点；测试时使用临时数据目录。它验证节点接口和数据链路，不等同于用户整合包的完整界面启动验收，也不评价真实模型的反推质量。

本次环境：Windows x64，Python 3.12，SDK/runtime 0.2.2rc2；ComfyUI 源码提交 `9fa6bc5`。共 20 项测试，包含无 site-packages 主机测试，覆盖主机未安装 SDK / Pydantic 时调用包内独立环境；公开工作流补充显式 Key 必填、并发用户的密钥/上下文隔离、临时目录清理、官方 DeepSeek Messages 图片/技能链路、不会写入共享配置/历史和 Linux 运行时选择。爆款裂变验证原始文件 SHA256、中文路由、实际 Harness 技能读取；节点检查保留中文章节、Markdown 与空分析槽。另检查三个 V3 节点与合成视频链路；浏览器验证本地 APIMart / DeepSeek 预设切换、设置保存后密钥清空与面板布局。测试通过代表协议实现和插件链路通过；未做真实 APIMart、Linux 或 RunningHub 线上验收。

`test_request_retry.py` 使用真实Harness及本地模拟接口验证工具执行后连续三次503，按5/15/30秒等待并恢复，重试不重复执行工具；同时验证停止与总超时取消重试。`node --test tests/request_retry.test.mjs` 验证重试次数上限、错误筛选及取消。

并行裁切验证：test_parallel_video.py覆盖方案修正、模型失败退出、编码失败和无方案回退；check_comfy.py使用真实Harness、MCP和Comfy VIDEO对象，让模拟模型等待两段预览到达才输出最终文字，证明裁切发生在AI结束前，不消耗付费API。check_video_preview.mjs覆盖运行/方案版本隔离、临时播放地址、预览清理和不序列化控件。
