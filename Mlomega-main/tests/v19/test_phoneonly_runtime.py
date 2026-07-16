from __future__ import annotations

import asyncio
import importlib.util
import json
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


def test_session_end_returns_fast_with_fine_intel_still_pending_and_close_day_gated():
    """E64-i chantier 1: /session/end must not block on the fine-intel queue.

    The remaining backlog is drained in the BACKGROUND; CloseDay only starts once
    that drain completes. The phone therefore never waits minutes on the queue.
    """
    order = []
    drain_release = asyncio.Event()

    class SlowDrainPipeline(FakePipeline):
        async def _wait(self):
            await drain_release.wait()

        def drain_deferred_semantics(self):
            # Runs in a worker thread (asyncio.to_thread). Block until released.
            fut = asyncio.run_coroutine_threadsafe(self._wait(), self._loop)
            fut.result()
            order.append("fine_intel_drained")
            return {"status": "completed", "remaining": 0}

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-fast-end",
            ingress_factory=FakeIngress,
            pipeline_factory=SlowDrainPipeline,
            close_day=lambda **_: order.append("close_day") or {"status": "completed"},
        )
        rt.pipeline._loop = asyncio.get_running_loop()
        await rt.start()

        # /session/end returns while the fine-intel drain is still running.
        ended = await rt.end_session_only()
        assert ended["end_session"] == "completed"
        assert rt.fine_intel_drain_status == "running"
        assert "fine_intel_drained" not in order

        # CloseDay is gated: it must not start before the background drain ends.
        close_task = asyncio.create_task(rt.run_close_day())
        await asyncio.sleep(0.05)
        assert "close_day" not in order, "close-day overtook the pending fine-intel drain"

        # Release the drain -> it finishes -> close-day is allowed to run.
        drain_release.set()
        await close_task
        assert order == ["fine_intel_drained", "close_day"]
        assert rt.status()["fine_intel_drain"] == "completed"

    asyncio.run(scenario())


def test_recovery_job_durable_before_fast_end_returns(tmp_path, monkeypatch):
    """The durable recovery boundary exists the moment /session/end returns.

    A kill during the background fine-intel drain therefore stays recoverable: the
    pending recovery row is already committed and startup recovery reprocesses it.
    """
    db_path = tmp_path / "fast-end-recovery.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    from mlomega_audio_elite.brainlive_v15 import ensure_brainlive_schema, start_live_session
    from mlomega_audio_elite.db import connect

    ensure_brainlive_schema()

    class RealSessionConversation(FakeConversation):
        def __init__(self, live_id):
            self.live_session_id = live_id

    class ProductLikePipeline(FakePipeline):
        def __init__(self, *, ingress, **kwargs):
            super().__init__(ingress=ingress, **kwargs)
            live = start_live_session(person_id="owner", mode="live_xr", title="fast-end")
            self.conversation = RealSessionConversation(live["live_session_id"])

        def drain_deferred_semantics(self):
            return {"status": "completed", "remaining": 0}

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-durable-end",
            person_id="owner",
            db_path=db_path,
            ingress_factory=FakeIngress,
            pipeline_factory=ProductLikePipeline,
            close_day=lambda **_: {"status": "completed"},
        )
        # Force the product recovery-job path even with an injected pipeline.
        rt._product_pipeline = True
        await rt.start()
        ended = await rt.end_session_only()
        assert ended["end_session"] == "completed"
        live_id = rt.live_session_id
        with connect(db_path) as con:
            row = con.execute(
                "SELECT state FROM phoneonly_session_recovery_v19 WHERE live_session_id=?",
                (live_id,),
            ).fetchone()
        assert row is not None and row["state"] == "pending"
        # Await the background drain so no task leaks past the test.
        if rt.fine_intel_drain_task is not None:
            await rt.fine_intel_drain_task

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


