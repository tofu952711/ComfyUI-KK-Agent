# 示例工作流

| 文件 | 用途 |
| --- | --- |
| [parallel_video_workflow.json](parallel_video_workflow.json) | 推荐在界面导入：分段视频保存与独立反推并行 |
| [parallel_video_api.json](parallel_video_api.json) | 并行流程的 API 格式 |
| [full_video_workflow.json](full_video_workflow.json) | 完整视频节点的串行流程 |
| [full_video_api.json](full_video_api.json) | 串行流程的 API 格式 |

导入后替换视频和参考图，填写自己的 API Key、接口地址、模型及协议。参考图为可选项，用途由本次用户要求说明。

不足 32 秒填写 A 的系统提示词；32—60 秒分别填写 B 分段规定和 B 反推规定。示例连接的独立文本节点规则为空，需要自行填写正文。规则框也支持直接填写或右键转为输入。

并行流程中，`video1—video5` 接 SaveVideo（中间可接人脸打码），「反推资料」接 DSH 独立反推，后者输出提示词。SaveVideo 控制目录、前缀与格式；A 从 video1 输出未分段原视频，video2—video5 不执行；B 输出实际分段，未使用的视频分支不执行。A/B 的反推均可与打码/保存并行。

「保留音轨」控制 B 分段成品的音轨；本地 SenseVoice 模型目录在完整包中可留空。若导入后提示缺少 SaveText 等文本保存节点，可安装对应节点或换成自己已有的文本显示／保存节点。

分享工作流前清空 Key 和不希望公开的规则。详细设置见 [使用说明](../docs/VIDEO-PROMPT.md)。
