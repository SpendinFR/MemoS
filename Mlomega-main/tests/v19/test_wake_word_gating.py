"""Wake-word gating of intent routing (E47-C livrable 4, guide E47 §4).

Policy ``wake_word_policy: open|gated`` (default open):

  * open  → every final transcript is BOTH remembered AND routed to intents
            (build-1 "tout écouté", unchanged);
  * gated → ALL turns are still remembered (conversation_bridge.ingest_segment),
            but only a turn carrying the device is_command flag (KWS wake word,
            agent A) is routed to the IntentRouter;
  * a turn with no flag at all stays open-compatible (routed), so a device that
            never sends the flag is never silenced.

The tests drive LivePipeline._handle_audio_intents with crafted final-turn
intents and spy the IntentRouter + ConversationBridge to assert exactly which
turns route vs. are only remembered. A separate test covers the DataChannel
control-message → command-window latch through the PhoneOnlyRuntime.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "services" / "live-pc"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIVE / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


live_pipeline = load("wwg_live_pipeline", "live_pipeline.py")
runtime_mod = load("wwg_runtime", "phoneonly_runtime.py")


class SpyIntents:
    def __init__(self):
        self.routed = []
        self.metrics = {"intents_routed": 0, "intent_unknown": 0, "grammar_hits": 0,
                        "multiturn_hits": 0, "llm_fallbacks": 0}

    def on_transcript(self, text):
        self.routed.append(text)


class SpyConversation:
    live_session_id = "brainlive-ww"
    metrics = {"conversation_turns": 0}

    def __init__(self):
        self.ingested = []

    def ingest_segment(self, text, **kwargs):
        self.ingested.append(text)
        return {"live_turn_id": len(self.ingested)}


def _final_intent(text, *, is_command=None, uiid="u1"):
    content = {"final": True, "text": text}
    if is_command is not None:
        content["is_command"] = is_command
    return {"ui_intent_id": uiid, "content": content}


def _pipeline(policy):
    pipe = live_pipeline.LivePipeline(
        enable_detector=False, enable_worldbrain=False, enable_conversation=False,
        enable_intents=False, enable_audio_archive=False,
        user_profile={"display": "phone_only", "wake_word_policy": policy},
    )
    pipe.intents = SpyIntents()
    pipe.conversation = SpyConversation()
    return pipe


def test_open_policy_routes_and_remembers_every_turn():
    pipe = _pipeline("open")
    assert pipe.wake_word_policy == "open"
    pipe._handle_audio_intents([_final_intent("cache tout")])
    pipe._handle_audio_intents([_final_intent("il fait beau aujourd'hui", uiid="u2")])
    # Both routed AND both remembered.
    assert pipe.intents.routed == ["cache tout", "il fait beau aujourd'hui"]
    assert pipe.conversation.ingested == ["cache tout", "il fait beau aujourd'hui"]
    assert pipe.metrics()["turns_routed"] == 2
    assert pipe.metrics()["turns_gated_out"] == 0


def test_gated_routes_only_command_turns_but_remembers_all():
    pipe = _pipeline("gated")
    assert pipe.wake_word_policy == "gated"
    # (a) command turn (is_command=True) → routed + remembered.
    pipe._handle_audio_intents([_final_intent("zoom", is_command=True, uiid="a")])
    # (b) background turn (is_command=False) → NOT routed, still remembered.
    pipe._handle_audio_intents([_final_intent("j'ai mangé une pomme", is_command=False, uiid="b")])
    assert pipe.intents.routed == ["zoom"]
    assert pipe.conversation.ingested == ["zoom", "j'ai mangé une pomme"]
    m = pipe.metrics()
    assert m["turns_routed"] == 1
    assert m["turns_gated_out"] == 1


def test_gated_turn_without_flag_is_open_compatible():
    """A gated device that sends no is_command flag at all behaves like open
    (the turn is routed) — the fallback compat path."""
    pipe = _pipeline("gated")
    pipe._handle_audio_intents([_final_intent("menu")])  # no is_command key
    assert pipe.intents.routed == ["menu"]
    assert pipe.conversation.ingested == ["menu"]


def test_current_phone_gate_makes_untagged_pc_asr_memory_only():
    pipe = _pipeline("gated")
    pipe.set_device_gate_authoritative(True)
    pipe._handle_audio_intents([_final_intent("conversation ambiante")])
    assert pipe.intents.routed == []
    assert pipe.conversation.ingested == ["conversation ambiante"]


def test_brainlive_receives_capture_timestamps_and_temp_wav_is_removed(tmp_path):
    pipe = _pipeline("open")
    calls = []

    class _Conversation(SpyConversation):
        def ingest_segment(self, text, **kwargs):
            calls.append((text, kwargs))
            return {"live_turn_id": "turn-1"}

    pipe.conversation = _Conversation()
    wav = tmp_path / "seg_test.wav"
    wav.write_bytes(b"RIFF")
    intent = _final_intent("bonjour")
    intent["content"].update({
        "timestamp_start": "2026-07-10T10:00:04+00:00",
        "timestamp_end": "2026-07-10T10:00:05+00:00",
        "duration_s": 1.0,
    })
    pipe._segment_clips[intent["ui_intent_id"]] = str(wav)
    pipe._handle_audio_intents([intent])
    assert calls[0][1]["timestamp_start"] == "2026-07-10T10:00:04+00:00"
    assert calls[0][1]["timestamp_end"] == "2026-07-10T10:00:05+00:00"
    assert not wav.exists()


def test_brainlive_failure_is_retried_then_visible_in_metrics():
    pipe = _pipeline("open")

    class _BrokenConversation(SpyConversation):
        def __init__(self):
            self.calls = 0

        def ingest_segment(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("db unavailable")

    broken = _BrokenConversation()
    pipe.conversation = broken
    pipe._handle_audio_intents([_final_intent("garde ceci")])
    assert broken.calls == 3
    metrics = pipe.metrics()
    assert metrics["pipeline_errors"] == 1
    assert "conversation.ingest_segment" in metrics["pipeline_recent_errors"][0]


def test_semantic_processing_worker_does_not_block_audio_producer():
    pipe = _pipeline("open")
    entered = threading.Event()
    release = threading.Event()

    class _SlowConversation(SpyConversation):
        def ingest_segment(self, text, **kwargs):
            entered.set()
            assert release.wait(2.0)
            return super().ingest_segment(text, **kwargs)

    pipe.conversation = _SlowConversation()
    pipe.defer_final_processing = True
    start = time.perf_counter()
    pipe._enqueue_final_processing([_final_intent("tour lent")])
    assert (time.perf_counter() - start) < 0.1
    assert entered.wait(1.0)
    release.set()
    pipe.drain_final_processing(timeout_s=2.0)
    pipe._stop_final_worker(timeout_s=2.0)
    assert pipe.conversation.ingested == ["tour lent"]


def test_device_transcript_routes_exact_command_once_not_next_pc_turn():
    pipe = _pipeline("gated")
    payload = {
        "type": "device_transcript", "segment_id": "dev-1",
        "text": "ouvre le menu", "is_final": True, "is_command": True,
        "start_ms": 100, "end_ms": 900,
    }
    pipe.on_device_transcript(payload)
    pipe.on_device_transcript(payload)
    pipe._handle_audio_intents([_final_intent("ouvre le menu")])
    assert pipe.intents.routed == ["ouvre le menu"]
    assert pipe.conversation.ingested == ["ouvre le menu"]


def test_gated_command_window_latch_routes_next_turn():
    """arm_command_window() (wake word fired) routes exactly the next turn — it
    overrides an explicit is_command=False, and is consumed after one command."""
    pipe = _pipeline("gated")
    t = [1000.0]
    pipe.arm_command_window(now=t[0])
    # Next turn within the window is routed even if it is flagged background.
    assert pipe._should_route_intent({"text": "traduis", "is_command": False}, now=t[0] + 1.0) is True
    # The window is consumed: a following background turn is gated out again.
    assert pipe._should_route_intent({"text": "et après", "is_command": False}, now=t[0] + 2.0) is False
    assert pipe.wake_word_metrics["command_windows_armed"] == 1


def test_gated_command_window_expires():
    pipe = _pipeline("gated")
    pipe._command_window_s = 8.0
    pipe.arm_command_window(now=100.0)
    # A background turn after the window TTL is not routed.
    assert pipe._should_route_intent({"text": "trop tard", "is_command": False}, now=120.0) is False


def test_invalid_policy_falls_back_to_open():
    pipe = _pipeline("nonsense")
    assert pipe.wake_word_policy == "open"


def test_runtime_control_message_arms_command_window():
    """A DataChannel {"type":"control","is_command":true} message (agent A) arms
    the wake-word window through the runtime's receipt handler."""
    armed = {"n": 0}

    class FakeIngress:
        def __init__(self, **_):
            self.on_audio_chunk = None
            self.on_receipt = None
            self.on_datachannel_open = None
            self.sent = []

        def send_ui_intent(self, p):
            return 0

        async def close(self):
            return None

    class FakePipeline:
        def __init__(self, *, ingress, **_):
            self.ingress = ingress
            self.conversation = SpyConversation()

        def arm_command_window(self, **_):
            armed["n"] += 1

        def metrics(self):
            return {"conversation_turns": 0}

        def on_audio_chunk(self, *_):
            return []

    rt = runtime_mod.PhoneOnlyRuntime(
        "s", ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
        close_day=lambda **_: {"status": "completed"},
    )
    # A control message arms the window.
    rt._on_receipt('{"type":"control","action":"wake_word","is_command":true}')
    assert armed["n"] == 1
    # A control message that is explicitly not a command does not arm.
    rt._on_receipt('{"type":"control","is_command":false}')
    assert armed["n"] == 1
    # A plain (non-control) receipt does not arm and does not crash.
    rt._on_receipt('{"ui_intent_id":"x","event":"shown"}')
    assert armed["n"] == 1