def test_audio_worker_losslessly_batches_adjacent_pcm_and_preserves_timing():
    async def scenario():
        ingress = gateway.AiortcIngress(
            session_id="audio-batch", standalone_signaling=False,
            audio_queue_max_chunks=64, audio_batch_max_chunks=8,
        )
        got = []
        ingress.on_audio_chunk = lambda pcm, rate, timing: got.append((pcm.copy(), rate, timing))
        for idx in range(8):
            pcm = np.full(480, idx, dtype=np.int16)
            ingress._audio.put_nowait((pcm, 48000, {
                "absolute_start": f"start-{idx}",
                "absolute_end": f"end-{idx}",
                "duration_s": 0.01,
                "clock_source": "webrtc_pts",
            }))
        ingress._audio_worker = asyncio.create_task(ingress._drain_audio())
        await ingress.drain_audio(timeout_s=2.0)
        assert len(got) == 1
        pcm, rate, timing = got[0]
        assert rate == 48000 and len(pcm) == 8 * 480
        for idx in range(8):
            assert np.all(pcm[idx * 480:(idx + 1) * 480] == idx)
        assert timing["absolute_start"] == "start-0"
        assert timing["absolute_end"] == "end-7"
        assert abs(timing["duration_s"] - 0.08) < 1e-9
        assert ingress.stats()["audio_batch_chunks_peak"] == 8
        await ingress.close()

    asyncio.run(scenario())


def test_audio_drain_timeout_is_diagnostic():
    async def scenario():
        ingress = gateway.AiortcIngress(session_id="audio-timeout", standalone_signaling=False)
        ingress._audio.put_nowait((np.zeros(480, dtype=np.int16), 48000, None))
        try:
            await ingress.drain_audio(timeout_s=0.01)
            assert False, "drain without worker must time out"
        except TimeoutError as exc:
            assert "queued=1" in str(exc) and "dropped=0" in str(exc)

    asyncio.run(scenario())


def test_runtime_audio_callback_does_not_scan_all_metrics_per_chunk():
    class CountedPipeline(FakePipeline):
        def __init__(self, *, ingress, **kwargs):
            super().__init__(ingress=ingress, **kwargs)
            self.metric_calls = 0

        def metrics(self):
            self.metric_calls += 1
            return super().metrics()

        def on_audio_chunk(self, samples, rate):
            self.audio_calls.append((samples, rate))
            return [{"content": {"final": True, "text": "bonjour"}}]

    rt = runtime_mod.PhoneOnlyRuntime(
        "no-metrics-scan", ingress_factory=FakeIngress, pipeline_factory=CountedPipeline,
        close_day=lambda **_: {"status": "completed"},
    )
    out = rt._on_audio_chunk(np.zeros(480, dtype=np.int16), 48000)
    assert out and rt.final_segments == 1
    assert rt.pipeline.metric_calls == 0


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


def test_scene_delta_drives_real_scene_adapter_delivery_queue(tmp_path, monkeypatch):
    """PhoneOnly scene cadence, not an isolated adapter call, must fire H1 cues."""
    db_path = tmp_path / "service.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    pipe = runtime_mod.live_pipeline.LivePipeline(
        session_id="transport-scene",
        live_session_id="brainlive-scene",
        person_id="owner",
        db_path=db_path,
        enable_detector=False,
        enable_worldbrain=True,
        enable_conversation=False,
        user_profile={"display": "phone_only"},
    )
    pipe.worldbrain.config.promote_min_observations = 1
    pipe.worldbrain.config.promote_min_confidence = 0.3
    delta = {
        "session_id": "brainlive-scene", "source_frame_id": "person-1",
        "entities": [{
            "track_id": "track-alice", "kind": "person", "label": "person",
            "bbox": [0, 0, 100, 300], "confidence": 0.9, "visibility": 1.0,
        }],
        "relations": [], "changes": [], "map_quality": 0.0,
        "evidence_refs": ["frame:person-1"],
    }
    pipe._on_scene_delta(delta)
    entity_id = pipe.worldbrain._track_to_entity["track-alice"]
    pipe.scene_adapter.known_people[entity_id] = {"name": "Alice", "relation": "amie"}
    pipe.scene_adapter._last_build_ts = 0.0
    pipe._on_scene_delta({**delta, "source_frame_id": "person-2",
                          "evidence_refs": ["frame:person-2"]})

    from mlomega_audio_elite.db import connect
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT message FROM brainlive_intervention_delivery_queue "
            "WHERE live_session_id='brainlive-scene'"
        ).fetchall()
        dedupes = con.execute(
            "SELECT candidate_fingerprint FROM brainlive_intervention_delivery_dedupes"
        ).fetchall()
    assert any("Alice" in str(r["message"]) for r in rows), rows
    assert dedupes
    assert pipe.scene_adapter.metrics["deliveries_enqueued"] >= 1


