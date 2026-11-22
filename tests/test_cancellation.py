"""DSH cancellation and isolated media preparation; no remote model calls."""
import asyncio
import importlib
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def backend(request, monkeypatch):
    package = "dsh_bridge"
    monkeypatch.syspath_prepend(str(ROOT))
    flag = threading.Event()
    class Interrupted(BaseException):
        pass
    monkeypatch.setitem(sys.modules, "comfy.model_management", SimpleNamespace(
        processing_interrupted=flag.is_set, InterruptProcessingException=Interrupted))
    cancellation = importlib.import_module(package + ".cancellation")
    yield SimpleNamespace(c=cancellation, package=package, flag=flag, error=Interrupted)
    with cancellation._LOCK:
        scopes = list(cancellation._SCOPES)
    for scope in scopes:
        scope.cancel()
        scope.close()


def test_cancel_is_latched_without_consuming_parallel_interrupt(backend):
    scope = backend.c.CancelScope()
    backend.flag.set()
    with pytest.raises(backend.error):
        scope.check()
    assert backend.flag.is_set()
    backend.flag.clear()
    with pytest.raises(backend.error):
        scope.check()
    # A fresh submission has an independent cancellation state.
    fresh = backend.c.CancelScope()
    fresh.check()


def test_cancel_kills_owned_hung_process(backend, monkeypatch, tmp_path):
    scope = backend.c.CancelScope()
    owned = []
    original = subprocess.Popen
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        if not owned:
            owned.append(process)
        return process
    monkeypatch.setattr(backend.c.subprocess, "Popen", capture)
    timer = threading.Timer(.3, scope.cancel)
    start = time.monotonic()
    timer.start()
    try:
        with backend.c.bind_scope(scope), pytest.raises(backend.error):
            backend.c.cancellable_run([sys.executable, "-c", "import time; time.sleep(60)"],
                                      capture_output=True, timeout=60)
    finally:
        timer.cancel()
    assert owned[0].poll() is not None
    assert time.monotonic() - start < 5


def test_model_and_review_watchers_stop_even_after_flag_reset(backend):
    Bridge = importlib.import_module(backend.package + ".bridge").Bridge
    scope = backend.c.CancelScope()
    entered, stopped = threading.Event(), threading.Event()
    bridge = Bridge({}, persist=False)
    def ask(*args, **kwargs):
        entered.set()
        assert stopped.wait(5), "model/reviewer was not cancelled"
        raise OSError("transport closed")
    bridge._channel = lambda name: SimpleNamespace(ask=ask)
    bridge.cancel = lambda: stopped.set()
    timer = threading.Timer(.2, scope.cancel)
    timer.start()
    try:
        with backend.c.bind_scope(scope), backend.c.watch_bridge(bridge):
            with pytest.raises(backend.error):
                bridge.ask("test", "test")
            # A cancelled draft must never dispatch a subsequent reviewer.
            with pytest.raises(backend.error):
                bridge.ask("review", "test")
    finally:
        timer.cancel()
    assert entered.is_set() and stopped.is_set()


def test_native_interrupt_http_hook_latches_scope(backend):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    async def scenario():
        app = web.Application()
        async def interrupt(request):
            backend.flag.set()
            return web.json_response({})
        app.router.add_post("/interrupt", interrupt)
        backend.c.install_interrupt_hook(SimpleNamespace(app=app))
        scope = backend.c.CancelScope()
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/interrupt", json={})
            assert response.status == 200
            assert scope.cancelled.is_set()
            backend.flag.clear()
            with pytest.raises(backend.error):
                scope.check()
    asyncio.run(scenario())


def test_generator_can_resume_on_another_worker_context(backend):
    Bridge = importlib.import_module(backend.package + ".bridge").Bridge
    async def scenario():
        scope = backend.c.CancelScope()
        bridge = Bridge({}, persist=False)
        def stages():
            with backend.c.watch_bridge(bridge):
                yield "prepared"
                backend.c.check_cancelled()
                yield "completed"
        generator = stages()
        assert await backend.c.cancellable_to_thread(next, generator, scope=scope) == "prepared"
        assert await backend.c.cancellable_to_thread(next, generator, scope=scope) == "completed"
        await backend.c.cancellable_to_thread(generator.close, scope=scope)
        scope.close()
    asyncio.run(scenario())


def test_async_cancel_stops_worker_before_returning(backend):
    exited = threading.Event()
    async def scenario():
        scope = backend.c.CancelScope()
        def worker():
            try:
                backend.c.cancellable_run([sys.executable, "-c", "import time; time.sleep(60)"],
                                          capture_output=True)
            finally:
                exited.set()
        task = asyncio.create_task(backend.c.cancellable_to_thread(worker, scope=scope))
        await asyncio.sleep(.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exited.is_set()
        scope.close()
    asyncio.run(scenario())


def test_inference_is_submitted_before_sync_sibling_blocks_event_loop(backend):
    # Match ComfyUI execution.py: create async node, yield exactly once, then
    # invoke a blocking synchronous sibling on the execution loop itself.
    started, released = threading.Event(), threading.Event()
    async def scenario():
        scope = backend.c.CancelScope()
        def inference():
            backend.c.check_cancelled()  # copied ContextVar must survive dispatch
            assert backend.c.current_scope() is scope
            started.set()
            assert released.wait(4)
            return "draft"
        task = asyncio.create_task(backend.c.cancellable_to_thread(inference, scope=scope))
        await asyncio.sleep(0)
        try:
            # Deliberately block this event loop. A second-turn to_thread task
            # cannot start here; an eagerly submitted executor job can.
            assert started.wait(2), "sync masking blocked reverse submission"
        finally:
            released.set()
        assert await task == "draft"
        scope.close()
    asyncio.run(scenario())


def test_cancelled_progress_is_not_success(backend, monkeypatch, tmp_path):
    module = importlib.import_module(backend.package + ".token_speed")
    monkeypatch.setattr(module.paths, "bridge_data_dir", lambda: tmp_path)
    scope = backend.c.CancelScope()
    with backend.c.bind_scope(scope), pytest.raises(backend.error):
        with module.SpeedRun("test", "local") as speed:
            scope.cancel()
            scope.check()
    assert speed.status == "cancelled"


@pytest.mark.parametrize("chain", ["A", "B"])
def test_isolated_media_preparation_and_clean_process_exit(backend, tmp_path, chain):
    import av
    import numpy as np
    source = tmp_path / "source-video.mp4"
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=12)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "yuv420p"
        for index in range(24):
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 96, 3), dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    output = tmp_path / "media-analysis"
    output.mkdir()
    module = importlib.import_module(backend.package + ".isolated_preparation")
    report, shots, transcript = module.prepare_isolated(output, tmp_path / "no-model", chain=chain, timeout=30)
    assert report["video"]["duration_seconds"] == 2
    assert transcript["has_audio"] is False
    assert report["sheets"]


def test_dsh_force_cancel_does_not_wait_for_graceful_shutdown(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    module = importlib.import_module("dsh_bridge.portable_client")
    worker = module.BundledHarness()
    worker._process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    process = worker._process
    start = time.monotonic()
    worker.cancel()
    assert process.poll() is not None
    assert time.monotonic() - start < 5
