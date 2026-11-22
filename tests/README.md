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