def test_named_person_appearance_change_reaches_proactive_queue_across_sessions(tmp_path, monkeypatch):
    """Named crop -> VLM attributes -> durable diff -> scene adapter -> H1 queue."""
    db_path = tmp_path / "appearance.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))

    class AppearanceVlm:
        def __init__(self, clothing): self.clothing = clothing
        def describe(self, _crop, prompt=""):
            return {"status": "ok", "text": json.dumps({
                "appearance": "adulte", "clothing": self.clothing,
                "age_apparent": "adulte", "role_hint": "",
            })}

    def make_pipe(session_id, track_id, clothing):
        pipe = runtime_mod.live_pipeline.LivePipeline(
            session_id=f"transport-{session_id}", live_session_id=session_id,
            person_id="owner", db_path=db_path, enable_detector=False,
            enable_worldbrain=True, enable_conversation=False,
            user_profile={"display": "phone_only"},
        )
        pipe.enable_fine_intel = True
        pipe.attribute_memory = runtime_mod.live_pipeline.attribute_memory.AttributeMemory(
            person_id="owner", worldbrain=pipe.worldbrain,
            service_db_path=db_path,
        )
        pipe.fusion = SimpleNamespace(_track_identity={track_id: "alice"})
        pipe.stranger_profiler = runtime_mod.live_pipeline.stranger_profile.StrangerProfiler(
            vlm=AppearanceVlm(clothing), worldbrain=pipe.worldbrain,
            config=runtime_mod.live_pipeline.stranger_profile.StrangerConfig(stable_seconds=0.0),
        )
        return pipe

    first = make_pipe("appearance-one", "person-a", "chaussures noires")
    first.worldbrain.config.promote_min_observations = 1
    promoted = first.worldbrain.ingest_scene_delta({
        "session_id": "appearance-one", "source_frame_id": "a",
        "entities": [{"track_id": "person-a", "kind": "person", "label": "person",
                      "bbox": [0, 0, 40, 80], "confidence": 0.9}],
        "relations": [], "changes": [], "evidence_refs": ["frame:a"],
    })["promoted"][0]
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    person_a = {"track_id": "person-a", "label": "person", "bbox": [0, 0, 40, 80]}
    first._run_stranger_profiles(frame, {"entities": [person_a]})
    first._run_stranger_profiles(frame, {"entities": [person_a]})

    second = make_pipe("appearance-two", "person-b", "chaussures rouges")
    second.worldbrain._track_to_entity["person-b"] = promoted
    second.scene_adapter.known_people[promoted] = {"name": "Alice", "relation": "amie"}
    person_b = {"track_id": "person-b", "label": "person", "bbox": [0, 0, 40, 80]}
    second._run_stranger_profiles(frame, {"entities": [person_b]})
    second._run_stranger_profiles(frame, {"entities": [person_b]})

    from mlomega_audio_elite.db import connect
    with connect(db_path) as con:
        changes = con.execute(
            "SELECT event_type,observation_json FROM visual_events_v19 "
            "WHERE person_id='owner' AND event_type='change_attribute_changed'"
        ).fetchall()
        cues = con.execute(
            "SELECT message FROM brainlive_intervention_delivery_queue "
            "WHERE live_session_id='appearance-two'"
        ).fetchall()
    assert any("chaussures rouges" in str(r["observation_json"]) for r in changes), changes
    assert any("Alice" in str(r["message"]) for r in cues), cues
    assert second.scene_adapter.metrics["attribute_change_cues"] >= 1


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


