"""Local Responses SSE fixture; exercises the real bundled provider adapter."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ResponsesGateway:
    def __init__(self, detail=True, media=False, segments=None):
        self.requests, self.paths, self.headers = [], [], []
        self.status = 200
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.paths.append(self.path)
                outer.headers.append({k.lower(): v for k, v in self.headers.items()})
                if self.path != "/v1/responses" or outer.status != 200:
                    raw = json.dumps({"error": {"message": "mock gateway rejected request"}}).encode()
                    self.send_response(outer.status if outer.status != 200 else 404)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                call = (detail or segments is not None) and len(outer.requests) == 1
                items = []
                events = [{"type": "response.created", "response": {"id": "resp_local"}}]
                if call:
                    tool = next(t["name"] for t in body["tools"] if t["name"].endswith("get_frames")) if media else "skill"
                    args = {"times": [.25, 1.25]} if media else {"name": "video-replica"}
                    if segments is not None:
                        tool = next(t["name"] for t in body["tools"] if t["name"].endswith("set_video_segments"))
                        args = {"segments": segments}
                    items = [
                        {"type": "reasoning", "id": "rs_local", "encrypted_content": "local-replay-proof", "summary": []},
                        {"type": "function_call", "id": "fc_local", "call_id": "call_local", "name": tool, "arguments": json.dumps(args)},
                    ]
                    for index, item in enumerate(items):
                        events.extend([
                            {"type": "response.output_item.added", "output_index": index, "item": item},
                            {"type": "response.output_item.done", "output_index": index, "item": item},
                        ])
                else:
                    block = {"type": "output_text", "text": "本地测试完成 left to right", "annotations": []}
                    item = {"type": "message", "id": "msg_local", "role": "assistant", "status": "completed", "content": [block]}
                    items = [item]
                    events.extend([
                        {"type": "response.output_item.added", "output_index": 0, "item": {**item, "content": []}},
                        {"type": "response.content_part.added", "output_index": 0, "content_index": 0, "part": {**block, "text": ""}},
                        {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": block["text"]},
                        {"type": "response.output_text.done", "output_index": 0, "content_index": 0, "text": block["text"]},
                        {"type": "response.content_part.done", "output_index": 0, "content_index": 0, "part": block},
                        {"type": "response.output_item.done", "output_index": 0, "item": item},
                    ])
                events.append({"type": "response.completed", "response": {
                    "id": "resp_local", "status": "completed", "output": items,
                    "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
                              "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 10}},
                }})
                raw = "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
