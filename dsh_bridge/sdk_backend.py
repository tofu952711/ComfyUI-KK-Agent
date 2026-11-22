"""Official SDK transport shared by nodes and the chat panel.

One runtime owns all sessions. Turns are serialized so panel edits and graph
execution cannot consume each other's responses. Cancelling closes this private
runtime, because the pinned SDK has no per-turn cancel method. Submitted turns
are retried within the failed model step for transient errors only.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import threading
from pathlib import Path
from typing import Any, Callable

from . import paths
from .errors import BridgeError
from .config import environment_api_key

SDK_VERSION = "0.2.2rc2"


def provider_api(cfg: dict[str, Any]) -> str:
    """CodeZ documents Responses; preserve the separate zdjapi compatibility route."""
    from urllib.parse import urlsplit
    protocol = cfg.get("api_protocol", "deepseek-messages")
    host = urlsplit(str(cfg.get("base_url") or "")).hostname or ""
    is_zdjapi = host == "zdjapi.com" or host.endswith(".zdjapi.com")
    if protocol == "codez" and not is_zdjapi:
        return "openai-responses"
    return "openai-completions" if protocol in ("openai-completions", "codez") else protocol


def instruction_role(cfg: dict[str, Any]) -> str:
    """Keep literal rules separate; work around the verified gateway role issue."""
    from urllib.parse import urlsplit
    # Narrowly scoped to the exact route/model reproduced with paired live probes.
    # Other providers and Anthropic retain their original system-role behavior.
    if (cfg.get("video_exact_inputs") and
            cfg.get("api_protocol") in ("openai-completions", "codez") and
            urlsplit(str(cfg.get("base_url") or "")).hostname == "api.zdjapi.com" and
            cfg.get("model") == "gpt-6.1-sol"):
        return "developer"
    return "system"


def response_diagnostics(result: Any) -> dict[str, Any]:
    """Return response counts and token totals, without model or image content."""
    messages = [e.get("data") or {} for e in result.events if e.get("type") == "assistant/message"]
    last = messages[-1] if messages else {}
    content = (last.get("message") or last).get("content") or []
    usage = last.get("usage") or {}
    return {"finish_reason": result.finish_reason, "assistant_messages": len(messages),
            "text_chars": sum(len(str(b.get("text") or "")) for b in content if b.get("type") == "text"),
            "reasoning_chars": sum(len(str(b.get("text") or "")) for b in content if b.get("type") == "reasoning"),
            "usage": {k: v for k, v in usage.items() if isinstance(v, (int, float))}}


def sdk_info() -> dict[str, Any]:
    bundle = paths.VENDOR_DIR / "windows-x64"
    manifest = bundle / "bundle.json"
    if manifest.is_file() and platform.system() == "Windows":
        try:
            info = json.loads(manifest.read_text(encoding="utf-8"))
            complete = all((bundle / name).is_file() for name in info["required_files"])
            supported = os.name == "nt" and platform.machine().lower() in ("amd64", "x86_64")
            version, runtime = info["sdk_version"], info["runtime_version"]
            return {"installed": complete and supported, "bundled": True,
                    "version": version, "runtime_version": runtime, "required": SDK_VERSION,
                    "python_version": info["python_version"], "platform": "windows-x64",
                    "compatible": complete and supported and version == runtime == SDK_VERSION}
        except (ValueError, KeyError, OSError):
            return {"installed": False, "bundled": True, "required": SDK_VERSION}
    try:
        version = importlib.metadata.version("deepseek-harness-sdk")
        runtime = importlib.metadata.version("deepseek-harness-runtime-bin")
    except importlib.metadata.PackageNotFoundError:
        return {"installed": False, "required": SDK_VERSION}
    return {"installed": True, "version": version, "runtime_version": runtime,
            "required": SDK_VERSION, "compatible": version == runtime == SDK_VERSION}


def prepare_home(cfg: dict[str, Any]) -> Path:
    """Seed missing bundled skills in the plugin's isolated home; preserve edits."""
    home = Path(cfg["dsh_home"]).resolve()
    home.mkdir(parents=True, exist_ok=True)
    Path(cfg["workspace"]).mkdir(parents=True, exist_ok=True)
    if cfg.get("video_prompt_only"):
        return home  # Full-video rules come only from the workflow text input.
    source = paths.VENDOR_DIR / "skills"
    for item in source.rglob("*"):
        if item.is_file():
            target = home / "skills" / item.relative_to(source)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    return home


