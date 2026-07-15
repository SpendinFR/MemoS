from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import threading
from datetime import datetime
from fractions import Fraction
from types import SimpleNamespace
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "services" / "live-pc"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIVE / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gateway = load("phone_test_gateway", "gateway.py")
runtime_mod = load("phone_test_runtime", "phoneonly_runtime.py")
http_mod = load("phone_test_http", "sessionhub_http.py")


class FakeIngress:
    def __init__(self, **_kwargs):
        self.on_audio_chunk = None
        self.offers = 0
        self.peer_state = "new"
        self._audio = asyncio.Queue()
        self.sent = []
        self.open_channels = 0

    async def __aiter__(self):
        while False:
            yield None

    async def handle_offer_sdp(self, sdp, kind):
        self.offers += 1
        return "answer", "answer"

    async def close(self):
        return None

    def send_ui_intent(self, payload):
        if self.open_channels:
            self.sent.append(payload)
        return self.open_channels

    def stats(self):
        return {"peer_state": self.peer_state, "frames_received": 0, "frames_dropped": 0}


class FakeConversation:
    live_session_id = "brainlive-real-1"
    metrics = {"conversation_turns": 1}

    def end_session(self, **_kwargs):
        return {"status": "ended"}


class FakePipeline:
    def __init__(self, *, ingress, **_kwargs):
        self.ingress = ingress
        self.init_kwargs = dict(_kwargs)
        self.conversation = FakeConversation()
        self.audio_archive = type("Archive", (), {"metrics": {"segments_archived": 1}})()
        self.end_calls = 0
        self.audio_calls = []

    async def run_video(self):
        async for _ in self.ingress:
            pass

    def on_audio_chunk(self, samples, rate):
        self.audio_calls.append((samples, rate))
        return []

    def end_session(self, **_kwargs):
        self.end_calls += 1

    def flush_audio(self):
        return []

    def release_live_resources(self):
        return None

    def metrics(self):
        return {"conversation_turns": 1, "keyframes_recorded": 1}


def test_runtime_starts_pipeline_audio_and_explicit_close_day_once():
    close_calls = []

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-1",
            person_id="owner",
            ingress_factory=FakeIngress,
            pipeline_factory=FakePipeline,
            close_day=lambda **kw: close_calls.append(kw) or {"status": "completed"},
        )
        await rt.start()
        assert rt.pipeline.init_kwargs["enable_help_mode"] is True
        assert rt.pipeline.init_kwargs["enable_live_discourse"] is False
        assert rt.pipeline.init_kwargs["defer_fine_intel"] is True
        rt.ingress.on_audio_chunk(np.zeros(480, dtype=np.int16), 48000)
        first = await rt.end_and_close_day()
        second = await rt.end_and_close_day()
        assert rt.pipeline.end_calls == 1
        assert first["end_session"] == second["end_session"] == "completed"
        assert close_calls == [{"person_id": "owner", "live_session_id": "brainlive-real-1"}]

    asyncio.run(scenario())


def test_deferred_semantics_runs_after_end_before_close_day():
    order = []

    class DeferredPipeline(FakePipeline):
        def drain_deferred_semantics(self):
            order.append("deferred_semantics")
            return {"status": "completed", "remaining": 0, "model_calls": 1}

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-deferred",
            ingress_factory=FakeIngress,
            pipeline_factory=DeferredPipeline,
            close_day=lambda **_: order.append("close_day") or {"status": "completed"},
        )
        await rt.end_and_close_day()
        assert order == ["deferred_semantics", "close_day"]
        assert rt.status()["deferred_semantics"] == "completed"

    asyncio.run(scenario())


class DrainTimeoutPipeline(FakePipeline):
    """Pipeline whose final worker is still busy when shutdown is requested."""

    def __init__(self, *, ingress, **kwargs):
        super().__init__(ingress=ingress, **kwargs)
        self._reported = []

    def _report_error(self, scope, exc):
        self._reported.append((scope, str(exc)))

    def end_session(self, **_kwargs):
        self.end_calls += 1
        raise TimeoutError("final turn processing did not drain in 30.0s")