def test_push_wake_word_retries_until_matching_device_ack():
    """E58: the PC pushes the owner-chosen wake word to the device as a
    set_wake_word device_command, once per session (idempotent), so it can be
    changed without an APK rebuild."""
    import json as _json

    pipe = _pipeline("gated")
    pipe.wake_word = "viki"
    sent: list[str] = []

    class _Ingress:
        open = False

        def send_ui_intent(self, payload):
            sent.append(payload)
            return 1 if self.open else 0

    ingress = _Ingress()
    pipe.ingress = ingress
    assert pipe.push_wake_word() is False
    assert pipe.push_wake_word() is False
    ingress.open = True
    assert pipe.push_wake_word() is True

    cmds = [_json.loads(s) for s in sent]
    set_words = [c for c in cmds if c.get("action") == "set_wake_word"]
    assert len(set_words) == 3
    delivered = set_words[-1]
    assert delivered["type"] == "device_command"
    assert delivered["word"] == "viki"
    assert delivered["command_id"]
    assert pipe.confirm_wake_word("wrong", True) is False
    assert pipe.confirm_wake_word(delivered["command_id"], True) is True
    assert pipe.push_wake_word() is True
    assert len(sent) == 3


def test_runtime_open_pushes_wake_word_enables_gate_and_tts():
    import asyncio

    calls = []

    class FakeIngress:
        def __init__(self, **_):
            self.on_audio_chunk = None
            self.on_receipt = None
            self.on_datachannel_open = None

        def send_ui_intent(self, _):
            return 1

        async def close(self):
            return None

    class FakePipeline:
        def __init__(self, *, ingress, **kwargs):
            self.ingress = ingress
            self.conversation = SpyConversation()
            calls.append(("enable_tts", kwargs.get("enable_tts")))

        def set_device_gate_authoritative(self, value):
            calls.append(("gate", value))

        def push_wake_word(self):
            calls.append(("wake", True))
            return True

        def deliver_morning_briefing(self):
            calls.append(("briefing", True))

        def metrics(self):
            return {"conversation_turns": 0}

        def on_audio_chunk(self, *_):
            return []

    rt = runtime_mod.PhoneOnlyRuntime(
        "s", ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
        close_day=lambda **_: {"status": "completed"},
    )

    async def empty_dispatch():
        return []

    rt._dispatch_deliveries = empty_dispatch
    asyncio.run(rt._on_datachannel_open())
    assert ("enable_tts", True) in calls
    assert ("gate", True) in calls
    assert ("wake", True) in calls


