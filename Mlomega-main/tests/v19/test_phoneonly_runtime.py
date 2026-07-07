from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import threading
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
        rt.ingress.on_audio_chunk(np.zeros(480, dtype=np.int16), 48000)
        first = await rt.end_and_close_day()
        second = await rt.end_and_close_day()
        assert rt.pipeline.end_calls == 1
        assert first["end_session"] == second["end_session"] == "completed"
        assert close_calls == [{"person_id": "owner", "live_session_id": "brainlive-real-1"}]

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
        assert health.json()["status"] == "ready"
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