def test_drain_timeout_blocks_brainlive_end_and_close_day():
    close_calls = []

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-drain",
            person_id="owner",
            ingress_factory=FakeIngress,
            pipeline_factory=DrainTimeoutPipeline,
            close_day=lambda **kw: close_calls.append(kw) or {"status": "completed"},
        )
        await rt.start()
        result = await rt.end_and_close_day()
        # Pending final turns make this an incomplete close. BrainLive must stay
        # retryable and CloseDay must never overtake the worker.
        assert result["end_session"] == "error", result
        assert result["close_day"] == "not_started", result
        assert close_calls == []
        assert rt.ended is False
        assert any("did not drain" in e for e in rt.recent_errors)

    asyncio.run(scenario())


def test_single_phone_policy_refuses_second_active_session():
    async def scenario():
        manager = runtime_mod.SinglePhoneRuntimeManager(
            ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
            close_day=lambda **_: {"status": "completed"},
        )
        await manager.get_or_create("one")
        try:
            await manager.get_or_create("two")
            assert False, "second phone must be refused"
        except RuntimeError:
            pass

    asyncio.run(scenario())


def test_single_phone_policy_allows_new_session_after_explicit_close_day():
    async def scenario():
        manager = runtime_mod.SinglePhoneRuntimeManager(
            ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
            close_day=lambda **_: {"status": "completed"},
        )
        first = await manager.get_or_create("one")
        await first.end_and_close_day()
        second = await manager.get_or_create("two")
        assert second.session_id == "two"
        assert second is manager.active

    asyncio.run(scenario())


class FakeManager:
    def __init__(self):
        self.runtime = None

    async def get_or_create(self, sid):
        if self.runtime is None:
            self.runtime = runtime_mod.PhoneOnlyRuntime(
                sid, ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
                close_day=lambda **_: {"status": "completed"},
            )
            await self.runtime.start()
        return self.runtime

    def get(self, sid):
        return self.runtime if self.runtime and self.runtime.session_id == sid else None

    def metrics(self):
        return {"active": self.runtime.status() if self.runtime else None}

    def start_close_day(self, sid):
        assert self.runtime is not None and self.runtime.session_id == sid
        return asyncio.create_task(self.runtime.run_close_day())


def test_offer_creates_runtime_and_end_is_authenticated():
    manager = FakeManager()
    app = http_mod.create_app(enable_signaling=True, runtime_manager=manager)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] in {"pairing_ready", "full_ready"}
        assert health.json()["pairing_ready"] is True
        # Full AI readiness is a distinct strict endpoint; stopped Ollama/Qdrant
        # must not be disguised as a successful whole-chain probe.
        if not health.json()["ai_ready"]:
            assert client.get("/ready").status_code == 503
        creds = client.post("/session/create", json={"device_id": "android"}).json()
        bad = client.post("/session/end", json={"session_id": creds["session_id"], "token": "bad"})
        assert bad.status_code == 401
        offer = client.post("/webrtc/offer", json={**creds, "sdp": "offer", "type": "offer"})
        assert offer.status_code == 200
        assert manager.runtime is not None and manager.runtime.video_task is not None
        ended = client.post("/session/end", json={"session_id": creds["session_id"], "token": creds["token"]})
        assert ended.status_code == 200
        assert ended.json()["end_session"] == "completed"
        status = ended.json()
        for _ in range(50):
            status = client.post(
                "/session/status",
                json={"session_id": creds["session_id"], "token": creds["token"]},
            ).json()
            if status["close_day"] == "completed":
                break
            time.sleep(0.01)
        assert status["close_day"] == "completed"
        again = client.post("/session/end", json={"session_id": creds["session_id"], "token": creds["token"]})
        assert again.status_code == 200
        assert manager.runtime.pipeline.end_calls == 1