def _command_pipeline_with_intents(intents, ingress):
    pipe = runtime_mod.live_pipeline.LivePipeline(
        ingress=ingress, enable_detector=False, enable_worldbrain=False,
        enable_conversation=False, enable_intents=False, enable_live_discourse=False,
        enable_audio_archive=False,
    )
    pipe.intents = intents
    pipe.set_wake_word_policy("gated")
    return pipe


def test_command_trace_emits_accepted_then_completed():
    """E64-i chantier 3: a normal command yields accepted then completed."""
    ingress = FakeIngress()
    ingress.open_channels = 1

    class OkIntents:
        def on_transcript(self, _text):
            return {"intent": "find", "handled": True,
                    "result": {"status": "ok", "component": "worldbrain"}}

    pipe = _command_pipeline_with_intents(OkIntents(), ingress)
    routed = pipe.on_device_transcript({
        "type": "device_transcript", "segment_id": "cmd-1",
        "text": "où sont mes clés ?", "is_final": True, "is_command": True,
    })
    assert routed is not None

    traces = [json.loads(raw) for raw in ingress.sent
              if json.loads(raw).get("type") == "command_execution_trace"]
    phases = [t["phase"] for t in traces]
    assert phases == ["accepted", "completed"]
    assert traces[0]["status"] == "accepted" and traces[0]["handled"] is False
    assert traces[1]["status"] == "completed" and traces[1]["handled"] is True


def test_command_trace_emits_accepted_then_failed_when_handler_raises():
    """A blocking/raising command still leaves accepted + a terminal failed trace."""
    ingress = FakeIngress()
    ingress.open_channels = 1

    class RaisingIntents:
        def on_transcript(self, _text):
            raise RuntimeError("ask_memory blocked")

    pipe = _command_pipeline_with_intents(RaisingIntents(), ingress)
    routed = pipe.on_device_transcript({
        "type": "device_transcript", "segment_id": "cmd-2",
        "text": "interroge ma memoire qui est Karim", "is_final": True, "is_command": True,
    })
    assert routed is None

    traces = [json.loads(raw) for raw in ingress.sent
              if json.loads(raw).get("type") == "command_execution_trace"]
    phases = [t["phase"] for t in traces]
    assert phases == ["accepted", "failed"], phases
    # Never zero traces: the command is provably not invisible.
    assert traces[0]["status"] == "accepted"
    assert traces[-1]["status"] == "failed"


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


def test_visual_translation_ocr_is_forwarded_to_device_reflex():
    ingress = FakeIngress()
    ingress.open_channels = 1
    pipe = runtime_mod.live_pipeline.LivePipeline(
        ingress=ingress, enable_detector=False, enable_worldbrain=False,
        enable_conversation=False, enable_intents=False, enable_live_discourse=False,
    )
    pipe.vision_focus_handler = lambda request: {
        "component": "lens_window",
        "content": {"kind": "ocr", "text": "Hello world", "lines": []},
    }

    result = pipe._route_vision_focus({
        "kind": "ocr", "translate": True, "language": "fr",
    })

    assert result["content"]["translation_status"] == "sent_to_device"
    sent = [json.loads(raw) for raw in ingress.sent]
    command = next(item for item in sent if item.get("action") == "translate_text")
    assert command["text"] == "Hello world"
    assert command["source_language"] == "en"
    assert command["target_language"] == "fr"


def test_viki_context_callbacks_use_live_product_state():
    pipe = runtime_mod.live_pipeline.LivePipeline(
        enable_detector=False, enable_worldbrain=False, enable_conversation=False,
        enable_intents=False, enable_live_discourse=False,
    )
    snapshot = {
        "recent_changes": [{"label": "clés déplacées", "evidence_refs": ["frame:f2"]}],
    }
    pipe.worldbrain = SimpleNamespace(snapshot=lambda: snapshot)
    pipe.scene_adapter = SimpleNamespace(_identify_people=lambda _snap: [{
        "identified": True, "name": "Karim", "confidence": 0.91, "entity_id": "person-karim",
    }])
    ingested = []
    pipe.conversation = SimpleNamespace(ingest_segment=lambda text, **kwargs: ingested.append(
        (text, kwargs)
    ) or {"live_turn_id": "turn-explicit"})

    who = pipe._who_is_active()
    changes = pipe._recent_scene_changes()
    remembered = pipe._remember_explicit_fact("demain je dois racheter des piles")

    assert who["content"]["text"] == "C'est Karim."
    assert who["truth_level"] == "observed"
    assert changes["content"]["changes"] == snapshot["recent_changes"]
    assert changes["evidence_refs"] == ["frame:f2"]
    assert remembered["truth_level"] == "remembered"
    assert ingested[0][0] == "demain je dois racheter des piles"
    assert ingested[0][1]["speaker_person_id"] == pipe.person_id


