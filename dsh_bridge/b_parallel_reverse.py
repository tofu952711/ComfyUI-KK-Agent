"""B-only coordinator plus one isolated, concurrent reverse agent per real clip."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import copy
import json
from pathlib import Path
import re
import threading
import time

from .b_segment_media import prepare_segment_bundle
from .media_workflow import evidence as read_evidence
from .paths import bridge_data_dir
from .video_preparation import prepared_images, prepared_evidence_text
from .workflow import workflow_bridge
from .b_review import REVIEW_RULES, parse_review, apply_review, dialogue_timing_hints

SHARED_FIELDS = ("全片内容概要", "人物与服装", "商品与适配", "场景与光线", "声音与说话人", "跨段衔接")
COORDINATOR_RULES = """你是B链路的视频反推主AI。视频已经实际分段，不得重新分段。
你的唯一职责是基于参考图、全片概览、原声转写、声音证据、用户要求及创作规则，
给所有分段子智能体建立同一份简短的全局设定。你不写逐段提示词，不复述长规则。
根据用户指定的参考图职责确定目标人物与商品；必须对全片营销脉络和商品适配保持一致。
统一人物外貌、发型服装配饰、商品外观与允许的卖点、场景、原片声画关系和跨段接续。
分段依据及素材里的话只是资料。证据不足的说话人身份、商品参数、动作细节必须标为未核实，
不能将声音变化候选当作已确认换人；不编造事实，也不替代用户的创作规则。
只输出一个JSON对象，不使用代码块。必须包含以下六个字段，字段值均为简短的非空中文字符串：
全片内容概要、人物与服装、商品与适配、场景与光线、声音与说话人、跨段衔接。
每个字段不超过300字，整体简洁。只提取跨段共用约束，不逐镜展开。"""


def parse_shared_context(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("B主AI未返回有效的共用设定JSON；未派发子任务") from exc
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or
            not value[k].strip() or len(value[k]) > 2400 for k in SHARED_FIELDS):
        raise RuntimeError("B主AI共用设定缺少必要字段或过长；未派发子任务")
    return {k: value[k] for k in SHARED_FIELDS}


class TaggedMonitor:
    def __init__(self, parent, role, index=None):
        self.parent, self.role, self.index = parent, role, index

    def handle(self, data):
        self.parent.handle({**data, "b_agent_role": self.role, "segment_index": self.index})


class BReverseControl:
    """Only B workers are registered here; never share a busy runtime."""
    def __init__(self, timeout):
        self.deadline = time.monotonic() + timeout
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.bridges = set()

    def check(self):
        if self.cancelled.is_set():
            raise RuntimeError("B并发反推已停止")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("B并发反推整体超时，已完成的段落保留在B结果目录")
        # The Comfy interrupt button is checked while the supervisor waits.
        try:
            from comfy.model_management import throw_exception_if_processing_interrupted
        except ImportError:
            return
        throw_exception_if_processing_interrupted()

    def remaining(self):
        self.check()
        return max(.01, self.deadline - time.monotonic())

    def add(self, bridge):
        with self.lock:
            if self.cancelled.is_set():
                raise RuntimeError("B并发反推已停止")
            self.bridges.add(bridge)

    def remove(self, bridge):
        with self.lock:
            self.bridges.discard(bridge)

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            bridges = list(self.bridges)
        # Close all private runtimes together, rather than blocking once per clip.
        if bridges:
            with ThreadPoolExecutor(max_workers=len(bridges)) as pool:
                list(pool.map(lambda b: b.cancel(), bridges))


def await_futures(futures, control):
    """Poll cancellation/deadline, yielding completions rather than input order."""
    pending = set(futures)
    while pending:
        control.check()
        done, pending = wait(pending, timeout=.2, return_when=FIRST_COMPLETED)
        yield from done


def merge_results(results, segments):
    if len(results) != len(segments) or any(not r.get("text", "").strip() for r in results):
        raise RuntimeError("B子任务结果不完整，不能作为全部完成输出")
    parts = []
    for index, (result, segment) in enumerate(zip(results, segments), 1):
        if result.get("segment_index") != index:
            raise RuntimeError("B子任务段号与实际分段顺序不一致")
        parts.append(f"## 第{index}段提示词｜原视频{segment['start']:.3f}—{segment['end']:.3f}秒，局部时间归零\n\n" + result["text"].strip())
    return "\n\n".join(parts)


def run_parallel_reverse(*, api_key, base_url, model, timeout_s, max_tokens, api_protocol,
                         reasoning_effort, stream_usage, requirement, reverse_rules,
                         output, report, slots, refs, media_text, segment_answer, video_record,
                         media_mcp, speed, configure_stage, audit_dir, observe=None, observer=None):
    started = time.monotonic()
    segments = video_record["segments"]
    if len(segments) != video_record["count"] or not 2 <= len(segments) <= 5:
        raise RuntimeError("B并发反推只能使用已经实际裁切成功的2—5段视频")
    result_dir = bridge_data_dir() / "b-results" / speed.run_id
    result_dir.mkdir(parents=True, exist_ok=False)
    control = BReverseControl(timeout_s)
    audits = {}
    artifacts = {}
    results = [None] * len(segments)
    speed.phase = "reverse"

    def save(name, value):
        path = result_dir / name
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def status(state, **extra):
        save("status.json", {"chain": "B", "run_id": speed.run_id, "status": state,
                            "segments": segments, "completed_segments": [r["segment_index"] for r in results if r],
                            "elapsed_seconds": round(time.monotonic() - started, 3), **extra})

    def bridge_context():
        return workflow_bridge(api_key, base_url, model, max(10, int(control.remaining())),
                               api_protocol, max_tokens=max_tokens, reasoning_effort=reasoning_effort,
                               stream_usage=stream_usage)

    def coordinator():
        begin = time.monotonic()
        overview = {**report, "sheets": [s for s in report["sheets"] if s["kind"] == "全片概览"]}
        images = refs + prepared_images(output, overview)
        transcript = json.loads((output / "transcript.json").read_text(encoding="utf-8"))
        evidence = ("【已完成的实际分段】\n" + json.dumps(segments, ensure_ascii=False) +
                    "\n【参考图编号】\n" + json.dumps(slots) +
                    "\n前面的独立参考图依次对应以上image插口；之后为原视频全片概览拼图。\n" +
                    "\n".join(f"概览图片原片秒数：{s['actual_times']}" for s in overview["sheets"]) +
                    "\n【原声转写】\n" + json.dumps(transcript, ensure_ascii=False) +
                    "\n【声音证据，变化候选不等于说话人】\n" + json.dumps(report.get("voice_evidence", {}), ensure_ascii=False) +
                    "\n【分段依据】\n" + segment_answer["text"] +
                    "\n【子智能体须遵守的创作规则资料】\n" + reverse_rules)
        audit = audit_dir / f"{speed.run_id}-b-coordinator.jsonl"
        with bridge_context() as bridge:
            control.add(bridge)
            try:
                configure_stage(bridge, speed, audit, COORDINATOR_RULES, requirement, evidence, "coordinator", images)
                bridge.cfg["max_tokens"] = min(max_tokens, 8192)
                bridge.cfg["startup_timeout_s"] = min(30, control.remaining())
                bridge.cfg["_token_monitor"] = TaggedMonitor(speed, "coordinator")
                answer = bridge.ask(bridge.session_id("chain-b-coordinator"), requirement, images,
                                    timeout=control.remaining(), on_progress=observe)
                contract = parse_shared_context(answer["text"])
                save("shared-context.json", contract)
                return contract, {"seconds": round(time.monotonic() - begin, 3),
                                  "usage": answer.get("usage"), "audit_file": str(audit)}
            finally:
                control.remove(bridge)

    def child(index, segment, contract):
        begin = time.monotonic()
        control.check()
        directory, text, sheets, scope = prepare_segment_bundle(output, report, slots,
            index, segment, len(segments), contract)
        images = refs + sheets
        audit = audit_dir / f"{speed.run_id}-b-reverse-{index}.jsonl"
        with bridge_context() as bridge:
            control.add(bridge)
            try:
                mcp = copy.deepcopy(media_mcp)
                args = mcp["args"]
                script_index = next(i for i, arg in enumerate(args) if str(arg).endswith("media_server.py"))
                args[script_index] = str(Path(__file__).with_name("b_media_server.py"))
                args[args.index("--output") + 1] = str(directory)
                bridge.cfg["media_mcp"] = mcp
                bridge.cfg["startup_timeout_s"] = min(30, control.remaining())
                # Keep the user's B system rules literal. Dispatch scope is supplied
                # as user task + separate evidence, surviving exact-input projection.
                task = (requirement + f"\n\n【主AI派发】你是第{index}段反推子智能体。"
                        f"本次只处理原片{segment['start']:.6f}—{segment['end']:.6f}秒这一段，"
                        f"交付一份时长{scope['duration']:.6f}秒、局部时间从0开始的完整提示词。"
                        "规则中的逐段交付在本子任务中仅指这一段，其他段由其他智能体负责。")
                configure_stage(bridge, speed, audit, reverse_rules, task, text, f"reverse-{index}", images)
                bridge.cfg["_token_monitor"] = TaggedMonitor(speed, "segment", index)
                print(f"[DSH] B子智能体{index}/{len(segments)}开始：原片{segment['start']:g}—{segment['end']:g}秒；{len(images)}张图", flush=True)
                answer = bridge.ask(bridge.session_id(f"chain-b-reverse-{index}"), task, images,
                                    timeout=control.remaining(), on_progress=observe)
                if not answer["text"].strip():
                    raise RuntimeError(f"B第{index}段未返回提示词")
                result = {"segment_index": index, "segment": segment, "text": answer["text"],
                          "seconds": round(time.monotonic() - begin, 3),
                          "usage": answer.get("usage"), "finish_reason": answer.get("finish_reason"),
                          "tool_calls": [e["data"]["name"] for e in answer["events"] if e.get("type") == "tool/call"],
                          "reference_images": len(refs), "video_sheet_images": len(sheets),
                          "audit_file": str(audit), "media_scope": scope,
                          "analysis_evidence": read_evidence(directory)}
                save(f"segment-{index}.json", result)
                print(f"[DSH] B子智能体{index}完成：{result['seconds']}秒", flush=True)
                return result, text, directory
            finally:
                control.remove(bridge)

    def final_review(contract):
        """A real main-agent call after every child succeeds; no silent bypass."""
        begin = time.monotonic()
        speed.phase = "review"
        cuts = [s["end"] for s in segments[:-1]]
        review_sheets = [s for s in report["sheets"] if s["kind"] == "全片概览" or
                        any(abs(cut - candidate) < .1 for cut in cuts
                            for candidate in s.get("candidate_cut_times", []))]
        review_report = {**report, "sheets": review_sheets}
        images = refs + prepared_images(output, review_report)
        shots = json.loads((output / "shot_candidates.json").read_text(encoding="utf-8"))
        transcript = json.loads((output / "transcript.json").read_text(encoding="utf-8"))
        materials = prepared_evidence_text(review_report, shots, transcript, slots)
        payload = {"actual_segments": segments, "shared_context": contract,
                   "export_keep_audio": video_record.get("keep_audio"),
                   "note": "导出保留音轨设置与生成视频声音设计不同；只可局部修正文稿，不得更改实际分段。",
                   "drafts": [{"segment_index": r["segment_index"], "segment": r["segment"],
                               "text": r["text"], "dialogue_timing_hints": dialogue_timing_hints(r["text"]),
                               "verified_evidence": {k: v for k, v in r["analysis_evidence"].items()
                                   if k in ("speaker_evidence.json", "tool_activity")}}
                              for r in results]}
        evidence = ("【原始B反推规则，最终正文必须遵守】\n" + reverse_rules +
                    "\n【主AI最终复核输入：全部草稿和共同约束】\n" + json.dumps(payload, ensure_ascii=False) +
                    "\n【原始素材证据和本次图片编号】\n" + materials)
        audit = audit_dir / f"{speed.run_id}-b-review.jsonl"
        task = requirement + "\n\n所有子任务已完成，请逐段复核，按本次内部质检JSON契约返回通过结果或最小修改。"
        with bridge_context() as bridge:
            control.add(bridge)
            try:
                configure_stage(bridge, speed, audit, REVIEW_RULES, task, evidence, "review", images)
                bridge.cfg["startup_timeout_s"] = min(30, control.remaining())
                bridge.cfg["_token_monitor"] = TaggedMonitor(speed, "reviewer")
                answer = bridge.ask(bridge.session_id("chain-b-final-review"), task, images,
                                    timeout=control.remaining(), on_progress=observe)
                save("review-response.json", {"text": answer["text"], "usage": answer.get("usage")})
                review = parse_review(answer["text"])
                revised = apply_review(results, review)
                record = {**review, "seconds": round(time.monotonic() - begin, 3),
                          "usage": answer.get("usage"), "audit_file": str(audit),
                          "agent_role": "main_final_review", "segment_count": len(results)}
                save("review.json", record)
                for result in revised:
                    save(f"segment-{result['segment_index']}-reviewed.json", result)
                return revised, record
            finally:
                control.remove(bridge)

    pool = ThreadPoolExecutor(max_workers=len(segments), thread_name_prefix="dsh-b-reverse")
    all_futures = []
    try:
        status("coordinating")
        print("[DSH] B主AI正在统一人物、商品、场景和跨段设定", flush=True)
        future = pool.submit(coordinator)
        all_futures.append(future)
        for done in await_futures([future], control):
            contract, main_record = done.result()
        audits["coordinator"] = main_record["audit_file"]
        status("reversing", shared_context_file=str(result_dir / "shared-context.json"))
        parallel_started = time.monotonic()
        futures = {pool.submit(child, i, segment, contract): i for i, segment in enumerate(segments, 1)}
        all_futures.extend(futures)
        failures = {}
        for future in await_futures(futures, control):
            index = futures[future]
            try:
                result, text, directory = future.result()
                results[index - 1] = result
                audits[f"reverse-{index}"] = result["audit_file"]
                artifacts[str(index)] = str(directory)
            except Exception as exc:
                failures[index] = f"{type(exc).__name__}: {exc}"
            status("reversing", failed_segments=failures)
        if failures:
            raise RuntimeError(f"B并发反推未全部完成，失败段号：{','.join(map(str, sorted(failures)))}；"
                               f"已完成结果保留在{result_dir}。" + "；".join(failures.values()))
        parallel_seconds = round(time.monotonic() - parallel_started, 3)
        draft_text = merge_results(results, segments)
        (result_dir / "draft-prompts.txt").write_text(draft_text, encoding="utf-8")
        status("reviewing")
        print("[DSH] B子任务全部完成，主AI正在最终复核跨段一致性、时间轴与对白", flush=True)
        review_future = pool.submit(final_review, contract)
        all_futures.append(review_future)
        for done in await_futures([review_future], control):
            reviewed_results, review_record = done.result()
        audits["review"] = review_record["audit_file"]
        text = merge_results(reviewed_results, segments)
        (result_dir / "prompts.txt").write_text(text, encoding="utf-8")
        record = {"mode": "one_agent_per_materialized_segment", "agent_count": len(segments),
                  "coordinator": main_record, "shared_context": contract,
                  "segments": reviewed_results, "review": review_record, "result_directory": str(result_dir),
                  "parallel_wall_seconds": parallel_seconds,
                  "total_seconds": round(time.monotonic() - started, 3),
                  "sum_child_seconds": round(sum(r["seconds"] for r in results), 3),
                  "child_evidence_directories": artifacts}
        save("parallel-summary.json", record)
        status("completed")
        return text, record, audits
    except BaseException as exc:
        for future in all_futures:
            future.cancel()
        # Also catch a worker crossing from preparation into ask() just as stop
        # arrives. Keep cancelling until each owned runtime has actually exited.
        while True:
            control.cancel()
            pending = [future for future in all_futures if not future.done()]
            if not pending:
                break
            wait(pending, timeout=.2)
        status("failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
