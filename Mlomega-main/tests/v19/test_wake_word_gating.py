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
