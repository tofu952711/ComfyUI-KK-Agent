"""Private worker. Executed only by the bundled Python, never imported by ComfyUI."""
from __future__ import annotations

import json
import sys
import threading


def main() -> None:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    protocol = sys.stdout
    sys.stdout = sys.stderr  # Keep incidental library output out of the protocol.
    output_lock = threading.Lock()
    harness = None

    def send(payload: dict) -> None:
        with output_lock:
            protocol.write(json.dumps(payload, ensure_ascii=False) + "\n")
            protocol.flush()

    def notification(note) -> None:
        send({"notification": {"method": note.method, "payload": note.payload}})

    def execute(request: dict) -> None:
        nonlocal harness
        try:
            params, method = request["params"], request["method"]
            if method == "start":
                from deepseek_harness import DeepSeekHarness
                harness = DeepSeekHarness(**params, on_user_question=lambda *_: {"cancelled": True})
                harness.start()
                result = {"ready": True}
            elif method == "resume":
                harness.resume_session(params["session"])
                result = None
            elif method == "run":
                answer = harness.run(params["blocks"], session_id=params["session"],
                                     on_notification=notification)
                result = {"final_response": answer.final_response, "finish_reason": answer.finish_reason,
                          "events": answer.events}
            elif method == "close":
                if harness is not None:
                    harness.close()
                result = None
            else:
                raise ValueError("unsupported worker method")
            send({"id": request["id"], "result": result})
        except Exception as exc:
            send({"id": request["id"], "error": f"{type(exc).__name__}: {exc}"})

    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request["method"] == "close":
                execute(request)  # Close can interrupt an active run on its worker thread.
                break
            threading.Thread(target=execute, args=(request,), daemon=True).start()
    finally:
        if harness is not None:
            harness.close()  # EOF also cleans up when the ComfyUI parent exits.


if __name__ == "__main__":
    main()