def test_phone_command_where_are_glasses_reaches_durable_spatial_answer(tmp_path, monkeypatch):
    """DataChannel transcript -> IntentRouter -> durable WorldBrain -> downlink."""
    db = tmp_path / "spatial-product.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    first = runtime_mod.live_pipeline.LivePipeline(
        session_id="transport-old", live_session_id="brain-old", person_id="me",
        db_path=db, enable_detector=False, enable_worldbrain=True,
        enable_conversation=False, enable_intents=False, enable_live_discourse=False,
    )
    first.worldbrain.config.promote_min_observations = 1
    first.worldbrain.ingest_scene_delta({
        "session_id": "brain-old", "source_frame_id": "frame-glasses",
        "entities": [{
            "track_id": "track-glasses", "kind": "object", "label": "lunettes",
            "bbox": [20, 30, 90, 60], "confidence": 0.88,
            "visibility": 1.0, "age": 1,
        }],
        "relations": [], "changes": [], "map_quality": 0.0,
        "evidence_refs": ["frame:frame-glasses"],
    })
    first.worldbrain.end_session(place_hint="salon")

    ingress = FakeIngress()
    ingress.open_channels = 1
    current = runtime_mod.live_pipeline.LivePipeline(
        session_id="transport-new", live_session_id="brain-new", person_id="me",
        db_path=db, ingress=ingress, enable_detector=False, enable_worldbrain=True,
        enable_conversation=False, enable_intents=True, enable_live_discourse=False,
        user_profile={"display": "phone_only", "llm": "ollama_local"},
    )
    current.set_wake_word_policy("gated")
    routed = current.on_device_transcript({
        "type": "device_transcript", "segment_id": "cmd-spatial-1",
        "text": "où sont mes lunettes ?", "is_final": True, "is_command": True,
    })

    assert routed is not None and routed["intent"] == "find"
    pushed = [json.loads(raw) for raw in ingress.sent]
    answer = next(item for item in pushed if item.get("producer") == "worldbrain")
    assert answer["content"]["state"] == "last_seen"
    assert answer["content"]["place_hint"] == "salon"
    assert answer["content"]["source"] == "durable_registry"
    assert answer["truth_level"] == "remembered"
    assert answer.get("bearing") is None  # a new session cannot invent an arrow
    assert current.metrics()["spatial_find_durable_hits"] == 1


def test_close_day_subprocess_reports_structured_blocker_not_stderr_warning(tmp_path, monkeypatch):
    from mlomega_audio_elite import runtime_environment_v19

    monkeypatch.setattr(
        runtime_environment_v19,
        "configure_windows_cuda_dlls",
        lambda _root: (True, {"status": "ok"}),
    )
    monkeypatch.setattr(runtime_environment_v19, "sanitize_blackhole_proxy_env", lambda: [])
    monkeypatch.setattr(
        runtime_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2,
            stdout=json.dumps({
                "status": "blocked",
                "error": "deep_vision returned blocked",
                "run_id": "close-1",
                "stages": {"deep_vision": {"status": "blocked"}},
            }) + "\n",
            stderr="FutureWarning: torch.load noise only",
        ),
    )

    try:
        runtime_mod._run_close_day_subprocess(
            person_id="me", live_session_id="brain-1", db_path=tmp_path / "memory.db"
        )
        raise AssertionError("blocked subprocess must raise")
    except RuntimeError as exc:
        detail = str(exc)
    assert "deep_vision returned blocked" in detail
    assert "close-1" in detail
    assert "torch.load" not in detail
