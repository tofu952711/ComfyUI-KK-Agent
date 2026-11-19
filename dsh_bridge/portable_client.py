"""Stdlib-only client for the plugin's isolated, bundled Python SDK worker."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .errors import BridgeError
from .paths import VENDOR_DIR


class BundledHarness:
    def __init__(self, **options: Any) -> None:
        # The callback is implemented inside the worker; functions cannot cross stdio.
        self.options = {key: value for key, value in options.items() if key != "on_user_question"}
        self.options["env"] = {**self.options.get("env", {}),
                               "PKG_NATIVE_CACHE_PATH": str(VENDOR_DIR / "windows-x64" / "native-cache")}
        self._process: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, Future] = {}
        self._sequence = 0
        self._disconnected = False
        self._on_notification = None
        self._callback_error: Exception | None = None

    def start(self) -> None:
        if self._process is not None:
            return
        python = VENDOR_DIR / "windows-x64" / "python" / "python.exe"
        worker = Path(__file__).with_name("portable_worker.py")
        env = os.environ.copy()
        preload = Path(__file__).with_name("native_modules.cjs")
        env["NODE_OPTIONS"] = f'--require "{preload.as_posix()}"'
        self._process = subprocess.Popen(
            [str(python), "-B", "-u", str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="strict", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
        )
        threading.Thread(target=self._read, name="dsh-bundled-reader", daemon=True).start()
        try:
            self._request("start", self.options, float(self.options["initialize_timeout_seconds"]) + 15)
        except BaseException:
            self.close()
            raise

    def _read(self) -> None:
        process = self._process
        try:
            for line in process.stdout:
                message = json.loads(line)
                if "notification" in message:
                    callback = self._on_notification
                    if callback is not None:
                        try:
                            callback(SimpleNamespace(**message["notification"]))
                        except Exception as exc:
                            self._callback_error = exc
                    continue
                with self._pending_lock:
                    future = self._pending.pop(message["id"], None)
                if future is not None:
                    if "error" in message:
                        future.set_exception(BridgeError("sdk_worker", message["error"]))
                    else:
                        future.set_result(message.get("result"))
        except Exception as exc:
            error = BridgeError("sdk_worker", f"本地运行时通信失败：{type(exc).__name__}")
        else:
            error = BridgeError("process_exit", "插件自带的本地运行时已退出")
        finally:
            with self._pending_lock:
                self._disconnected = True
                pending, self._pending = self._pending, {}
            for future in pending.values():
                future.set_exception(error)

    def _request(self, method: str, params: dict, timeout: float | None = None):
        process = self._process
        if process is None or process.poll() is not None:
            raise BridgeError("process_exit", "插件自带的本地运行时未启动")
        future: Future = Future()
        with self._pending_lock:
            if self._disconnected:
                raise BridgeError("process_exit", "插件自带的本地运行时已断开")
            self._sequence += 1
            request_id = self._sequence
            self._pending[request_id] = future
        try:
            with self._write_lock:
                process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params},
                                               ensure_ascii=False) + "\n")
                process.stdin.flush()
            return future.result(timeout=timeout)
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def resume_session(self, session: str) -> None:
        self._request("resume", {"session": session}, float(self.options["request_timeout_seconds"]))

    def run(self, blocks: list[dict], *, session_id: str, on_notification=None):
        self._on_notification = on_notification
        self._callback_error = None
        try:
            result = self._request("run", {"blocks": blocks, "session": session_id})
            if self._callback_error is not None:
                raise self._callback_error
            return SimpleNamespace(**result)
        finally:
            self._on_notification = None

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                try:
                    self._request("close", {}, 8)
                except Exception:
                    pass
                process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Only this worker and its owned native child, never another DSH instance.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                    process.wait(timeout=5)
        finally:
            self._process = None
            process.stdout.close()