def test_disconnect_teardown_does_not_end_or_close_day():
    close_calls = []

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "s", ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
            close_day=lambda **kw: close_calls.append(kw),
        )
        await rt.start()
        await rt.close_transport()  # transport loss/teardown only
        assert rt.pipeline.end_calls == 0
        assert close_calls == []

    asyncio.run(scenario())


def test_audio_frame_conversion_reaches_pcm_callback():
    import av

    packed = np.empty((1, 960), dtype=np.int16)
    packed[0, 0::2] = 1000
    packed[0, 1::2] = 3000
    frame = av.AudioFrame.from_ndarray(packed, format="s16", layout="stereo")
    frame.sample_rate = 48000

    class Track:
        def __init__(self): self.done = False

        async def recv(self):
            if self.done:
                raise gateway.MediaStreamError
            self.done = True
            return frame

    async def scenario():
        ingress = gateway.AiortcIngress(session_id="audio-test", standalone_signaling=False)
        got = []
        ingress.on_audio_chunk = lambda pcm, rate: got.append((pcm, rate))
        ingress._audio_worker = asyncio.create_task(ingress._drain_audio())
        await ingress._consume_audio_track(Track())
        for _ in range(20):
            if got: break
            await asyncio.sleep(0.01)
        await ingress.close()
        assert got and got[0][1] == 48000
        assert got[0][0].ndim == 1 and len(got[0][0]) == 480
        assert got[0][0].dtype == np.int16
        assert np.all(got[0][0] == 2000)

    asyncio.run(scenario())


def test_datachannel_send_from_audio_worker_is_marshaled_to_owner_loop():
    class Channel:
        readyState = "open"

        def __init__(self):
            self.thread_ids = []
            self.sent = []

        def send(self, payload):
            asyncio.get_running_loop()  # proves execution on an event-loop thread
            self.thread_ids.append(threading.get_ident())
            self.sent.append(payload)

    async def scenario():
        ingress = gateway.AiortcIngress(session_id="thread-test", standalone_signaling=False)
        await ingress.start()
        channel = Channel()
        ingress._channels.add(channel)
        owner_thread = threading.get_ident()
        reported = await asyncio.to_thread(ingress.send_ui_intent, "subtitle")
        for _ in range(20):
            if channel.sent:
                break
            await asyncio.sleep(0.01)
        assert reported == 1
        assert channel.sent == ["subtitle"]
        assert channel.thread_ids == [owner_thread]
        assert channel in ingress._channels
        await ingress.close()

    asyncio.run(scenario())


def test_all_durable_pipeline_writers_share_brainlive_id(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_EVIDENCE", str(tmp_path / "evidence"))
    conversation = FakeConversation()
    pipe = runtime_mod.live_pipeline.LivePipeline(
        session_id="transport-only",
        live_session_id="brainlive-real-1",
        person_id="owner",
        db_path=tmp_path / "service.db",
        enable_detector=False,
        enable_worldbrain=True,
        enable_conversation=True,
        conversation_bridge=conversation,
        enable_audio_archive=True,
        enable_replay=True,
        user_profile={"display": "phone_only"},
    )
    assert pipe.session_id == "transport-only"
    assert pipe.live_session_id == "brainlive-real-1"
    assert pipe.worldbrain.live_session_id == "brainlive-real-1"
    assert pipe.scene_adapter.live_session_id == "brainlive-real-1"
    assert pipe.audio_archive.live_session_id == "brainlive-real-1"
    assert pipe.replay.live_session_id == "brainlive-real-1"


def test_explicit_end_waits_inflight_audio_before_flush_and_pipeline_end(monkeypatch):
    order = []

    class SlowPipeline(FakePipeline):
        def on_audio_chunk(self, samples, rate):
            time.sleep(0.08)
            order.append("audio_done")
            return []

        def flush_audio(self):
            order.append("flush")
            return []

        def end_session(self, **_kwargs):
            order.append("pipeline_end")
            super().end_session()

    monkeypatch.setattr(runtime_mod.PhoneOnlyRuntime, "_release_core_live_caches", staticmethod(lambda: None))

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "drain-test",
            ingress_factory=gateway.AiortcIngress,
            pipeline_factory=SlowPipeline,
            close_day=lambda **_: {"status": "completed"},
        )
        await rt.start()
        rt.ingress._audio_worker = asyncio.create_task(rt.ingress._drain_audio())
        rt.ingress._audio.put_nowait((np.zeros(480, dtype=np.int16), 48000))
        await rt.end_and_close_day()
        assert order == ["audio_done", "flush", "pipeline_end"]

    asyncio.run(scenario())