class SDKRuntime:
    external = False

    def __init__(self, cfg: dict[str, Any]) -> None:
        from .config import connection_preset
        self.cfg = connection_preset(cfg)
        self._state_lock = threading.RLock()
        self._turn_lock = threading.Lock()
        self._harness: Any = None
        self._starting_harness: Any = None
        self._active = ""
        self._cancelled = threading.Event()
        self._known: set[str] = set()
        self._restored: set[str] = set()
        self.last_diagnostics: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        return self._harness is not None

    @property
    def pid(self) -> None:
        # No private SDK fields are needed to supervise the runtime.
        return None

    @property
    def active_session(self) -> str:
        return self._active

    def start(self) -> None:
        with self._state_lock:
            if self._harness is not None:
                return
            info = sdk_info()
            if not info.get("installed"):
                raise BridgeError("missing_sdk", "Harness 运行时缺失：Windows 请使用完整免安装包；云端请先由平台安装 requirements.txt 中的官方 SDK/runtime")
            if not info.get("compatible"):
                raise BridgeError("sdk_version", f"需要 SDK/runtime {SDK_VERSION}，请更新插件完整包或云端依赖")
            if info.get("bundled"):
                from .portable_client import BundledHarness as DeepSeekHarness
            else:
                from deepseek_harness import DeepSeekHarness

            home = prepare_home(self.cfg)
            key = str(self.cfg.get("api_key") or environment_api_key(self.cfg) or "").strip()
            if not key:
                raise BridgeError("missing_api_key", "请在工作流节点的 API Key 输入或本地 DSH 面板中填写密钥")
            manifest = home / "bridge-sessions.json"
            if manifest.is_file():
                known = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(known, list) or not all(isinstance(item, str) for item in known):
                    raise BridgeError("session_manifest", "会话索引损坏，请备份后移走 bridge-sessions.json")
                self._known = set(known)
            env = {"DSH_PRIMARY_RUNTIME": "", "DSH_OFFICE_RUNTIME": ""}
            proxy = str(self.cfg.get("proxy_url") or "").strip()
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                if proxy or self.cfg.get("strip_proxy_env"):
                    env[name] = proxy
            env["DSH_HOME"] = str(home)
            env["DSH_BRIDGE_MODEL_KEY"] = key
            # Explicitly declare the user-selected route as a vision route. Without
            # this, the SDK treats an unlisted model id as text-only and drops images.
            model_patch = home / "bridge-model.patch.yml"
            protocol = self.cfg.get("api_protocol", "deepseek-messages")
            rules_role = instruction_role(self.cfg)
            effort = self.cfg.get("reasoning_effort", "auto")
            if effort not in ("auto", "low", "medium", "high"):
                raise ValueError("思考等级请选择 auto、low、medium 或 high")
            explicit_effort = effort != "auto"
            base_url = str(self.cfg.get("base_url") or "").rstrip("/")
            if protocol in ("openai-completions", "codez"):
                wire_api = provider_api(self.cfg)
                for suffix in ("/chat/completions", "/responses"):
                    if base_url.endswith(suffix):
                        base_url = base_url[:-len(suffix)]
                patch = [{"id": "llm-deepseek", "disabled": True},
                         {"id": "llm-deepseek-account", "disabled": True},
                         {"id": "llm-pi-ai", "config": {"providers": {
                             self.cfg["provider"]: {
                                 "api": wire_api, "baseURL": base_url,
                                 "apiKeyEnv": "DSH_BRIDGE_MODEL_KEY",
                                 "retryPolicy": {"mode": "normal", "maxRetries": 0},
                                 "timeoutMs": int(self.cfg["request_timeout_s"]) * 1000,
                                 "compat": ({} if wire_api == "openai-responses" else {
                                            "supportsStore": False, "supportsDeveloperRole": rules_role == "developer",
                                            "supportsReasoningEffort": explicit_effort, "supportsUsageInStreaming": bool(self.cfg.get('stream_usage')),
                                            "maxTokensField": "max_tokens", "supportsStrictMode": False}),
                                 "models": [{"id": self.cfg["model"], "input": ["text", "image"],
                                             "contextWindow": 128000, "maxTokens": int(self.cfg["max_tokens"]),
                                             "reasoningEfforts": ({level: level for level in ("low", "medium", "high")}
                                                                  if explicit_effort else False)}],
                             }
                         }}}]
            elif protocol == "deepseek-messages":
                patch = [{"id": "llm-deepseek", "config": {
                    "apiKeyEnv": "DSH_BRIDGE_MODEL_KEY", "baseURL": base_url,
                    "retryPolicy": {"mode": "normal", "maxRetries": 0},
                    "models": [{"id": self.cfg["model"], "inputModalities": ["text", "image"],
                                "contextWindow": 1048576}],
                }}]
                if self.cfg.get("video_prompt_only"):
                    # Dense video evidence can exceed the inline fallback's
                    # default 20 MiB once PNG bytes are base64 encoded. Match
                    # the bounded Files budget instead of dropping references.
                    patch[0]["config"]["maxInlineRequestImageBytes"] = 128 * 1024 * 1024
            else:
                raise BridgeError("api_protocol", "不支持的 API 协议，请在连接设置中重新选择")
            model_patch.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
            patches = [str(paths.VENDOR_DIR / "profile" / "standalone.patch.yml"), str(model_patch)]
            # Provider retries remain disabled above so only this fixed schedule
            # owns retries; the agent retains completed tools and media evidence.
            retry_patch = home / "bridge-retry.patch.yml"
            retry_patch.write_text(json.dumps([{"insert": [{"id": "bridge-request-retry",
                "name": (paths.VENDOR_DIR / "plugins/request-retry/index.mjs").resolve().as_uri()}]}]), encoding="utf-8")
            patches.append(str(retry_patch))
            speed_patch = home / 'bridge-token-speed.patch.yml'
            speed_patch.write_text(json.dumps([{'insert': [{'id': 'bridge-token-speed',
                'name': (paths.VENDOR_DIR / 'plugins/token-speed/index.mjs').resolve().as_uri(),
                'config': {'file': str(home / 'token-speed.jsonl')}}]}]), encoding='utf-8')
            patches.append(str(speed_patch))
            if self.cfg.get("video_prompt_only"):
                patches.append(str(paths.VENDOR_DIR / "profile" / "video-prompt.patch.yml"))
                system_prompt = self.cfg.get("video_system_prompt")
                if isinstance(system_prompt, str) and system_prompt.strip():
                    system_patch = home / "bridge-video-system.patch.yml"
                    if self.cfg.get("video_exact_inputs"):
                        system_patch.write_text(json.dumps([
                            {"id": "system-prompt", "config": {"personaPrefix": "", "personaSuffix": "",
                                "includeHarnessIdentity": False, "includeRuntimeContext": False}},
                            {"insert": [{"id": "bridge-exact-inputs",
                                "name": (paths.VENDOR_DIR / "plugins/exact-inputs/index.mjs").resolve().as_uri(),
                                "config": {"text": system_prompt,
                                    "user": self.cfg["video_user_prompt"], "baseURL": base_url,
                                    "mediaEvidence": self.cfg.get("video_media_evidence", ""),
                                    "instructionRole": rules_role,
                                    "auditFile": self.cfg.get("_request_audit_file")}}]},
                        ], ensure_ascii=False), encoding="utf-8")
                    else:
                        system_patch.write_text(json.dumps([{"id": "system-prompt", "config": {
                            "personaPrefix": system_prompt + "\n\n【工作流规则优先级】以上是本次工作流的系统提示词。"
                            "交付内容和格式依照以上规则及其明确允许的用户要求；运行时通用的解释、文件展示和链接建议"
                            "不应改变这些要求。素材标签@视频N、@图片N是引用编号，不是文件路径。",
                        }}], ensure_ascii=False), encoding="utf-8")
                    patches.append(str(system_patch))
            if self.cfg.get("media_mcp"):
                # Use the official Harness MCP client. The media subprocess has
                # no model credentials and can only inspect this run's video.
                media_patch = home / "bridge-media.patch.yml"
                media_patch.write_text(json.dumps([{"insert": [{"id": "bridge-media-mcp",
                    "name": "@deepseek-ai/dsh-mcp-client", "config": self.cfg["media_mcp"]}]}]), encoding="utf-8")
                patches.append(str(media_patch))
            harness = DeepSeekHarness(
                dsh_home=str(home), cwd=str(Path(self.cfg["workspace"]).resolve()),
                profile="sdk", patches=tuple(patches),
                provider=self.cfg["provider"], model=self.cfg["model"],
                reasoning_effort=effort if explicit_effort else None,
                max_tokens=int(self.cfg["max_tokens"]),
                env=env, initialize_timeout_seconds=float(self.cfg["startup_timeout_s"]),
                request_timeout_seconds=float(self.cfg["request_timeout_s"]),
                shutdown_timeout_seconds=2.0,
                on_user_question=lambda _request, _cancelled: {"cancelled": True},
            )
            self._starting_harness = harness
            try:
                harness.start()
            except BaseException:
                harness.close()
                raise
            finally:
                self._starting_harness = None
            self._harness = harness
            self._restored.clear()

    def _remember(self, session: str) -> None:
        if session in self._known:
            return
        self._known.add(session)
        manifest = Path(self.cfg["dsh_home"]) / "bridge-sessions.json"
        temp = manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(sorted(self._known)), encoding="utf-8")
        temp.replace(manifest)

    def stop(self, expected: Any = None, *, force: bool = False) -> None:
        with self._state_lock:
            harness = self._harness
            if expected is not None and harness is not expected:
                return
            self._harness = None
            self._restored.clear()
        if harness is not None:
            if force and hasattr(harness, "cancel"):
                harness.cancel()
            else:
                harness.close()

    def cancel(self) -> bool:
        if not self._active:
            return False
        self._cancelled.set()
        # start() retains the state lock while handshaking. Stop the starting
        # owned worker directly so cancellation does not wait for that timeout.
        starting = self._starting_harness
        if starting is not None:
            (starting.cancel if hasattr(starting, "cancel") else starting.close)()
        self.stop(force=True)
        return True

    def run(self, session: str, blocks: list[dict[str, Any]], timeout: float,
            on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        if not self._turn_lock.acquire(blocking=False):
            raise BridgeError("busy", "已有任务运行，请等待完成或点击停止")
        timed_out = threading.Event()
        timer: threading.Timer | None = None
        speed_reader = None
        owned_monitor = None
        try:
            self.last_diagnostics = {}
            self._cancelled.clear()
            self._active = session
            self.start()
            with self._state_lock:
                if self._cancelled.is_set():
                    raise BridgeError("cancelled", "任务已停止")
                harness = self._harness
            def deadline() -> None:
                timed_out.set()
                self.stop(expected=harness)
            timer = threading.Timer(timeout, deadline)
            timer.daemon = True
            timer.start()
            if session in self._known and session not in self._restored:
                harness.resume_session(session)
            self._restored.add(session)
            if on_progress:
                on_progress("running")
            def notification(note: Any) -> None:
                if note.method == "session.event" and note.payload.get("sessionId") == session:
                    self._remember(session)
                    event_type = (note.payload.get("event") or {}).get("type", "")
                    if event_type == "llm/retry":
                        data = note.payload["event"].get("data") or {}
                        print(f"[DSH] 模型请求失败，{data.get('delayMs', 0) / 1000:g}秒后自动重试"
                              f"（{data.get('retry')}/3，{(data.get('failure') or {}).get('code', 'unknown')}）", flush=True)
                    if on_progress and event_type in ("step/start", "assistant/message", "tool/call", "tool/result", "turn/end", "llm/retry", "llm/retry-started"):
                        on_progress(event_type)
            from .token_speed import SpeedReader, SpeedRun
            monitor = self.cfg.get('_token_monitor')
            if monitor is None:
                owned_monitor = monitor = SpeedRun(None, self.cfg['model'])
            speed_reader = SpeedReader(Path(self.cfg['dsh_home']) / 'token-speed.jsonl', monitor.handle)
            speed_reader.start()
            result = harness.run(blocks, session_id=session, on_notification=notification)
            speed_reader.close()
            speed_records = [row for row in speed_reader.records if row['kind'] == 'end']
            speed_reader = None
            self.last_diagnostics = response_diagnostics(result)
            self.last_diagnostics['token_speed'] = speed_records
            if timed_out.is_set():
                raise BridgeError("timeout", "任务已超时，后台运行时已停止；不会自动重复提交")
            if self._cancelled.is_set():
                raise BridgeError("cancelled", "任务已停止")
            if result.finish_reason not in ("completed", "max-tokens"):
                failure = next(((e.get("data") or {}).get("reason", {}).get("error")
                                for e in reversed(result.events) if e.get("type") == "turn/end"), None) or {}
                self.last_diagnostics["failure"] = failure
                self.last_diagnostics["retries"] = [e["data"] for e in result.events if e.get("type") == "llm/retry"]
                message = (f"{failure.get('code', 'unknown')}: {failure['message']}" if failure.get("message")
                           else result.final_response or f"模型结束状态：{result.finish_reason}")
                raise BridgeError("model_error", message.replace(key, "[REDACTED]") if (key := str(self.cfg.get("api_key") or "")) else message)
            if result.finish_reason == "max-tokens":
                raise BridgeError("output_limit", "模型达到本次输出上限，结果不完整；请提高 max_tokens 后手动重试")
            if not result.final_response.strip():
                raise BridgeError("empty_response", f"模型结束但未返回正文（finish_reason={result.finish_reason}）；请查看诊断记录")
            if on_progress:
                on_progress("idle")
            usage = {}
            for event in reversed(result.events):
                if event.get("type") == "assistant/message":
                    usage = (event.get("data") or {}).get("usage") or {}
                    break
            return {"kind": "prompt", "text": result.final_response, "usage": usage,
                    "events": result.events, "finish_reason": result.finish_reason,
                    "token_speed": speed_records}
        except Exception as exc:
            if timed_out.is_set():
                raise BridgeError("timeout", "任务已超时并停止，不会自动重复计费请求") from exc
            if self._cancelled.is_set():
                raise BridgeError("cancelled", "任务已停止") from exc
            # Request-level retries have already completed or been declined; never restart the task here.
            self.stop()
            raise
        finally:
            if speed_reader:
                speed_reader.close()
            if owned_monitor:
                owned_monitor.finish('completed' if self.last_diagnostics.get('finish_reason') == 'completed' else 'error')
            if timer:
                timer.cancel()
            self._active = ""
            self._turn_lock.release()


class SDKChannel:
    def __init__(self, name: str, cfg: dict[str, Any], proc: SDKRuntime) -> None:
        self.name, self.cfg, self.proc = name, cfg, proc
        self._connected = False

    def connect(self) -> None:
        self.proc.start()
        self._connected = True

    @property
    def ready(self) -> bool:
        return self._connected and self.proc.alive

    def ask(self, session_id: str, blocks: list[dict[str, Any]], timeout: float | None = None,
            on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        self._connected = True
        return self.proc.run(session_id, blocks, float(timeout or self.cfg["request_timeout_s"]), on_progress)

    def close(self) -> None:
        self._connected = False
