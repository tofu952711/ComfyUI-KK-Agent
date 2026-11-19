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
