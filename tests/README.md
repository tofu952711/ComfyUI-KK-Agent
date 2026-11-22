# 开发检查

在具备插件依赖的 Python 环境运行选定测试；模型接口使用本地模拟服务，不调用付费模型。

```bash
python -m pytest -c tests/pytest.ini --confcutdir tests tests/test_standalone.py tests/test_apimart.py tests/test_workflow.py -q
node tests/check_video_stage_graph.mjs
node tests/check_full_video_widgets.mjs
node --test tests/request_retry.test.mjs
```

真实 ComfyUI 类型与合成视频链路检查：

```bash
python tests/check_comfy.py --comfy-root <ComfyUI目录>
```

源码仓库不含 Windows 原生运行时和模型，涉及真实 Harness 或语音分析的测试需先准备完整运行环境。测试只验证相应代码行为，不代表远端模型质量或云端部署通过。

音频绑定及B分段表达计划的回归检查：

```bash
python -m pytest -c tests/pytest.ini --confcutdir tests tests/test_audio_bindings.py tests/test_b_expression_plan.py tests/test_b_parallel_reverse.py -q
python tests/check_a_stage_scheduler.py --comfy-root <ComfyUI目录> --file-like --audio-bindings
python tests/check_stage_scheduler.py --comfy-root <ComfyUI目录> --review-linked --custom-review-ai --audio-bindings
```

检查实际请求中的音频编号绑定、无音频内容发送、各子任务分工、节点输出上限传递、正文分隔，以及独立审核与并行视频保存。音频输入只检测有无，不运行参考音频分析。

2026-11-23 的 A 审核、30 秒参考视频、取消与同步节点并发检查：

```bash
python -m pytest -c tests/pytest.ini --confcutdir tests tests/test_a_review.py tests/test_b_review.py tests/test_review_ai.py tests/test_cancellation.py tests/test_audio_bindings.py tests/test_b_expression_plan.py tests/test_parallel_video.py -q
python tests/check_a_reference.py --comfy-root <ComfyUI目录>
python tests/check_a_stage_scheduler.py --comfy-root <ComfyUI目录> --file-like --audio-bindings
python tests/check_sync_concurrency.py --comfy-root <ComfyUI目录> --chain B
```

上述单元回归共 77 项通过。A 参考视频检查使用 31.5 秒合成原片，确认 31.4 秒尾帧仍送入反推和审核，而参考输出不超过 30 秒；含音频的 29.97 fps 视频也验证此上限。实际 ComfyUI 调度使用本地模拟接口验证 A 反推、审核、B 子任务、自定义审核及视频保存；不调用付费云端模型。取消测试只终止其自行创建的进程。