def test_device_privacy_and_structured_intent_reach_runtime_controls():
    class Intents:
        def __init__(self): self.calls = []
        def on_device_action(self, action, payload): self.calls.append((action, payload))

    rt = runtime_mod.PhoneOnlyRuntime(
        "s-menu", ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
        close_day=lambda **_: {"status": "completed"},
    )
    rt.pipeline.intents = Intents()
    rt._on_receipt('{"type":"privacy_state","paused":true}')
    assert rt.privacy_paused is True
    rt._on_receipt('{"type":"device_intent","action":"owner_enroll"}')
    assert rt.pipeline.intents.calls[0][0] == "owner_enroll"


def test_recovery_job_exists_before_brainlive_can_be_marked_ended(tmp_path, monkeypatch):
    db_path = tmp_path / "recovery.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    from mlomega_audio_elite.brainlive_v15 import (
        ensure_brainlive_schema, start_live_session, end_live_session,
    )
    from mlomega_audio_elite.db import connect

    ensure_brainlive_schema()
    live = start_live_session(person_id="owner", title="atomic recovery", mode="live_xr")
    live_id = live["live_session_id"]
    runtime_mod._ensure_recovery_job(
        person_id="owner", live_session_id=live_id, db_path=db_path,
    )
    # This is the historical kill window: BrainLive is ended, but CloseDay has not
    # started. The durable pending job must already exist.
    end_live_session(live_id, notes="simulate kill after end")
    with connect(db_path) as con:
        row = con.execute(
            "SELECT state FROM phoneonly_session_recovery_v19 WHERE live_session_id=?",
            (live_id,),
        ).fetchone()
    assert row["state"] == "pending"

    calls = []
    report = runtime_mod.recover_abandoned_phoneonly_sessions(
        person_id="owner", db_path=db_path,
        close_day_runner=lambda **kw: calls.append(kw) or {"status": "completed"},
    )
    assert calls and calls[0]["live_session_id"] == live_id
    assert live_id in report["recovered"]


def test_runtime_surfaces_best_effort_close_day_maintenance_warning():
    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-maintenance",
            ingress_factory=FakeIngress,
            pipeline_factory=FakePipeline,
            close_day=lambda **_: {
                "status": "completed",
                "maintenance": {
                    "status": "warning",
                    "errors": [],
                    "warnings": ["referenced media exceeds quota"],
                },
            },
        )
        await rt.start()
        status = await rt.end_and_close_day()
        assert status["close_day"] == "completed"
        assert status["close_day_maintenance"] == "warning"
        assert any("maintenance.warning" in error for error in status["recent_errors"])

    asyncio.run(scenario())


def test_product_clip_recorder_is_passed_to_ingress_and_stopped():
    recorders = []

    class _Recorder:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            self.metrics = SimpleNamespace(to_dict=lambda: {"frames_offered": 0})
            recorders.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True
            return {"segments_written": 1}

    class _Ingress(FakeIngress):
        received_recorder = None

        def __init__(self, **kwargs):
            type(self).received_recorder = kwargs.get("clip_recorder")
            super().__init__(**kwargs)

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-clips",
            ingress_factory=_Ingress,
            pipeline_factory=FakePipeline,
            clip_recorder_factory=_Recorder,
        )
        assert recorders[0].started is True
        assert _Ingress.received_recorder is recorders[0]
        await rt.end_session_only()
        assert recorders[0].stopped is True
        assert rt.status()["clip_recording"]["segments_written"] == 1

    asyncio.run(scenario())


