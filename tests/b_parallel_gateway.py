"""Local-only SSE gateway for real B coordinator/worker concurrency checks."""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIELDS = ("全片内容概要", "人物与服装", "商品与适配", "场景与光线", "声音与说话人", "跨段衔接")
SHARED = {key: f"统一设定：{key}" for key in FIELDS}


class BParallelGateway:
    def __init__(self, segments, protocol="openai-completions", fail_segment=None,
                 on_coordinator=None, fail_coordinator=False, review_response=None, child_texts=None):
        self.requests, self.paths, self.errors = [], [], []
        self.segment_requests, self.coordinator_requests, self.worker_requests = [], [], []
        self.worker_initial_images = {}
        self.review_requests = []
        self.finished_children = set()
        self.peak_children = 0
        self.active_children = 0
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(len(segments))
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    responses = protocol == "codez"
                    assert self.path == ("/v1/responses" if responses else "/v1/chat/completions")
                    with outer.lock:
                        outer.requests.append(body)
                        outer.paths.append(self.path)
                    system = body.get("instructions", "") if responses else next(
                        m["content"] for m in body["messages"] if m["role"] in ("system", "developer"))
                    messages = body["input"] if responses else body["messages"]
                    users = [m for m in messages if m.get("role") == "user"]
                    texts = [b["text"] for m in users for b in m["content"] if b["type"] in ("input_text", "text")]
                    images = [b for m in users for b in m["content"] if b["type"] in ("input_image", "image_url")]
                    task = texts[0]
                    match = re.search(r"你是第(\d+)段反推子智能体", task)
                    tools = body.get("tools", [])
                    names = [t["name"] if responses else t["function"]["name"] for t in tools]
                    has_output = any(m.get("type") == "function_call_output" or m.get("role") == "tool" for m in messages)
                    call = None
                    text = ""
                    if "所有子任务已完成，请逐段复核" in task:
                        outer.review_requests.append(body)
                        assert outer.finished_children == set(range(1, len(segments)+1))
                        assert "全部草稿" in texts[1] and "actual_segments" in texts[1]
                        assert all(f'"segment_index": {i}' in texts[1] for i in range(1, len(segments)+1))
                        from dsh_bridge.b_review import CHECKS
                        review = review_response if review_response is not None else {
                            "status": "approved", "checks": {k: True for k in CHECKS}, "issues": [], "edits": []}
                        text = review if isinstance(review, str) else json.dumps(review, ensure_ascii=False)
                    elif "你是B链路的视频反推主AI" in system:
                        outer.coordinator_requests.append(body)
                        if on_coordinator:
                            on_coordinator()
                        text = "无效JSON" if fail_coordinator else json.dumps(SHARED, ensure_ascii=False)
                    elif match:
                        index = int(match[1])
                        with outer.lock:
                            outer.worker_requests.append((index, body))
                        assert not any(n.endswith("set_video_segments") for n in names)
                        if not has_output:
                            with outer.lock:
                                outer.active_children += 1
                                outer.peak_children = max(outer.peak_children, outer.active_children)
                                outer.worker_initial_images[index] = len(images)
                            try:
                                outer.barrier.wait(20)
                                segment = segments[index - 1]
                                stamp = (segment["start"] + segment["end"]) / 2
                                name = next(n for n in names if n.endswith("get_frames"))
                                call = (name, {"times": [stamp]})
                            finally:
                                with outer.lock:
                                    outer.active_children -= 1
                        else:
                            # The tool's actual image must survive exact-input replay.
                            wire = json.dumps(messages, ensure_ascii=False)
                            assert 'local_times' in wire and 'context_only' in wire
                            time.sleep(.03 * (len(segments) - index))
                            text = "" if index == fail_segment else (child_texts or {}).get(index,
                                f"第{index}段完整正文，局部时间0—{segments[index-1]['end']-segments[index-1]['start']:g}秒。")
                            with outer.lock:
                                outer.finished_children.add(index)
                    else:
                        outer.segment_requests.append(body)
                        if not has_output:
                            name = next(n for n in names if n.endswith("set_video_segments"))
                            call = (name, {"segments": segments})
                        else:
                            text = "分段完成，按原片切点衔接。"
                    raw = self.response_events(responses, call, text)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except Exception as exc:
                    outer.errors.append(f"{type(exc).__name__}: {exc}")
                    self.send_error(500, "local test assertion failed")

            def response_events(self, responses, call, text):
                if not responses:
                    delta = {"role": "assistant", "content": text}
                    if call:
                        delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "local_call", "type": "function",
                            "function": {"name": call[0], "arguments": json.dumps(call[1])}}]}
                    chunk = {"id": "local_b", "object": "chat.completion.chunk", "created": 1,
                             "model": "gpt-6.1-sol", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                    end = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if call else "stop"}],
                           "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
                    return ("".join("data: " + json.dumps(v) + "\n\n" for v in (chunk, end)) + "data: [DONE]\n\n").encode()
                events = [{"type": "response.created", "response": {"id": "resp_b"}}]
                if call:
                    items = [{"type": "function_call", "id": "fc_b", "call_id": "call_b", "name": call[0], "arguments": json.dumps(call[1])}]
                    events.extend([{"type": "response.output_item.added", "output_index": 0, "item": items[0]},
                                   {"type": "response.output_item.done", "output_index": 0, "item": items[0]}])
                else:
                    block = {"type": "output_text", "text": text, "annotations": []}
                    item = {"type": "message", "id": "msg_b", "role": "assistant", "status": "completed", "content": [block]}
                    items = [item]
                    events.extend([
                        {"type": "response.output_item.added", "output_index": 0, "item": {**item, "content": []}},
                        {"type": "response.content_part.added", "output_index": 0, "content_index": 0, "part": {**block, "text": ""}},
                        {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": text},
                        {"type": "response.output_text.done", "output_index": 0, "content_index": 0, "text": text},
                        {"type": "response.content_part.done", "output_index": 0, "content_index": 0, "part": block},
                        {"type": "response.output_item.done", "output_index": 0, "item": item},
                    ])
                events.append({"type": "response.completed", "response": {"id": "resp_b", "status": "completed", "output": items,
                    "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}}})
                return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