def test_runtime_routes_wake_ack_and_exact_device_transcript():
    calls = []

    class FakeIngress:
        def __init__(self, **_):
            self.on_audio_chunk = None
            self.on_receipt = None
            self.on_datachannel_open = None

        def send_ui_intent(self, _):
            return 1

        async def close(self):
            return None

    class FakePipeline:
        def __init__(self, *, ingress, **_):
            self.ingress = ingress
            self.conversation = SpyConversation()

        def confirm_wake_word(self, command_id, ok):
            calls.append(("ack", command_id, ok))

        def on_device_transcript(self, payload):
            calls.append(("transcript", payload["segment_id"], payload["text"]))

        def metrics(self):
            return {"conversation_turns": 0}

        def on_audio_chunk(self, *_):
            return []

    rt = runtime_mod.PhoneOnlyRuntime(
        "s", ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
        close_day=lambda **_: {"status": "completed"},
    )
    rt._on_receipt('{"type":"device_command_result","command_id":"w1",'
                   '"action":"set_wake_word","ok":true}')
    rt._on_receipt('{"type":"device_transcript","segment_id":"d1",'
                   '"text":"menu","is_command":true,"is_final":true}')
    assert calls == [("ack", "w1", True), ("transcript", "d1", "menu")]


def test_routed_short_text_reply_emits_tts_audio():
    sent = []
    pipe = _pipeline("open")
    pipe.enable_tts = True
    pipe._tts_on = True

    class FakeTts:
        def speak(self, text, lang="fr"):
            assert text == "Bonjour"
            return b"RIFF-valid-enough-for-contract"

    class FakeIngress:
        def send_ui_intent(self, payload):
            sent.append(payload)
            return 1

    pipe.tts = FakeTts()
    pipe.ingress = FakeIngress()
    pipe._speak_routed_reply({
        "ui_intent": {"content": {"text": "Bonjour"}}
    })
    assert any('"type": "tts_audio"' in payload for payload in sent)
