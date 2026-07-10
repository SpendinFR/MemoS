"""E53 — HelpTaskEngine ("Viki mode aide"), PC half.

Real PC-side checks, no hardware and no cloud network (the LLM/VLM are mocked; the
UI emission + grounding + persistence run for real). Coverage mirrors the E53 brief:

* a valid LLM JSON reply → a schema-EXACT TaskPlan (typed steps/objects/gesture);
* an invalid / empty reply → honest rejection (one reformulation ask), no fabricated plan;
* advance / repeat / go_to / finish state machine;
* pre-calc: entering step N already pushes step N+1 as ghost anchors (0-latency next);
* grounding: a step object's ``label_en`` matching a live WorldBrain track joins its
  ``track_id``/``entity_id`` into the anchor; no match → anchor ships un-grounded;
* proactive no-progress timer → ONE local hint, then escalation (cloud only when paid
  mode is active AND allowed — never per frame);
* the "j'ai une notice" VLM document path;
* light persistence: a paused task is offered again by a fresh engine (session resume);
* intents: "mode aide"/"aide-moi à X" route to help_start; while a task is active,
  "étape suivante"/"c'est fait"/"répète"/"pause"/"reprends"/"termine" route to it —
  and none of the existing E33 intents are stolen (no collision when no task runs).
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


help_mode = _load("v19_help_mode", "services/live-pc/help_mode.py")
intent_router = _load("v19_intent_router", "services/live-pc/intent_router.py")


# --------------------------------------------------------------------------- fakes
class _FakeLLM:
    """A stand-in LLMRouter: returns a fixed JSON dict, exposes cloud_active."""

    def __init__(self, data, *, cloud_active=False):
        self._data = data
        self.cloud_active = cloud_active
        self.calls = 0
        self.last_user = None

    def complete_json(self, system, user, *, schema_hint=None, timeout=None):
        self.calls += 1
        self.last_user = user
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class _FakeWorldBrain:
    def __init__(self, entities):
        self._entities = entities

    def snapshot(self):
        return {"entities": list(self._entities)}


class _FakeVLM:
    def __init__(self, text):
        self._text = text

    def describe(self, img, prompt=None):
        return {"status": "ok", "text": self._text, "model": "fake"}


class _Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def _tea_plan():
    return {
        "title": "Faire un thé", "domain": "cooking",
        "steps": [
            {"text": "Verse l'eau dans la bouilloire", "action": "pour",
             "objects": [
                 {"name": "la bouteille", "label_en": "Bottle", "role": "tool", "quantity": "500 ml"},
                 {"name": "la bouilloire", "label_en": "kettle", "role": "target"},
             ],
             "gesture": {"kind": "arc", "from": "bottle", "to": "kettle"},
             "timer_seconds": None, "done_when": "voice"},
            {"text": "Mets le sachet dans la tasse", "action": "place",
             "objects": [{"name": "la tasse", "label_en": "cup", "role": "target"}],
             "gesture": {"kind": "none"}, "timer_seconds": 180,
             "caution": "eau chaude", "done_when": "voice"},
        ],
    }


def _engine(plan_data=None, **kw):
    pushed: list[dict] = []
    eng = help_mode.HelpTaskEngine(
        llm_router=_FakeLLM(plan_data if plan_data is not None else _tea_plan()),
        emit_ui_intent=pushed.append, **kw,
    )
    return eng, pushed


# --------------------------------------------------------------------------- plan schema
def test_valid_llm_reply_yields_schema_exact_plan():
    eng, _ = _engine()
    res = eng.start_from_description("fais-moi un thé")
    assert res["status"] == "active" and res["ok"] is True
    assert res["domain"] == "cooking"
    assert res["current_index"] == 0 and res["status"] == "active"
    step0 = res["steps"][0]
    # typed fields present and normalised
    assert step0["index"] == 0
    assert step0["action"] == "pour"
    assert step0["done_when"] == "voice"
    obj = step0["objects"][0]
    # label_en canonicalised to lowercase; role/quantity carried
    assert obj["label_en"] == "bottle"
    assert obj["role"] == "tool" and obj["quantity"] == "500 ml"
    assert step0["gesture"] == {"kind": "arc", "from": "bottle", "to": "kettle"}
    # step 1 timer + caution preserved
    assert res["steps"][1]["timer_seconds"] == 180
    assert res["steps"][1]["caution"] == "eau chaude"
    assert eng.metrics["plans_generated"] == 1


def test_unknown_enum_values_are_normalised_not_rejected():
    plan = {"title": "X", "domain": "banana", "steps": [
        {"text": "fais un truc", "action": "teleport",
         "objects": [{"name": "chose", "label_en": "widget", "role": "boss"}],
         "gesture": {"kind": "spiral"}, "done_when": "telepathy"}]}
    eng, _ = _engine(plan)
    res = eng.start_from_description("x")
    assert res["domain"] == "generic"           # unknown domain → generic
    assert res["steps"][0]["action"] == "generic"
    assert res["steps"][0]["objects"][0]["role"] == "target"
    assert res["steps"][0]["gesture"]["kind"] == "none"
    assert res["steps"][0]["done_when"] == "voice"


@pytest.mark.parametrize("bad", [
    {"title": "x", "steps": []},                       # no steps
    {"title": "x", "steps": [{"action": "pour"}]},     # step with no text
    {"title": "x"},                                    # no steps key
    "not a dict",                                       # not even an object
])
def test_invalid_plan_rejected_with_honest_reformulation(bad):
    eng, pushed = _engine(bad)
    res = eng.start_from_description("trucmuche")
    assert res["status"] == "needs_reformulation"
    assert eng.plan is None
    assert eng.metrics["plans_rejected"] == 1
    # an honest card was pushed
    assert any(p["content"]["kind"] == "help_needs_reformulation" for p in pushed)


def test_llm_unavailable_degrades_honestly():
    eng = help_mode.HelpTaskEngine(llm_router=_FakeLLM(RuntimeError("down")), emit_ui_intent=lambda i: None)
    res = eng.start_from_description("fais un thé")
    assert res["status"] == "needs_reformulation"
    assert eng.metrics["llm_unavailable"] == 1


# --------------------------------------------------------------------------- state machine
def test_advance_repeat_go_to_finish():
    eng, _ = _engine()
    eng.start_from_description("x")
    assert eng.current_step()["index"] == 0
    nxt = eng.advance()
    assert nxt["index"] == 1 and eng.metrics["steps_advanced"] == 1
    # advancing past the last step finishes the task
    done = eng.advance()
    assert done["status"] == "done"
    assert eng.plan is None and not eng.active
    # go_to on a fresh plan is bounded
    eng.start_from_description("x")
    assert eng.go_to(99)["index"] == 1
    assert eng.go_to(-5)["index"] == 0


def test_finish_cancel_clears_task():
    eng, pushed = _engine()
    eng.start_from_description("x")
    res = eng.finish(cancelled=True)
    assert res["status"] == "cancelled"
    assert eng.plan is None
    # a closing panel (done) was emitted
    assert any(p["component"] == "task_panel" and p["content"]["status"] == "done" for p in pushed)


# --------------------------------------------------------------------------- pre-calc N+1
def test_entering_step_pre_pushes_next_as_ghost_anchor():
    eng, pushed = _engine()
    eng.start_from_description("x")
    anchors = [p for p in pushed if p["component"] == "task_anchor"]
    ghosts = [a for a in anchors if a["content"]["ghost"]]
    current = [a for a in anchors if not a["content"]["ghost"]]
    # step 0 has 2 objects (current), step 1 has 1 object (ghost, pre-calculated)
    assert {a["content"]["label_en"] for a in current} == {"bottle", "kettle"}
    assert [a["content"]["label_en"] for a in ghosts] == ["cup"]
    assert all(a["content"]["lookahead"] for a in ghosts)
    assert eng.metrics["ghost_anchors_emitted"] == 1
    # the ghost priority is low so the device pre-loads it silently
    assert ghosts[0]["priority"] < current[0]["priority"]


# --------------------------------------------------------------------------- contract / identity
def test_panel_contract_and_anchor_ids_refresh_in_place():
    eng, pushed = _engine()
    plan = eng.start_from_description("x")
    task_id = plan["task_id"]
    first_panel = next(p for p in pushed if p["component"] == "task_panel")
    assert first_panel["ui_intent_id"] == f"help-panel:{task_id}"
    assert [s["status"] for s in first_panel["content"]["steps"]] == ["current", "next"]
    ghost_cup = next(p for p in pushed if p["component"] == "task_anchor"
                     and p["content"]["label_en"] == "cup")

    pushed.clear()
    eng.advance()
    second_panel = next(p for p in pushed if p["component"] == "task_panel")
    current_cup = next(p for p in pushed if p["component"] == "task_anchor"
                       and p["content"]["label_en"] == "cup")
    assert second_panel["ui_intent_id"] == first_panel["ui_intent_id"]
    assert [s["status"] for s in second_panel["content"]["steps"]] == ["done", "current"]
    assert current_cup["ui_intent_id"] == ghost_cup["ui_intent_id"]
    assert current_cup["content"]["ghost"] is False


def test_cross_object_gesture_is_owned_once_and_carries_grounded_endpoints():
    wb = _FakeWorldBrain([
        {"label": "bottle", "track_id": "bottle-1", "entity_id": "eb", "lifecycle": "confirmed"},
        {"label": "kettle", "track_id": "kettle-1", "entity_id": "ek", "lifecycle": "confirmed"},
    ])
    eng, pushed = _engine(worldbrain=wb)
    eng.start_from_description("x")
    current = [p for p in pushed if p["component"] == "task_anchor" and not p["content"]["ghost"]]
    gestures = [p for p in current if p["content"]["gesture"]["kind"] != "none"]
    assert len(gestures) == 1
    assert gestures[0]["content"]["from_track_id"] == "bottle-1"
    assert gestures[0]["content"]["to_track_id"] == "kettle-1"


def test_h1_panel_is_not_double_pushed_and_preserves_typed_contract():
    class Scene:
        def __init__(self): self.calls = []
        def _enqueue(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "queued"}

    scene = Scene()
    eng, pushed = _engine(scene_adapter=scene)
    plan = eng.start_from_description("x")
    panels = [p for p in pushed if p["component"] == "task_panel"]
    assert panels == [], "queued H1 panel must not also use the direct renderer"
    assert scene.calls[0]["kind"] == "task_panel"
    assert scene.calls[0]["ui_intent_id"] == f"help-panel:{plan['task_id']}"
    payload = __import__("json").loads(scene.calls[0]["message"])
    assert payload["steps"][0]["status"] == "current"


# --------------------------------------------------------------------------- grounding
def test_grounding_joins_track_when_label_matches():
    wb = _FakeWorldBrain([
        {"label": "cup", "track_id": "trk-9", "entity_id": "ent-3",
         "lifecycle": "confirmed", "confidence": 0.9, "evidence": ["frame:a"]},
    ])
    plan = {"title": "T", "domain": "cooking", "steps": [
        {"text": "prends la tasse", "action": "place",
         "objects": [{"name": "la tasse", "label_en": "cup", "role": "target"},
                     {"name": "le couteau", "label_en": "knife", "role": "tool"}],
         "gesture": {"kind": "none"}}]}
    eng = help_mode.HelpTaskEngine(llm_router=_FakeLLM(plan), worldbrain=wb, emit_ui_intent=lambda i: None)
    pushed: list[dict] = []
    eng._emit = pushed.append
    eng.start_from_description("x")
    anchors = {a["content"]["label_en"]: a["content"] for a in pushed
               if a["component"] == "task_anchor" and not a["content"]["ghost"]}
    # cup is tracked → joined
    assert anchors["cup"]["track_id"] == "trk-9"
    assert anchors["cup"]["entity_id"] == "ent-3"
    # knife is NOT in the world → anchor ships without a track (device shows an arrow)
    assert anchors["knife"]["track_id"] is None
    assert eng.metrics["grounding_hits"] == 1


def test_grounding_prefers_confirmed_over_stale():
    wb = _FakeWorldBrain([
        {"label": "cup", "track_id": "old", "entity_id": "e-old",
         "lifecycle": "last_seen", "confidence": 0.9},
        {"label": "cup", "track_id": "new", "entity_id": "e-new",
         "lifecycle": "confirmed", "confidence": 0.5},
    ])
    eng = help_mode.HelpTaskEngine(worldbrain=wb)
    tracks = eng._ground_labels()
    assert tracks["cup"]["track_id"] == "new"


# --------------------------------------------------------------------------- proactive
def test_no_progress_timer_emits_one_hint_then_escalates_locally():
    clock = _Clock(0.0)
    eng = help_mode.HelpTaskEngine(
        llm_router=_FakeLLM(_tea_plan()), emit_ui_intent=lambda i: None, now_fn=clock,
        config=help_mode.HelpModeConfig(no_progress_seconds=10.0, allow_cloud_hints=False),
    )
    eng.start_from_description("x")
    assert eng.tick() is None            # too soon
    clock.t = 11.0
    h1 = eng.tick()
    assert h1 is not None and h1["content"]["escalated"] is False
    assert eng.tick() is None            # no second hint until the next window
    clock.t = 21.0
    h2 = eng.tick()
    assert h2 is not None and h2["content"]["escalated"] is True
    # cloud disabled → both hints are local, zero cloud calls
    assert eng.metrics["local_hints"] == 2 and eng.metrics["cloud_hints"] == 0
    # advancing resets the timer (no immediate hint on the new step)
    eng.advance()
    assert eng.tick() is None


def test_escalated_hint_uses_cloud_only_when_paid_mode_active():
    clock = _Clock(0.0)
    llm = _FakeLLM(_tea_plan(), cloud_active=True)
    vlm = _FakeVLM('{"hint": "vérifie que la bouilloire est branchée"}')
    eng = help_mode.HelpTaskEngine(
        llm_router=llm, vlm=vlm, keyframe_provider=lambda: np.zeros((4, 4, 3), np.uint8),
        emit_ui_intent=lambda i: None, now_fn=clock,
        config=help_mode.HelpModeConfig(no_progress_seconds=10.0, allow_cloud_hints=True),
    )
    eng.start_from_description("x")
    clock.t = 11.0
    eng.tick()                            # 1st (local)
    clock.t = 21.0
    h2 = eng.tick()                       # 2nd → cloud visual hint
    assert h2["content"]["text"].startswith("vérifie")
    assert eng.metrics["cloud_hints"] == 1


# --------------------------------------------------------------------------- document path
def test_plan_from_document_uses_vlm():
    doc_json = ('{"title":"Notice","domain":"repair","steps":['
                '{"text":"dévisser le panneau","action":"screw",'
                '"objects":[{"name":"la vis","label_en":"","role":"part"}],'
                '"gesture":{"kind":"circular"}}]}')
    img = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.close()
    import cv2

    cv2.imwrite(img.name, np.zeros((8, 8, 3), np.uint8))
    eng = help_mode.HelpTaskEngine(vlm=_FakeVLM(doc_json), emit_ui_intent=lambda i: None)
    res = eng.plan_from_document([img.name])
    assert res["status"] == "active" and res["source"] == "scanned_doc"
    assert res["domain"] == "repair"
    # a non-detectable object keeps label_en="" honestly (not invented)
    assert res["steps"][0]["objects"][0]["label_en"] == ""
    assert eng.metrics["plans_from_document"] == 1


def test_plan_from_document_no_image_is_honest():
    eng = help_mode.HelpTaskEngine(vlm=_FakeVLM("{}"), emit_ui_intent=lambda i: None)
    res = eng.plan_from_document([])
    assert res["status"] == "needs_reformulation"


# --------------------------------------------------------------------------- persistence
def test_paused_task_is_offered_again_by_a_fresh_engine(tmp_path):
    db = str(tmp_path / "help.db")
    plan = {"title": "Monter l'étagère", "domain": "assembly", "steps": [
        {"text": "un", "action": "generic", "objects": []},
        {"text": "deux", "action": "generic", "objects": []}]}
    e1 = help_mode.HelpTaskEngine(
        llm_router=_FakeLLM(plan), emit_ui_intent=lambda i: None,
        service_db_path=db, live_session_id="s1", person_id="me",
    )
    e1.start_from_description("monte l'étagère")
    e1.advance()
    e1.pause()
    # a NEW engine (next session) sees the paused task on the shared store
    e2 = help_mode.HelpTaskEngine(
        emit_ui_intent=lambda i: None, service_db_path=db,
        live_session_id="s2", person_id="me",
    )
    offered = e2.resume_active()
    assert offered is not None
    assert offered["title"] == "Monter l'étagère"
    assert offered["current_index"] == 1        # resumes where it was left
    assert e2.metrics["resumes_offered"] == 1
    resumed = e2.resume(offered)
    assert e2.active and e2.current_step()["index"] == 1


def test_resume_active_none_when_task_done(tmp_path):
    db = str(tmp_path / "help.db")
    e1 = help_mode.HelpTaskEngine(
        llm_router=_FakeLLM(_tea_plan()), emit_ui_intent=lambda i: None,
        service_db_path=db, person_id="me",
    )
    e1.start_from_description("x")
    e1.advance()          # → step 1
    e1.advance()          # → finished (done)
    e2 = help_mode.HelpTaskEngine(emit_ui_intent=lambda i: None, service_db_path=db, person_id="me")
    assert e2.resume_active() is None


def test_product_db_path_persists_from_worker_thread(tmp_path):
    db = str(tmp_path / "product.db")
    e1 = help_mode.HelpTaskEngine(
        llm_router=_FakeLLM(_tea_plan()), emit_ui_intent=lambda i: None,
        db_path=db, person_id="me",
    )
    thread = threading.Thread(
        target=lambda: e1.start_from_description("je suis bloqué au branchement")
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    e2 = help_mode.HelpTaskEngine(emit_ui_intent=lambda i: None, db_path=db, person_id="me")
    assert e2.resume_active() is not None


# --------------------------------------------------------------------------- intents
class _Sink:
    def __init__(self):
        self.ui = []
        self.device = []

    def emit_ui(self, i):
        self.ui.append(i)

    def emit_device(self, c):
        self.device.append(c)


def _router_with_engine(plan_data=None, *, llm_for_router=None):
    eng = help_mode.HelpTaskEngine(
        llm_router=_FakeLLM(plan_data if plan_data is not None else _tea_plan()),
        emit_ui_intent=lambda i: None,
    )
    sink = _Sink()
    router = intent_router.IntentRouter(
        vision_focus=lambda r: None,
        on_device_command=sink.emit_device,
        emit_ui_intent=sink.emit_ui,
        llm_router=llm_for_router,          # None → grammar net path
        help_engine=eng,
    )
    return router, eng, sink


def test_help_start_routes_from_grammar():
    router, eng, _ = _router_with_engine()
    r = router.on_transcript("aide-moi à préparer un thé")
    assert r["intent"] == "help_start"
    assert r["result"]["status"] == "active"
    assert eng.active


def test_mode_aide_alone_is_multiturn():
    router, eng, _ = _router_with_engine()
    r = router.on_transcript("viki mode aide")
    assert r["intent"] == "help_start"
    assert eng.awaiting_description and not eng.active
    # the NEXT turn is the description → task starts
    r2 = router.on_transcript("monter une étagère")
    assert r2["intent"] == "help_start"
    assert eng.active


def test_mode_aide_accepts_free_mid_task_blockage_verbatim():
    llm = _FakeLLM(_tea_plan())
    eng = help_mode.HelpTaskEngine(llm_router=llm, emit_ui_intent=lambda i: None)
    sink = _Sink()
    router = intent_router.IntentRouter(
        vision_focus=lambda r: None, on_device_command=sink.emit_device,
        emit_ui_intent=sink.emit_ui, help_engine=eng,
    )
    router.on_transcript("mode aide")
    description = "j'ai déjà monté l'étagère mais je bloque seulement pour fixer la porte"
    result = router.on_transcript(description)
    assert result["intent"] == "help_start"
    assert llm.last_user.startswith(description)


def test_active_task_controls_route_to_engine():
    router, eng, _ = _router_with_engine(
        {"title": "T", "domain": "cooking", "steps": [
            {"text": "un", "action": "generic", "objects": []},
            {"text": "deux", "action": "generic", "objects": []},
            {"text": "trois", "action": "generic", "objects": []}]})
    router.on_transcript("aide-moi à faire trois choses")
    assert eng.active and eng._current_index() == 0
    assert router.on_transcript("étape suivante")["intent"] == "help_advance"
    assert eng._current_index() == 1
    assert router.on_transcript("c'est fait")["intent"] == "help_advance"
    assert eng._current_index() == 2
    assert router.on_transcript("répète")["intent"] == "help_repeat"
    assert router.on_transcript("pause la tâche")["intent"] == "help_pause"
    assert eng.plan["status"] == "paused"
    assert router.on_transcript("reprends la tâche")["intent"] == "help_resume"
    assert eng.active
    assert router.on_transcript("termine la tâche")["intent"] == "help_stop"
    assert not eng.active


def test_no_collision_when_no_task_active():
    # "c'est fait" in ordinary talk must NOT be captured as a help control.
    router, eng, _ = _router_with_engine()
    r = router.on_transcript("c'est fait")   # no active task, no LLM router
    assert r["intent"] != "help_advance"
    assert r["intent"] == "unknown"


def test_help_does_not_break_existing_vision_intents():
    # An existing E33 intent still resolves with the help engine wired.
    router, eng, sink = _router_with_engine()
    r = router.on_transcript("trouve mes clés")
    assert r["intent"] == "find"
    assert r["request"]["query"] == "mes clés"
    # and "c'est quoi ça" still routes to what_is
    r2 = router.on_transcript("c'est quoi ça")
    assert r2["intent"] == "what_is"
