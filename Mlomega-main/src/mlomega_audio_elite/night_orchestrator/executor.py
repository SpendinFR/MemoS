"""E64-C generic window executor - budget/retry/subdivision/resume, lossless.

The engine that drives one stage's windows with the non-negotiable policies:

- **No prompt over budget.** Input tokens + reserved output + safety margin must
  fit the model context, or the call is refused and the window is subdivided.
- **No partial applied.** ``finish_reason=length``, timeout, invalid JSON or a
  failed contract never writes a cognitive output. On length the window is
  subdivided RECURSIVELY (fewer input units -> smaller output), never by bumping
  ``num_predict`` forever. A single unit that still truncates is quarantined.
- **Resume exactly once.** Every (sub)window is checkpointed by idempotent key;
  a restart skips completed/quarantined windows and never doubles outputs.
- **Thinking disabled for JSON contracts.** The output budget is reserved
  separately from the input budget.

This engine is decoupled from any business stage: it takes plain callables
(``render``, ``validate``) and a ``WindowLLM``. The real EpisodeBuilder/Brain2
adapter that wires it into the close-day is E64-F; no business prompt is touched
here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from . import checkpoint_store as cp
from .window_planner import PlannedWindow, PlanUnit, plan_windows, subdivide


@dataclass(frozen=True)
class ModelBudget:
    """Context accounting for one model. All values are token counts."""

    context_window: int
    output_reserve: int  # tokens reserved for the model's answer (num_predict)
    safety_margin: int = 256

    @property
    def max_input_tokens(self) -> int:
        return max(1, self.context_window - self.output_reserve - self.safety_margin)


@dataclass(frozen=True)
class LLMCallResult:
    """Outcome of one LLM call. ``error_kind`` drives the policy."""

    ok: bool
    data: Any = None
    finish_reason: str | None = None
    # one of: None (ok) | "length" | "timeout" | "unavailable" | "invalid_json" | "contract"
    error_kind: str | None = None


class WindowLLM(Protocol):
    """Minimal LLM contract the executor needs (real OllamaJsonClient wraps this)."""

    def generate(self, prompt: Mapping[str, Any], *, output_budget: int) -> LLMCallResult:
        ...


@dataclass
class WindowResult:
    window_key: str
    window_index: int
    state: str
    attempts: int = 0
    error_text: str | None = None
    primary_refs: tuple[str, ...] = ()


@dataclass
class StageResult:
    stage_name: str
    windows: list[WindowResult] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)

    @property
    def all_completed(self) -> bool:
        return bool(self.windows) and all(
            w.state == cp.STATE_COMPLETED for w in self.windows
        )

    @property
    def quarantined(self) -> list[WindowResult]:
        return [w for w in self.windows if w.state == cp.STATE_QUARANTINED]


@dataclass(frozen=True)
class StageScope:
    person_id: str
    package_date: str
    stage_name: str
    adapter_version: str
    prompt_version: str
    model: str


def _sleep_backoff(attempt: int, sleeper: Callable[[float], None]) -> None:
    # 0.0, 0.5, 1.0 ... bounded; injected sleeper keeps tests instant.
    sleeper(min(2.0, 0.5 * attempt))


def run_windows(
    units: Sequence[PlanUnit],
    *,
    con: Any,
    scope: StageScope,
    llm: WindowLLM,
    budget: ModelBudget,
    render: Callable[[Sequence[PlanUnit]], Mapping[str, Any]],
    validate: Callable[[Any], bool],
    decorate_output: Callable[[Any, Sequence[PlanUnit]], Any] | None = None,
    target_units: int = 45,
    overlap: int = 4,
    prompt_overhead_tokens: int = 512,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] | None = None,
) -> StageResult:
    """Plan, execute and checkpoint every window for one stage.

    ``render`` turns a window's units into a concrete prompt payload (the
    business prompt lives there in E64-F). ``validate`` returns True only if the
    output honours the stage contract. Returns a ``StageResult`` whose
    ``outputs`` are the validated per-window outputs, in window order.
    """
    cp.ensure_schema(con)
    # Checkpoints must survive a process kill or a later business-stage error.
    # The executor owns this connection while it runs; every state transition is
    # therefore committed deliberately instead of depending on an outer context
    # manager that could roll the entire run back.
    con.commit()
    sleeper = sleeper or (lambda _s: None)
    decorate_output = decorate_output or (lambda output, _units: output)
    result = StageResult(stage_name=scope.stage_name)

    planned = plan_windows(
        units,
        stage_name=scope.stage_name,
        max_input_tokens=budget.max_input_tokens,
        target_units=target_units,
        overlap=overlap,
    )

    def _estimate_input(window: PlannedWindow) -> int:
        # Budget on the units' DECLARED token cost (same basis as the planner),
        # plus a fixed prompt/schema overhead. The adapter is responsible for
        # PlanUnit.tokens reflecting the real per-unit prompt cost.
        return sum(u.tokens for u in window.units) + prompt_overhead_tokens

    def _split_and_recurse(window: PlannedWindow, key: str, error_text: str) -> bool:
        """Subdivide a window into children and drive them. Returns False if the
        window is a single unit (irreducible) - caller must quarantine it."""
        subs = subdivide(window, stage_name=scope.stage_name)
        if not subs:
            return False
        cp.mark_state(con, key, cp.STATE_SUBDIVIDED, error_text=error_text or None)
        con.commit()
        for sub in subs:
            _process(sub)
        return True

    def _quarantine(window: PlannedWindow, key: str, attempt: int, error_text: str) -> None:
        cp.mark_state(con, key, cp.STATE_QUARANTINED, error_text=error_text)
        con.commit()
        result.windows.append(
            WindowResult(
                key, window.spec.window_index, cp.STATE_QUARANTINED, attempt,
                error_text, tuple(window.spec.primary_refs),
            )
        )

    def _process(window: PlannedWindow) -> None:
        key = cp.window_key(
            person_id=scope.person_id, package_date=scope.package_date,
            stage_name=scope.stage_name, input_digest=window.spec.input_digest,
            window_index=window.spec.window_index, adapter_version=scope.adapter_version,
            prompt_version=scope.prompt_version, model=scope.model,
        )
        existing = cp.get_window(con, key)
        state = existing["state"] if existing else None

        # Resume: a leaf that already reached a durable end state is not redone.
        if state in (cp.STATE_COMPLETED, cp.STATE_QUARANTINED):
            result.windows.append(
                WindowResult(
                    key, window.spec.window_index, state, int(existing["attempts"]),
                    existing.get("error_text"), tuple(window.spec.primary_refs),
                ))
            if state == cp.STATE_COMPLETED:
                for out in cp.load_outputs(
                    con, person_id=scope.person_id, package_date=scope.package_date,
                    stage_name=scope.stage_name,
                ):
                    if out["window_key"] == key:
                        result.outputs.append(out["output"])
            return
        # Resume: a subdivided parent re-drives its children, no LLM call for it.
        if state == cp.STATE_SUBDIVIDED:
            subs = subdivide(window, stage_name=scope.stage_name)
            for sub in subs:
                _process(sub)
            return

        input_tokens = _estimate_input(window)
        cp.upsert_window(
            con, key=key, person_id=scope.person_id, package_date=scope.package_date,
            stage_name=scope.stage_name, input_digest=window.spec.input_digest,
            window_index=window.spec.window_index, adapter_version=scope.adapter_version,
            prompt_version=scope.prompt_version, model=scope.model,
            state=cp.STATE_RUNNING, input_tokens=input_tokens, output_budget=budget.output_reserve,
        )
        con.commit()

        # Refuse over-budget: subdivide, or quarantine a single oversized unit.
        if input_tokens > budget.max_input_tokens:
            if not _split_and_recurse(window, key, "input exceeds budget"):
                _quarantine(window, key, 0, "single unit exceeds input budget")
            return

        last_error = ""
        for attempt in range(1, max_attempts + 1):
            cp.bump_attempt(con, key)
            con.commit()
            call = llm.generate(render(window.units), output_budget=budget.output_reserve)

            if call.ok and validate(call.data):
                durable_output = decorate_output(call.data, window.primary_units)
                digest = cp.record_output(con, key, durable_output)
                cp.mark_state(con, key, cp.STATE_COMPLETED, output_digest=digest)
                con.commit()
                result.windows.append(
                    WindowResult(
                        key, window.spec.window_index, cp.STATE_COMPLETED, attempt,
                        None, tuple(window.spec.primary_refs),
                    )
                )
                result.outputs.append(durable_output)
                return

            if call.ok and not validate(call.data):
                # Bounded repair: one more try, then quarantine. Never apply it.
                last_error = "invalid output (contract)"
                if attempt >= 2:
                    _quarantine(window, key, attempt, last_error)
                    return
                continue

            kind = call.error_kind or "unknown"
            last_error = f"llm_error:{kind} finish={call.finish_reason}"
            if kind in ("length", "invalid_json", "contract"):
                # Output too big / malformed -> subdivide the INPUT and retry.
                if not _split_and_recurse(window, key, last_error):
                    _quarantine(window, key, attempt, last_error)
                return
            # Transient (timeout / unavailable): backoff and retry.
            if attempt < max_attempts:
                _sleep_backoff(attempt, sleeper)

        # Exhausted transient retries: retryable error, NOT applied, resumable.
        cp.mark_state(con, key, cp.STATE_ERROR, error_text=last_error)
        con.commit()
        result.windows.append(
            WindowResult(
                key, window.spec.window_index, cp.STATE_ERROR, max_attempts,
                last_error, tuple(window.spec.primary_refs),
            )
        )

    for window in planned:
        _process(window)
    return result
