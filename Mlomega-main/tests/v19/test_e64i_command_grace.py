from __future__ import annotations

"""E64-i (Codex decision b) — bounded command grace after /session/end.

After the fast /session/end ACK, the background drain grants a SHORT grace
(``MLOMEGA_COMMAND_GRACE_S``) for every in-flight device command, then splits
them by their ROUTED intent:

  * INTERACTIVE (help/next-step/ask_memory/one-shot VLM): abandoned after the
    grace with a durable ``cancelled_session_end`` trace — never silent, never
    blocking CloseDay.
  * DURABLE (enrollment/identity/remember/owner-voice): NEVER cancelled; awaited
    up to the existing budget (``MLOMEGA_FINAL_DRAIN_TIMEOUT_S``). A durable
    command that overruns the budget raises a noisy TimeoutError (retryable),
    exactly as before.

Every phase (accepted/completed/failed/cancelled_session_end) is persisted to
``command_execution_traces_v19`` so the Gate B 13/13 correlation and verdict 1.3
are verifiable from the DB even with the DataChannel closed.

All fakes; no real LLM.
"""

import asyncio
import importlib.util
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "services" / "live-pc"
SRC = ROOT / "src"
for _p in (ROOT, SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIVE / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


live_pipeline = _load("e64i_grace_live_pipeline", "live_pipeline.py")
runtime_mod = _load("e64i_grace_runtime", "phoneonly_runtime.py")


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #
class _SpyConversation:
    live_session_id = "brainlive-grace-1"
    metrics = {"conversation_turns": 0}

    def end_session(self, **_kwargs):
        return {"status": "ended"}


class _Context:
    """Minimal stand-in for intent_router.IntentContext, carrying the routing hook."""

    def __init__(self):
        self.on_intent_resolved = None

    def note(self, intent):
        if self.on_intent_resolved is not None:
            self.on_intent_resolved(intent)


class _BlockingIntents:
    """An intent router whose handler blocks until released, but which RESOLVES the
    intent first (exactly like the real router: the intent label is decided, its
    ``context.note`` fires, THEN the slow handler runs). This is what lets the drain
    classify durable vs interactive while the command is still in flight."""

    def __init__(self, *, intent: str, gate: threading.Event, handled: bool = True):
        self.intent = intent
        self.gate = gate
        self.handled = handled
        self.metrics = {"intents_routed": 0}
        self.context = _Context()

    def on_transcript(self, _text):
        # Intent is decided up-front (routing), BEFORE the slow handler blocks.
        self.context.note(self.intent)
        self.gate.wait(timeout=30.0)  # the slow handler (VLM/LLM) still in flight
        return {"intent": self.intent, "handled": self.handled, "result": {"status": "ok"}}


def _pipeline(db_path: Path, intents) -> object:
    pipe = live_pipeline.LivePipeline(
        enable_detector=False, enable_worldbrain=False, enable_conversation=False,
        enable_intents=False, enable_audio_archive=False,
        user_profile={"display": "phone_only", "wake_word_policy": "gated"},
        db_path=db_path,
    )
    pipe.intents = intents
    # Wire the routing hook exactly as the product pipeline does when it builds
    # the real IntentRouter (so an in-flight command is classified at routing time).
    context = getattr(intents, "context", None)
    if context is not None:
        context.on_intent_resolved = pipe._on_intent_resolved_for_current_command
    pipe.conversation = _SpyConversation()
    pipe.live_session_id = _SpyConversation.live_session_id
    pipe.person_id = "owner"
    pipe.set_device_gate_authoritative(True)
    return pipe


class _ReceiptIngress:
    """Mirrors the production gateway receipt mechanism: each device transcript is
    executed as an asyncio task via to_thread, and drain_receipts awaits them with
    the same non-cancelling ``asyncio.wait`` semantics used by the real gateway."""

    def __init__(self, **_kwargs):
        self.on_audio_chunk = None
        self._receipt_tasks: set[asyncio.Task] = set()
        self.peer_state = "new"
        self.sent = []

    def dispatch_transcript(self, pipeline, payload) -> asyncio.Task:
        task = asyncio.create_task(
            asyncio.to_thread(pipeline.on_device_transcript, payload)
        )
        self._receipt_tasks.add(task)
        task.add_done_callback(self._receipt_tasks.discard)
        return task

    async def drain_receipts(self, *, timeout_s: float = 5.0) -> None:
        pending = list(self._receipt_tasks)
        if not pending:
            return
        _done, still = await asyncio.wait(pending, timeout=max(0.1, float(timeout_s)))
        if still:
            raise asyncio.TimeoutError(f"{len(still)} receipt task(s) still in flight")

    def send_ui_intent(self, _payload):
        return 0

    def stats(self):
        return {"peer_state": self.peer_state, "frames_received": 0, "frames_dropped": 0}


def _command_payload(segment_id: str, text: str) -> dict:
    return {
        "type": "device_transcript", "is_final": True, "is_command": True,
        "segment_id": segment_id, "text": text,
    }


def _traces(db_path: Path, segment_id: str) -> list[dict]:
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='command_execution_traces_v19'"
        ).fetchone() is None:
            return []
        return [dict(r) for r in con.execute(
            "SELECT * FROM command_execution_traces_v19 WHERE segment_id=? ORDER BY id",
            (segment_id,),
        ).fetchall()]


