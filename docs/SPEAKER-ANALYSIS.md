# 说话人分析：CPU

现有 VIDEO 工作流通过 MCP 工具 `diarize_speakers` 获取估计人数、每人发言时间及声学音色指标，不增加必填节点输入。工具仅使用 CPU，agent 调用时才加载模型，同一 MCP 进程复用模型；结果写入本任务 `media-analysis/speaker_evidence.json`，进程结束释放模型。

## 部署

在 ComfyUI 使用的 Python 环境中执行：

```bash
python -m pip install -r requirements.txt
python scripts/setup_speaker_models.py
```

使用普通 `sherpa-onnx`，无需显卡、CUDA、cuDNN 或额外的 GPU 包。任务运行时不安装或更新依赖。可选执行 `python scripts/setup_speaker_runtime.py` 检查语音运行库；该脚本仅检查，不安装、不联网、不检测显卡。

下载脚本校验 SHA256，准备两个 FP32 权重，合计约34.3 MB：

- `models/speaker-diarization/segmentation.onnx`：pyannote segmentation 3.0。
- `models/speaker-diarization/speaker_embedding.onnx`：中文 CAM++。

模型只在部署时下载；工作流不下载模型、不调用音频付费 API。完整发行包包含已准备的权重及来源、许可证；仓库源码不含权重。可在启动 ComfyUI 前设置 `DSH_BRIDGE_SPEAKER_MODEL_DIR` 指定模型目录，插件会将该路径显式传入 MCP 工具进程。

后端固定为 `cpu`，无需设置后端环境变量。缺少运行库或权重时明确返回错误，不将旧声学候选冒称为说话人分析结果。

## agent 调用

```json
{"name":"diarize_speakers","arguments":{"num_speakers":0,"threshold":0.5}}
```

`num_speakers=0` 自动估计人数，阈值越小通常分出越多人。只有已知人数才填写正整数，指定人数得到的是约束聚类，不是独立验证。返回人数、按首次发言编号的 `speaker_0` 等标签、原视频时间轴上的发言区间、各人的代表时间段、音高中位数与范围、频谱质心及高频能量比例。不将 ASR 粗略窗口硬分配给某个人。

音色统计只使用不与其他说话人重叠的音段；音高可能存在倍频/半频误差。频谱指标受录音设备、配乐、压缩和发音影响，不能单靠这些指标推断性别年龄或主观音色标签。声纹标签仅在本片内有效，人数仍是模型估计；短句、抢话和变声需复核。

预处理继续运行轻量声学分析；判断人数或区分多条声线时，agent 可按提示调用 `diarize_speakers`。不改变反推 Skill。


可选音频接口：`audio1`、`audio2`、`audio3`。A/B 两条链路只检测哪些接口实际接入，并向模型说明“音频1绑定模特1、音频2绑定模特2、音频3绑定模特3”。只传递已接入的绑定关系，编号不顺延、不补齐缺失输入，不自动推断图片编号或新增人物。外接音频不解码、不转写、不做声纹、音色、年龄或性别分析，也不上传音频内容；原视频已有的音轨预处理及导出音轨设置保持原有行为。B分段、共用设定、逐段反推和最终审核均会收到相同绑定资料。无音频接入时按原流程执行。
