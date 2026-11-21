"""Full VIDEO input to Harness with local analysis tools."""
from __future__ import annotations
import asyncio
import hashlib
import json
from pathlib import Path
import time
from comfy_api.latest import io
from ..dsh_bridge.workflow import workflow_bridge
from ..dsh_bridge.media_workflow import configure_media_config, evidence
from ..dsh_bridge.video_preparation import prepare_video, prepared_images, prepared_evidence_text
from ..dsh_bridge.images import tensor_to_base64
from ..dsh_bridge.media_tools import MediaTools
from ..dsh_bridge.duration_routing import route_duration
from ..dsh_bridge.b_review import REVIEW_RULES


class DSH_FullVideoAgent(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DSH_FullVideoAgent", display_name="DSH Agent 完整视频反推", category="DSH Bridge",
            description="只按视频实际时长选择独立链路：不足32秒进入A，使用前两个文本框直接反推；32至60秒进入B，AI按B分段规定调用工具实际裁切，再独立使用B反推规定生成提示词。两阶段均携带共用素材资料。超过60秒报错。支持最多五个分段VIDEO输出。",
            hidden=[io.Hidden.unique_id],
            inputs=[io.Video.Input("video", display_name="原视频"),
                    *[io.Image.Input(f"image{index}", optional=True, display_name=f"image{index}",
                                     tooltip=f"通用参考图{index}，用途由本次用户要求和系统提示词指定；可不连接。")
                      for index in range(1, 11)],
                    io.String.Input("api_key", default="", display_name="API Key"),
                    io.String.Input("base_url", default="https://api.deepseek.com/anthropic"),
                    io.String.Input("model", default="deepseek-flash"),
                    io.String.Input("requirement", multiline=True, default="按系统提示词分析原视频；参考图用途在此说明。",
                                    display_name="本次用户要求", tooltip="第一个文本框：本次用户输入。系统提示词请填在第二个文本框。"),
                    io.Int.Input("timeout_s", default=900, min=30, max=7200),
                    io.Int.Input("max_tokens", default=32768, min=256, max=65536),
                    io.String.Input("asr_model_dir", optional=True, default="", display_name="本地SenseVoice模型目录",
                                    tooltip="留空使用插件自带 models/sensevoice；相对路径从插件目录解析。无需单独下载模型。"),
                    io.Combo.Input("api_protocol", optional=True, options=["deepseek-messages", "openai-completions", "codez"],
                                   default="deepseek-messages", display_name="接口协议",
                                   tooltip="codez 使用 OpenAI Responses 协议并适配思考等级；zdjapi 地址保留原 Chat Completions 兼容；地址、CodeZ Key 和模型均由你填写，不会自动替换。Base URL 请填所选线路的 /v1 地址。"),
                    # ComfyUI groups required widgets before optional widgets.
                    # Append to the optional group to preserve existing saved indices;
                    # execute still requires nonempty system instructions.
                    io.String.Input("rules_text", optional=True, multiline=True, default="", lazy=True, display_name="系统提示词（原Skill正文）",
                                    placeholder="在此粘贴系统提示词，例如原 SKILL.md 正文；也可转为输入连接文本节点。",
                                    tooltip="第二个文本框：作为模型系统提示词发送。插件不再内置爆款裂变；右键转为输入后可连接外部文本节点。"),
                    io.Boolean.Input("keep_audio", optional=True, default=True, display_name="保留音轨",
                                     tooltip="控制链路B分段工具是否保留原音轨。分流入口的链路A从video1直通原视频及其音轨，导出音频由下游节点控制。"),
                    io.String.Input("segment_rules_text", optional=True, multiline=True, default="", lazy=True,
                                    display_name="链路B：分段规定",
                                    placeholder="链路B：在此填写视频分段规定，AI将按此规定调用工具实际裁切。",
                                    tooltip="仅作为链路B分段阶段的系统规则。AI决定切点并调用工具输出2—5段视频；A不读取。支持连接外部文本节点。"),
                    io.String.Input("chain_b_reverse_rules_text", optional=True, multiline=True, default="", lazy=True,
                                    display_name="链路B：反推提示词规定",
                                    placeholder="链路B：在此填写分段完成后的反推提示词规定。",
                                    tooltip="仅作为链路B反推阶段的系统规则。工具实际裁切成功后，在独立会话中传递分段结果与共用素材；不使用A系统提示词。支持连接外部文本节点。"),
                    io.Combo.Input("reasoning_effort", optional=True, options=["high", "medium", "low", "auto"],
                                   default="high", display_name="思考等级",
                                   tooltip="high=高，medium=中，low=低；auto=接口默认，不指定等级。默认high，A反推、B分段与反推及工具续轮均使用本等级。所选模型与接口须支持该参数；接口拒绝时明确报错，不会悄悄降级。"),
                    io.Boolean.Input('stream_usage', optional=True, default=True, display_name='请求token用量',
                                     tooltip='开启后向Chat Completions接口发送stream_options.include_usage，用于计算tok/s。CodeZ Responses和DeepSeek Messages使用自身用量字段。接口不支持时可关闭；没有用量则不估算速度。'),
                    io.String.Input("chain_b_review_rules_text", optional=True, multiline=True, default=REVIEW_RULES, lazy=True,
                                    display_name="链路B：审核规定",
                                    placeholder="在此编辑B链路最终审核全文；也可右键转为输入连接文本节点。",
                                    tooltip="全部分段反推完成后，按此文本审核并修改。默认显示原审核全文，可自行修改检查项；请保留JSON返回格式说明。A不读取此字段。")],
            outputs=[io.String.Output(display_name="提示词"), io.String.Output(display_name="分析证据"), io.String.Output(display_name="状态"),
                     *[io.Video.Output(display_name=f"video{index}") for index in range(1, 6)]])

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    def check_lazy_status(cls, video, rules_text=None, segment_rules_text=None, chain_b_reverse_rules_text=None,
                          chain_b_review_rules_text=REVIEW_RULES, **kwargs):
        routing = route_duration(video.get_duration())
        if routing["chain"] == "A":
            return ["rules_text"] if rules_text is None else []
        return [name for name, value in (("segment_rules_text", segment_rules_text),
                ("chain_b_reverse_rules_text", chain_b_reverse_rules_text),
                ("chain_b_review_rules_text", chain_b_review_rules_text)) if value is None]

    @classmethod
    async def execute(cls, video, api_key, base_url, model, requirement,
                      timeout_s=900, max_tokens=32768, asr_model_dir="", _observer=None,
                      api_protocol="deepseek-messages", rules_text="", keep_audio=True, segment_rules_text="", reasoning_effort="high", stream_usage=True,
                      image1=None, image2=None, image3=None, image4=None, image5=None,
                      image6=None, image7=None, image8=None, image9=None, image10=None,
                      chain_b_reverse_rules_text="", chain_b_review_rules_text=REVIEW_RULES):
        if video is None:
            raise ValueError("请连接原视频，脚本需要检测时长后选择链路")
        # Dispatch happens before credentials, prompts, references or media staging.
        # Never round duration or inspect prompt wording to choose a chain.
        routing = route_duration(video.get_duration())
        print(f"[DSH] 视频{routing['duration_seconds']}秒 → 链路{routing['chain']}", flush=True)
        image_values = (image1, image2, image3, image4, image5, image6, image7, image8, image9, image10)
        if routing["chain"] == "B":
            return io.NodeOutput(*await asyncio.to_thread(
                cls.run_chain_b, video, routing, api_key, base_url, model, requirement,
                segment_rules_text, chain_b_reverse_rules_text, timeout_s, max_tokens,
                asr_model_dir, api_protocol, reasoning_effort, stream_usage, keep_audio,
                _observer, image_values, chain_b_review_rules_text))
        result = await asyncio.to_thread(cls.run_chain_a, video, routing,
            api_key, base_url, model, requirement, rules_text, timeout_s, max_tokens,
            asr_model_dir, api_protocol, reasoning_effort, stream_usage, _observer,
            image_values)
        return io.NodeOutput(*result)

    @classmethod
    def prepare_chain_media(cls, cfg, video, routing, asr_model_dir, image_values):
        """The default material bundle is identical for A and B."""
        output = configure_media_config(cfg, video, asr_model_dir)
        tools = MediaTools(output.parent / "source-video.mp4", output, Path(cfg["media_model_dir"]))
        tools._write_json("duration_policy.json", {**routing, "phase": "prepared"})
        slots = [index for index, image in enumerate(image_values, 1) if image is not None]
        refs = []
        for index in slots:
            image = image_values[index - 1]
            if len(image.shape) == 4 and image.shape[0] != 1:
                raise ValueError(f"image{index}只接收单张图片；请拆开图片批次后连接独立插口")
            refs.append(tensor_to_base64(image, max_side=1568))
        print(f"[DSH] 链路{routing['chain']}：正在本地预处理视频和音轨转写", flush=True)
        report, shots, transcript = prepare_video(output, Path(cfg["media_model_dir"]))
        media_text = prepared_evidence_text(report, shots, transcript, slots)
        # Both current and future chain requests receive this explicit bundle.
        cfg["video_media_evidence"] = media_text
        return output, report, slots, refs, prepared_images(output, report), media_text

    @classmethod
    def run_chain_b(cls, *args):
        from ..dsh_bridge.chain_b import run_chain_b
        return run_chain_b(cls, *args)

    @classmethod
    def run_chain_a(cls, video, routing, api_key, base_url, model, requirement,
                    rules_text, timeout_s, max_tokens, asr_model_dir, api_protocol,
                    reasoning_effort, stream_usage, observer, image_values):
        stages = cls.iter_chain_a(video, routing, api_key, base_url, model, requirement,
            rules_text, timeout_s, max_tokens, asr_model_dir, api_protocol,
            reasoning_effort, stream_usage, observer, image_values)
        try:
            next(stages)
            try:
                next(stages)
            except StopIteration as finished:
                return finished.value
            raise RuntimeError("链路A反推阶段未正确结束")
        finally:
            stages.close()

    @classmethod
    def iter_chain_a(cls, video, routing, api_key, base_url, model, requirement,
                     rules_text, timeout_s, max_tokens, asr_model_dir, api_protocol,
                     reasoning_effort, stream_usage, observer, image_values, *, publish_video=False):
        if not isinstance(rules_text, str) or not rules_text.strip():
            raise ValueError("请在第二个文本框「系统提示词（原Skill正文）」填写反推规则，或转为输入连接文本节点")
        from ..dsh_bridge.token_speed import SpeedRun
        from comfy_execution.graph_utils import ExecutionBlocker
        started = time.monotonic()
        with SpeedRun(getattr(cls.hidden, 'unique_id', None), model) as speed, workflow_bridge(
                api_key, base_url, model, timeout_s, api_protocol, max_tokens=max_tokens,
                reasoning_effort=reasoning_effort, stream_usage=stream_usage) as bridge:
            from ..dsh_bridge.paths import bridge_data_dir
            audit_dir = bridge_data_dir() / "request-audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            audit_file = audit_dir / f"{speed.run_id}.jsonl"
            bridge.cfg["_request_audit_file"] = str(audit_file)
            bridge.cfg.update({"_token_monitor": speed, "video_prompt_only": True,
                "video_exact_inputs": True, "video_system_prompt": rules_text,
                "video_user_prompt": requirement})
            output, report, slots, refs, sheets, media_text = cls.prepare_chain_media(
                bridge.cfg, video, routing, asr_model_dir, image_values)
            tools = MediaTools(output.parent / "source-video.mp4", output, Path(bridge.cfg["media_model_dir"]))
            tools._write_json("duration_policy.json", {**routing, "phase": "reverse"})
            if observer:
                observer("ready", bridge, output)
            preparation_finished = time.monotonic()
            progress = []
            def observe(event):
                progress.append({"event": event, "phase": "reverse",
                    "agent_elapsed_seconds": round(time.monotonic() - preparation_finished, 3)})
                if event in ("step/start", "assistant/message", "tool/call", "tool/result", "turn/end"):
                    print(f"[DSH] {progress[-1]['agent_elapsed_seconds']}s {event}", flush=True)
            # Literal textbox values and the common source evidence stay separate.
            prepared_record = {"stage": "prepared", "run_id": speed.run_id,
                "node_id": str(getattr(cls.hidden, "unique_id", "")), "chain": "A",
                "system_characters": len(rules_text),
                "system_sha256": hashlib.sha256(rules_text.encode("utf-8")).hexdigest(),
                "user_characters": len(requirement),
                "user_sha256": hashlib.sha256(requirement.encode("utf-8")).hexdigest(),
                "media_evidence_characters": len(media_text),
                "media_evidence_sha256": hashlib.sha256(media_text.encode("utf-8")).hexdigest(),
                "reference_slots": slots, "reference_images": len(refs),
                "video_sheet_images": len(sheets), "total_images": len(refs) + len(sheets),
                "frame_coverage": report.get("coverage", {})}
            audit_file.write_text(json.dumps(prepared_record, ensure_ascii=False) + "\n", encoding="utf-8")
            # Preparation has copied the source into this job's private workspace.
            # Only now release the original VIDEO to downstream consumers: their
            # decoding/seeking cannot race with staging a shared file-like source.
            video_outputs = (video, *[ExecutionBlocker(None) for _ in range(4)]) if publish_video else tuple(
                ExecutionBlocker(None) for _ in range(5))
            yield ("", json.dumps({"chain": "A", "chain_status": "prepared",
                   "video_outputs": {"count": 1 if publish_video else 0,
                                     "plan_origin": "chain_a_original_video", "split_required": False}}, ensure_ascii=False),
                   "链路A原视频已就绪；video1可直接处理或保存，提示词由独立反推节点输出", *video_outputs)
            speed.phase = 'reverse'
            before_agent = time.monotonic()
            answer = bridge.ask(bridge.session_id("full-video"), requirement + "\n\n" + media_text, refs + sheets,
                                timeout=timeout_s, on_progress=observe)
            agent_finished = time.monotonic()
            compliance = {"input_mode": "exact_two_textboxes_with_media_evidence", "review_turns": 0,
                "review_seconds": 0.0, "rules_characters": len(rules_text),
                "rules_sha256": hashlib.sha256(rules_text.encode("utf-8")).hexdigest(),
                "format_check": "not_requested", "semantic_check": "not_requested"}
            records = evidence(output)
            records["chain"] = "A"
            records["chain_status"] = "completed"
            records["request_audit_file"] = str(audit_file)
            records["reference_image_slots"] = slots
            records["media_input"] = {"prepared": True, "sent_to_ai": True,
                "text": media_text, "reference_images": len(refs), "video_sheet_images": len(sheets)}
            records["video_outputs"] = {"count": 0, "segments": [], "ai_plan_submitted": False,
                "plan_origin": "chain_a_no_output", "encoding_seconds": [],
                "storage": "none; no VIDEO output for chain A"}
            if publish_video:
                records["video_outputs"].update(count=1, plan_origin="chain_a_original_video",
                    split_required=False, storage="original VIDEO passed through video1; saving is handled by downstream nodes")
            records["output_compliance"] = compliance
            records["reasoning_effort"] = {"selected": reasoning_effort,
                "requested": None if reasoning_effort == "auto" else reasoning_effort}
            records["segment_corrections"] = 0
            records["segment_agent_tool_calls"] = []
            records["segment_usage"] = None
            records["agent_tool_calls"] = [e["data"]["name"] for e in answer["events"] if e.get("type") == "tool/call"]
            records["finish_reason"] = answer.get("finish_reason")
            records["usage"] = answer.get("usage")
            records['token_speed'] = {**speed.snapshot(), 'status': 'completed'}
            records["agent_progress"] = progress
            records["usage_by_round"] = [(e.get("data") or {}).get("usage") or {} for e in answer["events"]
                                         if e.get("type") == "assistant/message"]
            records["timings"] = {"before_agent_seconds": round(before_agent - started, 3),
                "agent_seconds": round(agent_finished - before_agent, 3),
                "output_review_seconds": 0.0,
                "preparation_seconds": round(preparation_finished - started, 3),
                "segment_planning_seconds": 0.0, "video_output_seconds": 0.0,
                "video_encoding_seconds": 0.0, "video_agent_overlap_seconds": 0,
                "total_seconds": round(time.monotonic() - started, 3)}
            status = "ok" if answer["text"].strip() else "未返回提示词"
            if observer:
                observer("finished", bridge, output)
            return (answer["text"], json.dumps(records, ensure_ascii=False, indent=2), status,
                    *video_outputs)