# --------------------------------------------------------------------------- #
# Classification                                                              #
# --------------------------------------------------------------------------- #
def test_intent_classification_matches_the_router_vocabulary():
    durable = {"enroll", "correct", "correct_object", "correct_place",
               "remember_fact", "owner_enroll"}
    interactive = {"help_start", "help_advance", "ask_memory", "what_is",
                   "find", "ocr", "zoom", "translate", "translate_live", "unknown"}
    for intent in durable:
        assert live_pipeline._command_intent_is_durable(intent) is True
    for intent in interactive:
        assert live_pipeline._command_intent_is_durable(intent) is False
    # Unknown / in-flight (None) is durable-by-default: never abandon a
    # possibly-durable command.
    assert live_pipeline._command_intent_is_durable(None) is True


# --------------------------------------------------------------------------- #
# Interactive command in-flight past the grace → cancelled_session_end        #
# --------------------------------------------------------------------------- #
def test_interactive_command_past_grace_is_cancelled_and_drain_returns(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_COMMAND_GRACE_S", "0.3")
    monkeypatch.setenv("MLOMEGA_FINAL_DRAIN_TIMEOUT_S", "5")
    db = tmp_path / "memory.db"
    gate = threading.Event()  # never released → command stays in flight
    intents = _BlockingIntents(intent="ask_memory", gate=gate)

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-interactive",
            person_id="owner", db_path=db,
            ingress_factory=_ReceiptIngress,
            pipeline_factory=lambda **_k: _pipeline(db, intents),
            close_day=lambda **_k: {"status": "completed"},
        )
        seg = "seg-interactive"
        rt.ingress.dispatch_transcript(rt.pipeline, _command_payload(seg, "interroge ma mémoire"))
        await asyncio.sleep(0.05)  # let accepted trace land + routing start
        # The grace drain must RETURN (not raise) once the interactive command is
        # abandoned after the grace.
        await rt._drain_commands_with_grace()
        return seg, rt

    seg, rt = asyncio.run(scenario())
    gate.set()  # release the orphan thread so pytest can exit cleanly

    phases = [t["phase"] for t in _traces(db, seg)]
    assert "accepted" in phases
    assert "cancelled_session_end" in phases
    row = [t for t in _traces(db, seg) if t["phase"] == "cancelled_session_end"][0]
    assert row["status"] == "cancelled"
    assert row["durable"] == 0
    # Honest cancellation must be recorded on the runtime (never silent).
    assert any("cancelled_session_end" in e for e in rt.recent_errors)


# --------------------------------------------------------------------------- #
# Gate B #5: a cancelled interactive worker's effect is REFUSED at the token   #
# and the drain WAITS for the worker to really finish before returning.        #
# --------------------------------------------------------------------------- #
def test_cancelled_interactive_effect_is_suppressed_and_drain_waits_real_end(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_COMMAND_GRACE_S", "0.3")
    monkeypatch.setenv("MLOMEGA_FINAL_DRAIN_TIMEOUT_S", "5")
    db = tmp_path / "memory.db"
    gate = threading.Event()
    released = threading.Event()

    class _EffectAfterCancel:
        """An interactive handler that, once released, tries to push a device effect
        THROUGH the pipeline — exactly what an orphaned VLM/ask_memory reply would do.
        The cancel token must make that effect a no-op."""

        metrics = {"intents_routed": 0}

        def __init__(self, pipe):
            self.context = _Context()
            self._pipe = pipe

        def on_transcript(self, _text):
            self.context.note("ask_memory")   # interactive intent, decided up-front
            gate.wait(timeout=30.0)           # blocked past the grace → cancelled
            # The worker resumes AFTER cancellation and attempts an effect:
            self._pipe._push_intent({"type": "ui_intent", "content": {"text": "late reply"}})
            released.set()
            return {"intent": "ask_memory", "handled": True, "result": {"status": "ok"}}

    sent: list = []

    class _RecordingIngress(_ReceiptIngress):
        def send_ui_intent(self, payload):
            sent.append(payload)
            return 0

    async def scenario():
        pipe_holder = {}

        def _factory(**_k):
            p = _pipeline(db, None)
            handler = _EffectAfterCancel(p)
            p.intents = handler
            ctx = handler.context
            ctx.on_intent_resolved = p._on_intent_resolved_for_current_command
            pipe_holder["pipe"] = p
            return p

        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-effect-suppress",
            person_id="owner", db_path=db,
            ingress_factory=_RecordingIngress,
            pipeline_factory=_factory,
            close_day=lambda **_k: {"status": "completed"},
        )
        seg = "seg-effect"
        rt.ingress.dispatch_transcript(rt.pipeline, _command_payload(seg, "interroge ma mémoire"))
        await asyncio.sleep(0.05)

        async def _release_after_cancel():
            await asyncio.sleep(0.6)  # let the grace expire + cancel land
            gate.set()

        releaser = asyncio.create_task(_release_after_cancel())
        await rt._drain_commands_with_grace()   # waits for the real end of the worker
        await releaser
        return seg, rt

    seg, rt = asyncio.run(scenario())
    assert released.is_set()  # the worker really finished (drain awaited it)
    # The late effect was suppressed — nothing reached the (closed) device channel.
    assert sent == []
    # Command_execution traces are additive and DO go out (not through _push_intent
    # suppression): the cancellation is recorded, never silent.
    phases = [t["phase"] for t in _traces(db, seg)]
    assert "cancelled_session_end" in phases