def test_audio_pts_is_anchored_and_forwarded_to_three_arg_callback():
    async def scenario():
        ingress = gateway.AiortcIngress(
            session_id="pts-test", standalone_signaling=False, audio_queue_max_chunks=64
        )
        pcm = np.zeros(960, dtype=np.int16)
        first = SimpleNamespace(pts=48000, time_base=Fraction(1, 48000))
        second = SimpleNamespace(pts=48960, time_base=Fraction(1, 48000))
        t1 = ingress._audio_source_timing(first, pcm, 48000)
        t2 = ingress._audio_source_timing(second, pcm, 48000)
        start1 = datetime.fromisoformat(t1["absolute_start"])
        start2 = datetime.fromisoformat(t2["absolute_start"])
        assert abs((start2 - start1).total_seconds() - 0.02) < 0.001
        assert t2["clock_source"] == "webrtc_pts"

        received = []
        ingress.on_audio_chunk = lambda samples, rate, timing: received.append(timing)
        ingress._audio_worker = asyncio.create_task(ingress._drain_audio())
        ingress._audio.put_nowait((pcm, 48000, t2))
        await ingress.close()
        assert received == [t2]

    asyncio.run(scenario())


def test_run_video_executes_sync_pipeline_off_event_loop_thread():
    async def frames():
        yield np.zeros((2, 2, 3), dtype=np.uint8), SimpleNamespace(frame_id="f1")

    class _Ingress:
        def __aiter__(self):
            return frames()

    async def scenario():
        event_thread = threading.get_ident()
        processed_threads = []
        pipe = runtime_mod.live_pipeline.LivePipeline.__new__(runtime_mod.live_pipeline.LivePipeline)
        pipe.ingress = _Ingress()
        pipe.on_video_frame = lambda *_args, **_kwargs: processed_threads.append(threading.get_ident())
        pipe.metrics = lambda: {"ok": True}
        assert await runtime_mod.live_pipeline.LivePipeline.run_video(pipe) == {"ok": True}
        assert processed_threads and processed_threads[0] != event_thread

    asyncio.run(scenario())


def test_live_discourse_close_joins_and_drains_every_batch():
    ingested = []

    discourse = runtime_mod.live_pipeline.live_discourse.LiveDiscourse(
        min_turns=1,
        min_interval_s=0,
        ingest_fn=lambda data: (time.sleep(0.03), ingested.append(data)),
    )
    discourse.note_turn("premier")
    discourse.note_turn("deuxieme")
    discourse.close(timeout=2.0)
    turns = [turn["text"] for batch in ingested for turn in batch["turns"]]
    assert turns == ["premier", "deuxieme"]
    assert discourse._worker is None


def test_abandoned_session_recovery_is_durable_and_retryable(tmp_path, monkeypatch):
    db = tmp_path / "abandoned.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    from mlomega_audio_elite.brainlive_v15 import start_live_session
    from mlomega_audio_elite.db import connect

    session = start_live_session(person_id="owner", mode="live_xr", title="abandoned")
    live_id = session["live_session_id"]
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("night service unavailable")
        return {"status": "completed"}

    first = runtime_mod.recover_abandoned_phoneonly_sessions(
        person_id="owner", db_path=db, close_day_runner=runner
    )
    assert first["status"] == "error"
    with connect(db) as con:
        brain = con.execute(
            "SELECT status FROM brainlive_sessions WHERE live_session_id=?", (live_id,)
        ).fetchone()
        recovery = con.execute(
            "SELECT state,attempts FROM phoneonly_session_recovery_v19 WHERE live_session_id=?",
            (live_id,),
        ).fetchone()
    assert brain["status"] == "ended"
    assert tuple(recovery) == ("error", 1)

    # A fresh process finds the persisted recovery row even though BrainLive is
    # already ended, retries the same session, then seals the marker.
    second = runtime_mod.recover_abandoned_phoneonly_sessions(
        person_id="owner", db_path=db, close_day_runner=runner
    )
    assert second["status"] == "completed"
    assert second["recovered"] == [live_id]
    assert calls[1]["allow_rerun"] is True
    with connect(db) as con:
        recovery = con.execute(
            "SELECT state,attempts,completed_at FROM phoneonly_session_recovery_v19 WHERE live_session_id=?",
            (live_id,),
        ).fetchone()
    assert recovery["state"] == "completed"
    assert recovery["attempts"] == 2
    assert recovery["completed_at"]


