from __future__ import annotations

"""HelpTaskEngine — "Viki mode aide" universal help mode, PC half (E53).

« Aide-moi à faire X » (cook, assemble a shelf, fix something…) done WELL, at the
OBJECT+GESTURE level. This module owns the PC-side brain of E53; the device owns
the real-time anchoring (StableTrack) and the glass UI bank. The split follows
the E53 golden latency rule — **the cloud is never in the display loop**:

* **Plan** (the typed steps) — slow-OK, cloud ``gpt5.4-mini`` (paid mode) or the
  local LLM, ONCE at the start. Reuses the E33 ``LLMRouter`` verbatim (paid mode
  already shows its cost; we invent nothing).
* **Object recognition** — the PC's VisionRT/WorldBrain, ~0.2 s in LAN.
* **UI anchoring** — the phone, every frame, on-device.
* **"done" / "stuck" / off-plan checks** — cloud, **event-driven** only (a
  no-progress timer), never one call per frame.

What the engine emits (via the EXISTING delivery paths — no new queue):

* a ``task_panel`` UIIntent through the scene adapter's H1 ``_enqueue`` path
  (steps done/current/next, progress, domain) — the sober plan overview;
* a ``task_anchor`` UIIntent per object of the CURRENT step through the live
  DataChannel renderer, carrying ``label_en``, ``role``, gesture params, timer,
  quantity, caution — plus a joined ``track_id``/``entity_id`` when WorldBrain is
  already tracking that object (grounding). The device does the anchoring; an
  anchor with no track ships anyway (the device shows a directional arrow / waits).

**Pre-calc N+1** (0-latency step transition): on entering step N, the payloads of
step N+1 are already built and pushed as *ghost* anchors (``ghost=True``,
``lookahead=True``) so the device can cross-fade instantly on ``advance()``.

**Proactive, event-driven** (never per-frame cloud): :meth:`tick` runs a
"no-progress" timer per step (``no_progress_seconds``, default 90 s). First
timeout → ONE local text hint (a ``task_hint`` card). Second timeout → if paid
mode is active AND ``allow_cloud_hints``, ONE cloud call with the last keyframe for
a contextual hint (reuses the on-demand VLM path); otherwise a second local hint.

**Light persistence**: the active plan survives the session in a small additive,
service-local table (same self-contained sqlite pattern as
``hypothesis_engine``/``attribute_memory`` — no core-schema change). On the next
session, :meth:`resume_active` proposes picking the task back up.

All invariants of the house hold: memory is never cut, ``truth_level`` is honest
(a generated plan is ``inferred``), no hardcoded demo task, honest degrade (LLM
down → one honest reformulation ask, VLM down → honest message), cloud is opt-in
with its cost via the existing mechanism.
"""

import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- schema
# Canonical vocabularies the LLM must fill (kept in sync with the FIGÉ orchestrator
# contract). The device consumes the TaskPlan/TaskStep verbatim.
_DOMAINS = ("cooking", "assembly", "repair", "electronics", "garden",
            "care", "sport", "music", "generic")
_ACTIONS = ("pour", "screw", "turn", "press", "wipe", "cut", "mix", "place",
            "connect", "remove", "hold", "measure", "wait", "check", "generic")
_ROLES = ("target", "tool", "ingredient", "part")
_GESTURES = ("arc", "circular", "linear", "pulse", "none")
_DONE_WHEN = ("voice", "auto_suggest")


@dataclass
class HelpModeConfig:
    """Tunables — all config, never hardcoded (same style as change_attention)."""

    no_progress_seconds: float = 90.0   # per-step "no progress" timer before a hint
    allow_cloud_hints: bool = True      # 2nd timeout may call cloud IF paid mode active
    max_steps: int = 40                 # bound the plan the LLM may return
    panel_ttl_ms: int = 3_600_000       # task panel is sticky (1 h) — a long task
    anchor_ttl_ms: int = 20_000         # per-object anchor refresh window
    hint_ttl_ms: int = 12_000           # a proactive hint card
    plan_timeout_s: float = 20.0        # LLM budget for plan generation
    hint_timeout_s: float = 12.0        # LLM/VLM budget for a contextual hint