# --------------------------------------------------------------------------- #
# Durable command in-flight past the grace → awaited, finishes → completed     #
# --------------------------------------------------------------------------- #
def test_durable_command_past_grace_is_awaited_not_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_COMMAND_GRACE_S", "0.3")
    monkeypatch.setenv("MLOMEGA_FINAL_DRAIN_TIMEOUT_S", "5")
    db = tmp_path / "memory.db"
    gate = threading.Event()
    intents = _BlockingIntents(intent="remember_fact", gate=gate)

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-durable",
            person_id="owner", db_path=db,
            ingress_factory=_ReceiptIngress,
            pipeline_factory=lambda **_k: _pipeline(db, intents),
            close_day=lambda **_k: {"status": "completed"},
        )
        seg = "seg-durable"
        rt.ingress.dispatch_transcript(rt.pipeline, _command_payload(seg, "retiens c'est Karim"))
        await asyncio.sleep(0.05)

        # Release the durable command AFTER the grace but WELL BEFORE the budget
        # (the "finishes at 90 s → completed" case).
        async def _release_later():
            await asyncio.sleep(0.6)
            gate.set()

        releaser = asyncio.create_task(_release_later())
        await rt._drain_commands_with_grace()  # must WAIT for the durable command
        await releaser
        return seg

    seg = asyncio.run(scenario())
    phases = [t["phase"] for t in _traces(db, seg)]
    assert "accepted" in phases
    assert "completed" in phases  # ran to completion, not abandoned
    assert "cancelled_session_end" not in phases
    completed = [t for t in _traces(db, seg) if t["phase"] == "completed"][0]
    assert completed["durable"] == 1
    assert completed["intent"] == "remember_fact"


# --------------------------------------------------------------------------- #
# Durable command overruns the budget → noisy TimeoutError                     #
# --------------------------------------------------------------------------- #
def test_durable_command_over_budget_raises_noisy_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_COMMAND_GRACE_S", "0.3")
    monkeypatch.setenv("MLOMEGA_FINAL_DRAIN_TIMEOUT_S", "0.6")
    db = tmp_path / "memory.db"
    gate = threading.Event()  # never released within the budget
    intents = _BlockingIntents(intent="owner_enroll", gate=gate)

    async def scenario():
        rt = runtime_mod.PhoneOnlyRuntime(
            "transport-overbudget",
            person_id="owner", db_path=db,
            ingress_factory=_ReceiptIngress,
            pipeline_factory=lambda **_k: _pipeline(db, intents),
            close_day=lambda **_k: {"status": "completed"},
        )
        seg = "seg-overbudget"
        rt.ingress.dispatch_transcript(rt.pipeline, _command_payload(seg, "configure ma voix"))
        await asyncio.sleep(0.05)
        with pytest.raises(TimeoutError):
            await rt._drain_commands_with_grace()
        return seg

    seg = asyncio.run(scenario())
    gate.set()
    # A durable overrun is NEVER a cancellation; only accepted was recorded.
    phases = [t["phase"] for t in _traces(db, seg)]
    assert "accepted" in phases
    assert "cancelled_session_end" not in phases


# --------------------------------------------------------------------------- #
# All phases persisted for the 13/13 correlation                              #
# --------------------------------------------------------------------------- #
def test_completed_and_failed_phases_persist_for_correlation(tmp_path):
    db = tmp_path / "memory.db"

    class _ImmediateIntents:
        metrics = {"intents_routed": 0}

        def on_transcript(self, _text):
            return {"intent": "find", "handled": True, "result": {"status": "ok"}}

    pipe = _pipeline(db, _ImmediateIntents())
    pipe.on_device_transcript(_command_payload("seg-ok", "trouve mes clés"))

    class _RaisingIntents:
        metrics = {"intents_routed": 0}

        def on_transcript(self, _text):
            raise RuntimeError("boom")

    pipe.intents = _RaisingIntents()
    pipe.on_device_transcript(_command_payload("seg-fail", "trouve autre chose"))

    ok_phases = {t["phase"] for t in _traces(db, "seg-ok")}
    fail_phases = {t["phase"] for t in _traces(db, "seg-fail")}
    assert ok_phases == {"accepted", "completed"}
    assert fail_phases == {"accepted", "failed"}
    # Correlation must see both the accepted and a terminal phase per command.
    assert {t["intent"] for t in _traces(db, "seg-ok") if t["phase"] == "completed"} == {"find"}