def test_inactivity_watchdog_closes_and_runs_close_day():
    class _IdleIngress:
        def stats(self):
            return {"media_idle_seconds": 10.0}

    class _AbandonedRuntime:
        def __init__(self):
            self.ended = False
            self.ingress = _IdleIngress()
            self.end_status = "active"
            self.close_day_status = "not_started"
            self.calls = 0

        async def end_and_close_day(self, **_kwargs):
            self.calls += 1
            self.ended = True
            self.end_status = "completed"
            self.close_day_status = "completed"
            return {}

    async def scenario():
        manager = runtime_mod.SinglePhoneRuntimeManager(
            inactivity_timeout_s=5.0, watchdog_interval_s=0.01
        )
        abandoned = _AbandonedRuntime()
        manager.active = abandoned
        manager.start_watchdog()
        for _ in range(50):
            if abandoned.ended:
                break
            await asyncio.sleep(0.01)
        assert abandoned.calls == 1
        assert manager.watchdog_closures == 1
        await manager.shutdown()

    asyncio.run(scenario())


def test_vad_segment_is_archived_when_asr_unavailable():
    archived = []

    class NoAsr:
        last_infer_ms = 0.0

        def transcribe(self, _seg):
            return {"status": "asr_unavailable", "text": "", "language": None}

    audio = runtime_mod.live_pipeline.audiort.AudioRT(
        transcriber=NoAsr(), on_segment=lambda seg, meta: archived.append((seg, meta))
    )
    intents = audio._handle_segment(np.zeros(1600, dtype=np.float32))
    assert intents[0]["content"]["status"] == "asr_unavailable"
    assert len(archived) == 1
    assert archived[0][1]["asr_status"] == "asr_unavailable"


def test_brainlive_delivery_queue_reaches_phone_datachannel(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "delivery.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    from mlomega_audio_elite.brainlive_v15 import start_live_session
    from mlomega_audio_elite.v18_delivery import enqueue_delivery

    session = start_live_session(person_id="owner", mode="live_xr")
    queued = enqueue_delivery(
        live_session_id=session["live_session_id"],
        source_key="phone-ui-1",
        candidate={"decision": "queue", "message": "Rappel depuis BrainLive", "priority": 0.8},
    )
    ingress = FakeIngress()
    ingress.open_channels = 1
    adapter = runtime_mod.delivery_adapter.DeliveryAdapter(
        renderer=runtime_mod.DataChannelRenderer(ingress)
    )
    sent = asyncio.run(adapter.dispatch_once())
    assert len(sent) == 1
    assert queued["delivery_id"] in ingress.sent[0]
    assert "Rappel depuis BrainLive" in ingress.sent[0]


def test_voice_focus_uses_exactly_one_latest_video_frame():
    pipe = runtime_mod.live_pipeline.LivePipeline(
        enable_detector=False, enable_worldbrain=False, enable_conversation=False,
        enable_intents=False, enable_audio_archive=False,
    )
    seen = []
    pipe.on_focus_request = lambda request, frame, envelope: seen.append(
        (request, frame.copy(), envelope.frame_id)
    ) or {"ok": True}
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    second = np.ones((8, 8, 3), dtype=np.uint8)
    pipe.on_video_frame(first, SimpleNamespace(frame_id="f1", rotation=0, pose_valid=False))
    pipe.on_video_frame(second, SimpleNamespace(frame_id="f2", rotation=0, pose_valid=False))
    result = pipe._route_vision_focus({"kind": "what_is"})
    assert result == {"ok": True}
    assert seen[0][2] == "f2"
    assert np.array_equal(seen[0][1], second)