# --------------------------------------------------------------------------- plan validation
def _clean_str(value: Any, *, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _one_of(value: Any, allowed: tuple[str, ...], default: str) -> str:
    v = _clean_str(value).lower()
    return v if v in allowed else default


def _normalize_object(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalise ONE object of a step, or ``None`` if it carries no usable label."""
    name = _clean_str(raw.get("name"), limit=80)
    label_en = _clean_str(raw.get("label_en"), limit=60).lower()
    if not (name or label_en):
        return None
    role = _one_of(raw.get("role"), _ROLES, "target")
    quantity = raw.get("quantity")
    quantity = _clean_str(quantity, limit=40) if quantity not in (None, "") else None
    return {
        "name": name or label_en,
        "label_en": label_en,          # may be "" (not detectable) — honest, kept
        "role": role,
        "quantity": quantity,
    }


def _normalize_gesture(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {"kind": "none", "from": None, "to": None}
    kind = _one_of(raw.get("kind"), _GESTURES, "none")
    return {
        "kind": kind,
        "from": _clean_str(raw.get("from"), limit=60).lower() or None,
        "to": _clean_str(raw.get("to"), limit=60).lower() or None,
    }


def _normalize_step(raw: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    """Normalise/validate ONE step. Returns ``None`` when it has no displayable text
    (a step with no instruction is meaningless — dropped, not invented)."""
    if not isinstance(raw, Mapping):
        return None
    text = _clean_str(raw.get("text"))
    if not text:
        return None
    objects: list[dict[str, Any]] = []
    for o in raw.get("objects") or []:
        if isinstance(o, Mapping):
            norm = _normalize_object(o)
            if norm is not None:
                objects.append(norm)
    timer = raw.get("timer_seconds")
    try:
        timer_seconds = int(timer) if timer not in (None, "", False) else None
        if timer_seconds is not None and timer_seconds <= 0:
            timer_seconds = None
    except (TypeError, ValueError):
        timer_seconds = None
    caution = raw.get("caution")
    caution = _clean_str(caution) if caution not in (None, "") else None
    return {
        "index": index,
        "text": text,
        "action": _one_of(raw.get("action"), _ACTIONS, "generic"),
        "objects": objects,
        "gesture": _normalize_gesture(raw.get("gesture")),
        "timer_seconds": timer_seconds,
        "caution": caution,
        "done_when": _one_of(raw.get("done_when"), _DONE_WHEN, "voice"),
    }


class InvalidPlan(ValueError):
    """The LLM reply could not be normalised into a conformant TaskPlan."""


def normalize_plan(raw: Mapping[str, Any], *, source: str, config: HelpModeConfig | None = None) -> dict[str, Any]:
    """Validate + normalise a raw LLM/VLM dict into a schema-exact ``TaskPlan``.

    Rejects honestly (:class:`InvalidPlan`) when there is not a single usable step —
    the caller then asks the user to reformulate, never fabricates a fallback plan.
    """
    cfg = config or HelpModeConfig()
    if not isinstance(raw, Mapping):
        raise InvalidPlan("plan is not an object")
    steps: list[dict[str, Any]] = []
    for i, rs in enumerate(raw.get("steps") or []):
        if len(steps) >= cfg.max_steps:
            break
        step = _normalize_step(rs, len(steps))
        if step is not None:
            steps.append(step)
    if not steps:
        raise InvalidPlan("no usable step in plan")
    title = _clean_str(raw.get("title"), limit=120) or "Tâche"
    return {
        "task_id": _clean_str(raw.get("task_id"), limit=64) or f"task-{uuid.uuid4().hex[:12]}",
        "title": title,
        "domain": _one_of(raw.get("domain"), _DOMAINS, "generic"),
        "source": source,
        "steps": steps,
        "current_index": 0,
        "status": "active",
    }


# --------------------------------------------------------------------------- prompts
_PLAN_SCHEMA: dict[str, Any] = {
    "title": "string — short task title (French)",
    "domain": "one of: " + "|".join(_DOMAINS),
    "steps": [
        {
            "text": "string — short displayable instruction (French)",
            "action": "one of: " + "|".join(_ACTIONS),
            "objects": [
                {
                    "name": "string — displayable FR name (\"le bol\")",
                    "label_en": "string — canonical EN detector label (COCO-like, \"bowl\"); \"\" if not detectable",
                    "role": "one of: " + "|".join(_ROLES),
                    "quantity": "string or null (\"200 g\", \"2\")",
                }
            ],
            "gesture": {"kind": "one of: " + "|".join(_GESTURES),
                        "from": "label_en of source object or null",
                        "to": "label_en of target object or null"},
            "timer_seconds": "int or null",
            "caution": "string or null — a safety warning if any",
            "done_when": "one of: voice|auto_suggest",
        }
    ],
}

_PLAN_SYSTEM = (
    "Tu es l'assistant « mode aide » de lunettes AR. À partir de la description d'une "
    "tâche PHYSIQUE (cuisine, montage, réparation, électronique, jardinage, soin, sport, "
    "musique), produis un PLAN d'ACTIONS ATOMIQUES en JSON strict conforme au schéma. "
    "RÈGLE CENTRALE : chaque `step` est UNE MICRO-ACTION = UN SEUL GESTE affichable en AR "
    "(« verse la farine dans le bol », « visse la vis du coin », « appuie sur le bouton ») "
    "— JAMAIS une étape composite (« prépare la pâte » = interdit : découpe-la en verser/"
    "mélanger/…). Une action = un verbe, un ou deux objets, un geste. Autres règles : "
    "chaque objet manipulable porte un `label_en` canonique de détecteur (COCO-like : "
    "bowl, cup, bottle, knife, spoon, scissors…) ; mets `label_en` à \"\" si l'objet n'est "
    "pas détectable. Le geste décrit la TRAJECTOIRE du mouvement de CETTE action "
    "(verser=arc, visser/tourner=circular, essuyer/déplacer=linear, appuyer=pulse, sinon "
    "none), `from`/`to` = label_en source/cible. `timer_seconds` seulement si l'action a "
    "une attente réelle. `caution` seulement si un vrai danger. N'invente pas d'actions "
    "non nécessaires. L'utilisateur peut demander de l'aide AU MILIEU d'une tâche ou "
    "pour UNE SEULE ACTION : commence à son blocage actuel et ne lui impose jamais de "
    "reprendre la tâche depuis le début. Sa description est du langage naturel libre, "
    "pas une commande ou un patron à recopier. Si un CONTEXTE VISUEL de la scène est fourni, sers-t'en pour "
    "adapter le plan à ce que l'utilisateur a réellement devant lui. Réponds en JSON "
    "uniquement."
)

_SCENE_GUESS_PROMPT = (
    "You see the current scene through AR glasses. The user just asked for help with a "
    "physical task. In 1-2 short sentences (French), describe what task/problem they "
    "seem to be facing and which relevant objects are visible. Be factual, no guessing "
    "beyond what is visible. Answer as strict JSON {\"context\": \"...\"}."
)

_HINT_SYSTEM = (
    "Tu es l'assistant « mode aide ». L'utilisateur semble bloqué sur une étape. "
    "Donne UN indice court et concret (français) pour débloquer, sans refaire tout le "
    "plan. Réponds en JSON strict {\"hint\": \"...\"}."
)

_DOC_PROMPT = (
    "This image is a page of an instructions sheet / manual for a physical task. "
    "Extract it into a typed ACTION plan as strict JSON with keys title, domain, steps "
    "(each step: text, action, objects[name,label_en,role,quantity], gesture{kind,from,to}, "
    "timer_seconds, caution, done_when). IMPORTANT: each step must be ONE ATOMIC "
    "MICRO-ACTION = one displayable gesture (split composite instructions into several "
    "steps). Use canonical COCO-like English detector labels for label_en, or \"\" if "
    "not detectable. Answer with JSON only."
)


# --------------------------------------------------------------------------- engine
class HelpTaskEngine:
    """Owns a TaskPlan lifecycle + its UI emission, grounding, proactivity, persistence.

    Wiring (all optional; a bare engine still computes and returns payloads so the
    unit tests can inspect them without a live pipeline):

    * ``llm_router`` — the E33 :class:`LLMRouter`. Its ``active`` provider decides
      local vs paid (cloud). ``cloud_active`` gates the on-demand cloud hint.
    * ``scene_adapter`` — a :class:`BrainLiveSceneAdapter`; its ``_enqueue`` carries
      the ``task_panel`` through H1. Anchors are real UIIntents on the renderer path.
    * ``worldbrain`` — for grounding: match a step object's ``label_en`` to a live
      track/entity and join its ``track_id``/``entity_id`` into the anchor.
    * ``vlm`` — a ``VisionRT.VlmCrop``-shaped object with ``describe(img, prompt=…)``
      for the document path and the on-demand cloud/local visual hint.
    * ``keyframe_provider`` — returns the last keyframe (a np-array-like) for the
      escalated visual hint. Optional.
    """

    def __init__(
        self,
        *,
        person_id: str = "me",
        live_session_id: str = "",
        llm_router: Any = None,
        scene_adapter: Any = None,
        worldbrain: Any = None,
        vlm: Any = None,
        keyframe_provider: Callable[[], Any] | None = None,
        emit_ui_intent: Callable[[dict[str, Any]], Any] | None = None,
        config: HelpModeConfig | None = None,
        service_db_path: str | Path | None = None,
        db_path: Any = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.person_id = person_id
        self.live_session_id = live_session_id
        self.llm_router = llm_router
        self.scene_adapter = scene_adapter
        self.worldbrain = worldbrain
        self.vlm = vlm
        self._keyframe_provider = keyframe_provider
        # Direct UIIntent emitter (the pipeline's thread-safe DataChannel path).
        # Panels prefer the durable H1 queue; anchors use this renderer path.
        self._emit = emit_ui_intent
        self.config = config or HelpModeConfig()
        self.db_path = db_path
        self._now = now_fn or time.monotonic
        self._svc_lock = threading.RLock()
        self._svc_db = self._init_service_db(service_db_path or db_path)

        self.plan: dict[str, Any] | None = None
        # per-step no-progress timer bookkeeping (monotonic seconds).
        self._step_entered_at: float = 0.0
        self._hints_given: int = 0
        # multi-turn: "mode aide" with no description yet → we await the next turn.
        self._awaiting_description: bool = False
        self.metrics: dict[str, Any] = {
            "plans_generated": 0,
            "plans_rejected": 0,
            "plans_from_document": 0,
            "steps_advanced": 0,
            "anchors_emitted": 0,
            "ghost_anchors_emitted": 0,
            "panels_emitted": 0,
            "grounding_hits": 0,
            "local_hints": 0,
            "cloud_hints": 0,
            "llm_unavailable": 0,
            "resumes_offered": 0,
            "delivery_errors": 0,
            "persistence_errors": 0,
        }

    # ----------------------------------------------------------------- persistence
    def _init_service_db(self, path: str | Path | None):
        import sqlite3

        conn = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS help_mode_tasks(
                 task_id TEXT PRIMARY KEY, person_id TEXT, live_session_id TEXT,
                 title TEXT, domain TEXT, status TEXT, plan_json TEXT,
                 current_index INTEGER, created_at TEXT, updated_at TEXT)"""
        )
        conn.commit()
        return conn

    def _persist(self) -> None:
        if self.plan is None:
            return
        try:
            with self._svc_lock:
                self._svc_db.execute(
                    """INSERT INTO help_mode_tasks(
                         task_id, person_id, live_session_id, title, domain, status,
                         plan_json, current_index, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(task_id) DO UPDATE SET
                         status=excluded.status, plan_json=excluded.plan_json,
                         current_index=excluded.current_index, updated_at=excluded.updated_at""",
                    (
                        self.plan["task_id"], self.person_id, self.live_session_id,
                        self.plan["title"], self.plan["domain"], self.plan["status"],
                        json.dumps(self.plan, ensure_ascii=False), self.plan["current_index"],
                        _iso_now(), _iso_now(),
                    ),
                )
                self._svc_db.commit()
        except Exception:
            self.metrics["persistence_errors"] += 1

    def resume_active(self) -> dict[str, Any] | None:
        """Propose picking up the most recent still-active task (session resume).

        Reads the service-local table for an ``active|paused`` task of this person
        (any session — a task started yesterday is offered today). Returns the
        stored TaskPlan (without re-emitting UI) so the caller can ask the user
        "on reprend « X » ?" — nothing is auto-resumed silently."""
        try:
            with self._svc_lock:
                row = self._svc_db.execute(
                    """SELECT plan_json FROM help_mode_tasks
                       WHERE person_id=? AND status IN ('active','paused')
                       ORDER BY updated_at DESC LIMIT 1""",
                    (self.person_id,),
                ).fetchone()
        except Exception:
            self.metrics["persistence_errors"] += 1
            return None
        if not row:
            return None
        try:
            plan = json.loads(row["plan_json"] or "{}")
        except Exception:
            return None
        if not isinstance(plan, dict) or not plan.get("steps"):
            return None
        self.metrics["resumes_offered"] += 1
        return plan

    def resume(self, plan: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Actually resume a task: adopt the plan and re-emit its UI.

        Prefers an explicit ``plan``, else the currently-loaded (paused) plan, else
        the most recent stored active/paused task (cross-session resume)."""
        if plan is None and self.plan is not None:
            plan = self.plan
        plan = dict(plan) if plan is not None else self.resume_active()
        if not plan:
            return None
        self.plan = dict(plan)
        self.plan["status"] = "active"
        self._enter_step()
        self._persist()
        return self.plan

    # ----------------------------------------------------------------- acquisition
    def start_from_description(self, description: str) -> dict[str, Any]:
        """Generate a TaskPlan from the user's free description via the LLM.

        Uses the E33 ``LLMRouter`` (local by default; paid/cloud when the user has
        opted in — the router already surfaces the cost). On an unavailable LLM or
        an invalid/empty plan, returns an honest ``needs_reformulation`` result and
        asks the user to rephrase — NEVER a hardcoded fallback plan."""
        self._awaiting_description = False
        desc = _clean_str(description, limit=600)
        if not desc:
            return self._ask_description()
        if self.llm_router is None:
            self.metrics["llm_unavailable"] += 1
            return self._needs_reformulation("Le générateur de plan n'est pas disponible.")
        # E53: ONE initial scene glance (VLM on the current keyframe) so the plan is
        # grounded in what the user actually has in front of them — best-effort,
        # event-driven (a single call at start, never per frame).
        scene_ctx = self._guess_scene_context()
        user_msg = desc if not scene_ctx else (
            desc + "\n\nContexte visuel (scène actuelle, indicatif) : " + scene_ctx
        )
        try:
            data = self.llm_router.complete_json(
                _PLAN_SYSTEM, user_msg, schema_hint=_PLAN_SCHEMA,
                timeout=self.config.plan_timeout_s,
            )
        except Exception:
            self.metrics["llm_unavailable"] += 1
            return self._needs_reformulation(
                "Je n'ai pas réussi à préparer le plan. Tu peux reformuler la tâche ?"
            )
        return self._adopt_plan(data, source="user_description")

    def _guess_scene_context(self) -> str:
        """E53: one best-effort VLM glance at the current keyframe when help starts.

        Infers what task/problem the user is facing and which objects are visible so
        the plan matches reality. Returns "" on any failure or missing wiring — the
        plan is then generated from the description alone (honest degraded)."""
        if self.vlm is None or self._keyframe_provider is None:
            return ""
        try:
            img = self._keyframe_provider()
            if img is None:
                return ""
            out = self.vlm.describe(img, prompt=_SCENE_GUESS_PROMPT)
            text = str((out or {}).get("text") or "").strip()
            if not text:
                return ""
            # The VLM may answer either raw text or the requested {"context": ...}.
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("context"):
                    text = str(parsed["context"]).strip()
            except Exception:
                pass
            self.metrics["scene_guesses"] = self.metrics.get("scene_guesses", 0) + 1
            return _clean_str(text, limit=400)
        except Exception:
            return ""

    def plan_from_document(self, image_paths: Sequence[str | Path]) -> dict[str, Any]:
        """"J'ai une notice" path: pass the page image(s) to the VLM → TaskPlan.

        Cloud when paid mode is active (better extraction), else the local VLM with
        an honest quality caveat. With no image available, an honest message — never
        an invented plan."""
        paths = [Path(p) for p in (image_paths or []) if p]
        if not paths:
            return self._needs_reformulation(
                "Je n'ai pas d'image de notice à lire. Montre-moi la page et redemande."
            )
        if self.vlm is None:
            self.metrics["llm_unavailable"] += 1
            return self._needs_reformulation("La lecture de notice n'est pas disponible ici.")
        img = self._read_image(paths[0])
        if img is None:
            return self._needs_reformulation("Je n'ai pas pu ouvrir l'image de la notice.")
        try:
            res = self.vlm.describe(img, prompt=_DOC_PROMPT)
        except Exception:
            res = None
        text = (res or {}).get("text") if isinstance(res, Mapping) else None
        if not text:
            self.metrics["llm_unavailable"] += 1
            return self._needs_reformulation(
                "Je n'ai pas réussi à lire la notice. Réessaie avec une photo plus nette."
            )
        try:
            data = json.loads(_extract_json_block(str(text)))
        except Exception:
            return self._needs_reformulation("La notice n'était pas exploitable. Reformule la tâche ?")
        result = self._adopt_plan(data, source="scanned_doc")
        if result.get("status") == "active":
            self.metrics["plans_from_document"] += 1
        return result

    def _adopt_plan(self, data: Mapping[str, Any], *, source: str) -> dict[str, Any]:
        try:
            plan = normalize_plan(data, source=source, config=self.config)
        except InvalidPlan:
            self.metrics["plans_rejected"] += 1
            return self._needs_reformulation(
                "Je n'ai pas obtenu un plan clair. Tu peux préciser la tâche ?"
            )
        self.plan = plan
        self.metrics["plans_generated"] += 1
        self._enter_step()
        self._persist()
        return {**plan, "status": plan["status"], "ok": True}

    def _read_image(self, path: Path) -> Any | None:
        try:
            import cv2  # type: ignore

            img = cv2.imread(str(path))
            return img if img is not None and getattr(img, "size", 0) else None
        except Exception:
            return None

    # ----------------------------------------------------------------- state machine
    @property
    def active(self) -> bool:
        return self.plan is not None and self.plan.get("status") == "active"

    def _current_index(self) -> int:
        return int(self.plan["current_index"]) if self.plan else 0

    def current_step(self) -> dict[str, Any] | None:
        if self.plan is None:
            return None
        i = self._current_index()
        steps = self.plan["steps"]
        return steps[i] if 0 <= i < len(steps) else None

    def _step_at(self, index: int) -> dict[str, Any] | None:
        if self.plan is None:
            return None
        steps = self.plan["steps"]
        return steps[index] if 0 <= index < len(steps) else None

    def advance(self) -> dict[str, Any] | None:
        """« étape suivante » / « c'est fait » → move to N+1 (or finish)."""
        if self.plan is None:
            return None
        i = self._current_index()
        if i + 1 >= len(self.plan["steps"]):
            return self.finish()
        self.plan["current_index"] = i + 1
        self.metrics["steps_advanced"] += 1
        self._enter_step()
        self._persist()
        return self.current_step()

    def go_to(self, index: int) -> dict[str, Any] | None:
        """Jump to a specific step (bounded)."""
        if self.plan is None:
            return None
        index = max(0, min(int(index), len(self.plan["steps"]) - 1))
        self.plan["current_index"] = index
        self._enter_step()
        self._persist()
        return self.current_step()

    def repeat(self) -> dict[str, Any] | None:
        """« répète » / « quelle étape » → re-emit the current step's UI unchanged."""
        if self.plan is None:
            return None
        self._emit_step_ui(reset_timer=False)
        return self.current_step()

    def pause(self) -> dict[str, Any] | None:
        if self.plan is None:
            return None
        self.plan["status"] = "paused"
        self._persist()
        return self.plan

    def finish(self, *, cancelled: bool = False) -> dict[str, Any] | None:
        """« termine » / « annule » → close the task, clear its panel/anchors."""
        if self.plan is None:
            return None
        self.plan["status"] = "cancelled" if cancelled else "done"
        self._persist()
        self._emit_panel(done=True)
        done = dict(self.plan)
        self.plan = None
        return done

    def _enter_step(self) -> None:
        """Everything that must happen when the current step becomes active:
        reset the no-progress timer, emit the panel + current-step anchors, then
        PRE-CALC and push N+1 as ghost anchors (0-latency next transition)."""
        self._step_entered_at = self._now()
        self._hints_given = 0
        self._emit_step_ui(reset_timer=True)

    def _emit_step_ui(self, *, reset_timer: bool) -> None:
        if reset_timer:
            self._step_entered_at = self._now()
            self._hints_given = 0
        self._emit_panel(done=False)
        self._emit_anchors_for(self._current_index(), ghost=False)
        # Pre-calc N+1 ghost anchors so the device can cross-fade instantly.
        self._emit_anchors_for(self._current_index() + 1, ghost=True)

    # ----------------------------------------------------------------- UI emission
    def _emit_panel(self, *, done: bool) -> dict[str, Any] | None:
        """The ``task_panel`` overview (steps done/current/next, progress, domain).
        Rides the EXISTING H1 delivery queue via the scene adapter's ``_enqueue``
        when present; else the direct UIIntent emitter; else just returns the dict."""
        if self.plan is None:
            return None
        i = self._current_index()
        steps = self.plan["steps"]
        rendered_steps = []
        for index, step in enumerate(steps):
            if done or index < i:
                step_status = "done"
            elif index == i:
                step_status = "current"
            elif index == i + 1:
                step_status = "next"
            else:
                step_status = "pending"
            rendered_steps.append({
                "index": index,
                "text": step.get("text"),
                "status": step_status,
            })
        content = {
            "kind": "task_panel",
            "task_id": self.plan["task_id"],
            "title": self.plan["title"],
            "domain": self.plan["domain"],
            "status": "done" if done else self.plan["status"],
            "current_index": i,
            "step_count": len(steps),
            "progress": round((i + (1 if done else 0)) / max(1, len(steps)), 3),
            "current_text": (steps[i]["text"] if 0 <= i < len(steps) else None),
            "next_text": (steps[i + 1]["text"] if i + 1 < len(steps) else None),
            "steps": rendered_steps,
            "ghost_next": not done and i + 1 < len(steps),
        }
        stable_intent_id = f"help-panel:{self.plan['task_id']}"
        intent = {
            "type": "ui_intent", "ui_intent_id": stable_intent_id,
            "producer": "ultralive", "component": "task_panel",
            "content": content,
            "truth_level": "inferred",   # a generated plan is a hypothesis, not a fact
            "confidence": 0.8, "priority": 0.55,
            "ttl_ms": 4000 if done else self.config.panel_ttl_ms,
            "evidence_refs": [],
        }
        self.metrics["panels_emitted"] += 1
        # Prefer the durable H1 queue. A queued panel is sent exactly once by the
        # DeliveryAdapter; a deduplicated repeat is pushed directly to refresh it
        # after reconnection with the same UI id.
        delivery_status = "unavailable"
        if self.scene_adapter is not None and hasattr(self.scene_adapter, "_enqueue"):
            source_key = f"help:{self.live_session_id}:panel:{self.plan['task_id']}"
            try:
                result = self.scene_adapter._enqueue(
                    source_key=source_key,
                    message=json.dumps(content, ensure_ascii=False),
                    evidence_refs=[], priority=0.55, kind="task_panel",
                    ui_intent_id=stable_intent_id,
                    ttl_ms=4000 if done else self.config.panel_ttl_ms,
                )
                delivery_status = str((result or {}).get("status") or "error")
            except Exception:
                self.metrics["delivery_errors"] += 1
                delivery_status = "error"
        if delivery_status in {"unavailable", "error", "skipped", "deduplicated"}:
            self._push(intent)
        return intent

    def _emit_anchors_for(self, index: int, *, ghost: bool) -> list[dict[str, Any]]:
        """Emit one ``task_anchor`` per object of the step at ``index``.

        Each anchor carries the object (label_en, role, quantity), the step's gesture
        params, timer and caution, and — when WorldBrain already tracks a matching
        object — the joined ``track_id``/``entity_id`` (grounding). Ghost anchors
        (N+1) are flagged so the device pre-loads them silently."""
        step = self._step_at(index)
        if step is None or self.plan is None:
            return []
        tracks = self._ground_labels()
        out: list[dict[str, Any]] = []
        objects = step["objects"] or [{"name": step["text"], "label_en": "",
                                       "role": "target", "quantity": None}]
        gesture = step.get("gesture") or {}
        from_label = str(gesture.get("from") or "").lower()
        gesture_owner = next(
            (n for n, obj in enumerate(objects)
             if from_label and str(obj.get("label_en") or "").lower() == from_label),
            0,
        )
        for object_index, obj in enumerate(objects):
            anchor = self._build_anchor(
                step, obj, index=index, object_index=object_index,
                ghost=ghost, tracks=tracks,
                show_gesture=object_index == gesture_owner,
            )
            self._push_anchor(anchor)
            out.append(anchor)
            self.metrics["anchors_emitted"] += 1
            if ghost:
                self.metrics["ghost_anchors_emitted"] += 1
        return out

    def _build_anchor(
        self, step: Mapping[str, Any], obj: Mapping[str, Any], *,
        index: int, object_index: int, ghost: bool,
        tracks: Mapping[str, dict[str, Any]], show_gesture: bool,
    ) -> dict[str, Any]:
        label_en = str(obj.get("label_en") or "").lower()
        ground = tracks.get(label_en) if label_en else None
        if ground:
            self.metrics["grounding_hits"] += 1
        step_gesture = dict(step.get("gesture") or {})
        from_label = str(step_gesture.get("from") or "").lower()
        to_label = str(step_gesture.get("to") or "").lower()
        if not show_gesture:
            step_gesture["kind"] = "none"
        content: dict[str, Any] = {
            "kind": "task_anchor",
            "task_id": self.plan["task_id"] if self.plan else None,
            "step_index": index,
            "label_en": label_en or None,
            "name": obj.get("name"),
            "role": obj.get("role"),
            "quantity": obj.get("quantity"),
            "action": step.get("action"),
            "gesture": step_gesture,
            "from_track_id": (tracks.get(from_label) or {}).get("track_id") if from_label else None,
            "to_track_id": (tracks.get(to_label) or {}).get("track_id") if to_label else None,
            "timer_seconds": step.get("timer_seconds"),
            "caution": step.get("caution"),
            "lookahead": bool(ghost),
            "ghost": bool(ghost),
            # Grounding: joined only when WorldBrain already tracks this label. When
            # absent, the device shows a directional arrow / waits for its own detect.
            "track_id": (ground or {}).get("track_id"),
            "entity_id": (ground or {}).get("entity_id"),
        }
        return {
            "type": "ui_intent",
            "ui_intent_id": f"help-anchor:{self.plan['task_id']}:{index}:{object_index}",
            "producer": "ultralive", "component": "task_anchor",
            "content": content,
            "truth_level": "inferred", "confidence": 0.8,
            "priority": 0.2 if ghost else 0.6,
            "ttl_ms": self.config.anchor_ttl_ms,
            "evidence_refs": list((ground or {}).get("evidence") or []),
        }

    def _ground_labels(self) -> dict[str, dict[str, Any]]:
        """Map ``label_en`` → the best matching live WorldBrain track/entity.

        Reads the same ``entities`` list of ``WorldBrain.snapshot()`` the scene
        adapter uses (each carries ``label``, ``track_id``, ``entity_id``, evidence).
        Best-effort: no WorldBrain, or any failure → empty (anchors ship un-grounded).
        """
        if self.worldbrain is None:
            return {}
        try:
            entities = self.worldbrain.snapshot().get("entities") or []
        except Exception:
            return {}
        best: dict[str, dict[str, Any]] = {}
        for e in entities:
            label = str(e.get("label") or "").lower().strip()
            if not label:
                continue
            prev = best.get(label)
            # Prefer a currently-confirmed sighting over a stale last_seen.
            score = (1 if e.get("lifecycle") == "confirmed" else 0, float(e.get("confidence") or 0.0))
            if prev is None or score > prev["_score"]:
                best[label] = {
                    "track_id": e.get("track_id"),
                    "entity_id": e.get("entity_id"),
                    "evidence": e.get("evidence") or [],
                    "_score": score,
                }
        return {k: {kk: vv for kk, vv in v.items() if kk != "_score"} for k, v in best.items()}

    def _push_anchor(self, anchor: Mapping[str, Any]) -> None:
        """Send a real UIIntent; Unity's broker/component own the local track cache."""
        self._push(dict(anchor))

    def _push(self, intent: Mapping[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(dict(intent))
        except Exception:
            self.metrics["delivery_errors"] += 1

    # ----------------------------------------------------------------- proactivity
    def tick(self, *, now: float | None = None) -> dict[str, Any] | None:
        """Event-driven no-progress watchdog. Call on the scene cadence (cheap).

        On the FIRST ``no_progress_seconds`` elapsed with no advance → ONE local
        text hint. On the SECOND timeout → a cloud visual hint IF paid mode is active
        AND allowed (one call, last keyframe), else a second local hint. NEVER a
        per-frame cloud call. Returns the emitted hint intent, or ``None``."""
        if not self.active:
            return None
        now = self._now() if now is None else now
        elapsed = now - self._step_entered_at
        cfg = self.config
        # First hint after one window; escalated hint after two windows.
        if self._hints_given == 0 and elapsed >= cfg.no_progress_seconds:
            return self._emit_hint(escalated=False)
        if self._hints_given == 1 and elapsed >= 2 * cfg.no_progress_seconds:
            return self._emit_hint(escalated=True)
        return None

    def _emit_hint(self, *, escalated: bool) -> dict[str, Any] | None:
        self._hints_given += 1
        step = self.current_step()
        if step is None:
            return None
        text = self._hint_text(step, escalated=escalated)
        content = {
            "kind": "task_hint",
            "task_id": self.plan["task_id"] if self.plan else None,
            "step_index": self._current_index(),
            "text": text,
            "escalated": bool(escalated),
        }
        intent = {
            "type": "ui_intent", "ui_intent_id": str(uuid.uuid4()),
            "producer": "ultralive", "component": "context_card",
            "content": content, "truth_level": "inferred", "confidence": 0.6,
            "priority": 0.45, "ttl_ms": self.config.hint_ttl_ms, "evidence_refs": [],
        }
        self._push(intent)
        return intent

    def _hint_text(self, step: Mapping[str, Any], *, escalated: bool) -> str:
        """Build the hint. Escalated + paid-mode + allowed → one cloud visual call
        with the last keyframe; otherwise a local, honest text hint from the step."""
        if escalated and self.config.allow_cloud_hints and self._cloud_active():
            cloud = self._cloud_visual_hint(step)
            if cloud:
                self.metrics["cloud_hints"] += 1
                return cloud
        self.metrics["local_hints"] += 1
        base = str(step.get("text") or "").strip()
        if escalated:
            return f"Toujours bloqué ? Concentre-toi sur : {base}"
        caution = step.get("caution")
        tip = f" Attention : {caution}" if caution else ""
        return f"Besoin d'un coup de main ? Étape en cours : {base}.{tip}"

    def _cloud_active(self) -> bool:
        return bool(self.llm_router is not None and getattr(self.llm_router, "cloud_active", False))

    def _cloud_visual_hint(self, step: Mapping[str, Any]) -> str | None:
        """ONE on-demand contextual hint from the last keyframe (reuses the VLM path).

        Cloud (paid mode) is already active here; we route the keyframe through the
        VLM ``describe`` if wired, else a text-only LLM ask. Best-effort — any failure
        falls back to the local text hint. Never called per frame (only 2nd timeout)."""
        prompt = (
            f"{_HINT_SYSTEM} Étape en cours : « {step.get('text')} ». "
            "Regarde l'image et dis ce qui bloque probablement."
        )
        img = self._keyframe_provider() if self._keyframe_provider is not None else None
        if img is not None and self.vlm is not None:
            try:
                res = self.vlm.describe(img, prompt=prompt)
                text = (res or {}).get("text") if isinstance(res, Mapping) else None
                if text:
                    return _clean_str(_hint_from_reply(str(text)), limit=200)
            except Exception:
                pass
        if self.llm_router is not None:
            try:
                data = self.llm_router.complete_json(
                    _HINT_SYSTEM, str(step.get("text") or ""),
                    schema_hint={"hint": "string"}, timeout=self.config.hint_timeout_s,
                )
                hint = _clean_str((data or {}).get("hint"), limit=200)
                if hint:
                    return hint
            except Exception:
                pass
        return None

    # ----------------------------------------------------------------- honest degrade
    def _needs_reformulation(self, text: str) -> dict[str, Any]:
        self._awaiting_description = False
        intent = self._card(text, kind="help_needs_reformulation", level="warn")
        self._push(intent)
        return {"status": "needs_reformulation", "text": text, "ui_intent": intent, "handled": True}

    def _ask_description(self) -> dict[str, Any]:
        """« mode aide » with no description → ask, and await the next turn (multi-turn)."""
        self._awaiting_description = True
        text = "Mode aide : décris-moi la tâche. T'as une notice à me montrer, ou je te fais le plan ?"
        intent = self._card(text, kind="help_ask_description", level="confirm")
        self._push(intent)
        return {"status": "awaiting_description", "text": text, "ui_intent": intent, "handled": True}

    @property
    def awaiting_description(self) -> bool:
        return self._awaiting_description

    def _card(self, text: str, *, kind: str, level: str = "confirm") -> dict[str, Any]:
        return {
            "type": "ui_intent", "ui_intent_id": str(uuid.uuid4()),
            "producer": "ultralive", "component": "context_card",
            "content": {"kind": kind, "text": text, "level": level},
            "truth_level": "observed", "confidence": 1.0, "priority": 0.55,
            "ttl_ms": 9000, "evidence_refs": [],
        }

    # ----------------------------------------------------------------- introspection
    def snapshot(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "task_id": self.plan.get("task_id") if self.plan else None,
            "current_index": self._current_index() if self.plan else None,
            "awaiting_description": self._awaiting_description,
            "metrics": dict(self.metrics),
        }


def _hint_from_reply(text: str) -> str:
    """A hint reply may be a bare sentence or a ``{"hint": "..."}`` JSON object
    (the VLM/LLM prompt asks for the latter). Pull the ``hint`` when present, else
    return the text as-is — never surface raw JSON to the user."""
    s = (text or "").strip()
    if "{" in s and "hint" in s:
        try:
            obj = json.loads(_extract_json_block(s))
            if isinstance(obj, dict) and obj.get("hint"):
                return str(obj["hint"]).strip()
        except Exception:
            pass
    return s


def _extract_json_block(text: str) -> str:
    """Pull a JSON object substring from a VLM reply that may wrap it in prose/fences."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        return s[start : end + 1]
    return s
