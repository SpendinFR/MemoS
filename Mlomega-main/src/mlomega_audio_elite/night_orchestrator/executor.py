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

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from . import checkpoint_store as cp
from .evidence_ref import content_digest
from .stage_adapter import estimate_tokens_for_text
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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None


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


def _stage_call_reason(stage_name: str) -> dict[str, Any]:
    try:
        from .prompt_projection import stage_input_policy
        input_policy = stage_input_policy(stage_name)
    except Exception:
        input_policy = None
    return {
        "stage_name": stage_name,
        "why_called": "validated_semantic_contract_required",
        "input_policy": input_policy or "stage_specific_projected_evidence",
    }


def _produced_fact_summary(value: Any) -> dict[str, Any]:
    """Compact telemetry only; the complete validated output stays in its table."""
    identifiers: list[str] = []
    sections: dict[str, int] = {}

    def visit(node: Any, path: str = "", depth: int = 0) -> None:
        if depth > 8 or len(identifiers) >= 256:
            return
        if isinstance(node, Mapping):
            for key, item in node.items():
                child = f"{path}.{key}" if path else str(key)
                lowered = str(key).lower()
                if lowered.endswith(("_id", "_ref")) and item not in (None, ""):
                    identifiers.append(f"{child}={item}")
                elif lowered.endswith(("_ids", "_refs")) and isinstance(item, (list, tuple)):
                    for value_ in item[:64]:
                        identifiers.append(f"{child}={value_}")
                visit(item, child, depth + 1)
        elif isinstance(node, list):
            if path and depth <= 2:
                sections[path] = len(node)
            for item in node:
                visit(item, path, depth + 1)

    visit(value)
    return {
        "output_digest": content_digest(value),
        "section_counts": sections,
        "identifiers": identifiers,
    }


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
    normalize_output: Callable[[Any, Sequence[PlanUnit]], Any] | None = None,
    render_window: Callable[[PlannedWindow], Mapping[str, Any]] | None = None,
    normalize_window_output: Callable[[Any, PlannedWindow], Any] | None = None,
    decorate_output: Callable[[Any, Sequence[PlanUnit]], Any] | None = None,
    describe_contract_violation: Callable[[Any, PlannedWindow], Mapping[str, Any]] | None = None,
    resolve_contract_rejection: Callable[..., bool] | None = None,
    target_units: int = 45,
    overlap: int = 4,
    prompt_overhead_tokens: int = 512,
    max_attempts: int = 3,
    subdivide_on_length: bool = True,
    sleeper: Callable[[float], None] | None = None,
    parallel_workers: int = 1,
    connection_factory: Callable[[], Any] | None = None,
    _planned_windows: Sequence[PlannedWindow] | None = None,
    _schema_ready: bool = False,
) -> StageResult:
    """Plan, execute and checkpoint every window for one stage.

    ``render`` turns a window's units into a concrete prompt payload (the
    business prompt lives there in E64-F). ``validate`` returns True only if the
    output honours the stage contract. Returns a ``StageResult`` whose
    ``outputs`` are the validated per-window outputs, in window order.
    """
    if not _schema_ready:
        cp.ensure_schema(con)
    # Checkpoints must survive a process kill or a later business-stage error.
    # The executor owns this connection while it runs; every state transition is
    # therefore committed deliberately instead of depending on an outer context
    # manager that could roll the entire run back.
    con.commit()
    sleeper = sleeper or (lambda _s: None)
    normalize_output = normalize_output or (lambda output, _units: output)
    decorate_output = decorate_output or (lambda output, _units: output)
    result = StageResult(stage_name=scope.stage_name)

    # Plan against the same complete budget later enforced before the call.
    # Previously the fixed prompt/schema overhead was added only after planning,
    # which created doomed parent windows and needless recursive subdivisions.
    planning_input_budget = max(
        1, budget.max_input_tokens - max(0, int(prompt_overhead_tokens))
    )
    planned = list(_planned_windows) if _planned_windows is not None else plan_windows(
        units,
        stage_name=scope.stage_name,
        max_input_tokens=planning_input_budget,
        target_units=target_units,
        overlap=overlap,
    )

    # PRO-only callers may execute independent, already-planned top-level windows
    # concurrently.  Every worker owns a separate SQLite connection and drives its
    # own retry/subdivision tree; the parent merely rejoins StageResults in planner
    # order.  Local callers do not pass these options and keep the historic loop
    # below byte-for-byte in effect.
    worker_count = max(1, int(parallel_workers or 1))
    if worker_count > 1 and len(planned) > 1:
        if connection_factory is None:
            raise ValueError("parallel run_windows requires connection_factory")

        def _run_one(window: PlannedWindow) -> StageResult:
            with connection_factory() as worker_con:
                return run_windows(
                    (),
                    con=worker_con,
                    scope=scope,
                    llm=llm,
                    budget=budget,
                    render=render,
                    validate=validate,
                    normalize_output=normalize_output,
                    render_window=render_window,
                    normalize_window_output=normalize_window_output,
                    decorate_output=decorate_output,
                    describe_contract_violation=describe_contract_violation,
                    resolve_contract_rejection=resolve_contract_rejection,
                    target_units=target_units,
                    overlap=overlap,
                    prompt_overhead_tokens=prompt_overhead_tokens,
                    max_attempts=max_attempts,
                    subdivide_on_length=subdivide_on_length,
                    sleeper=sleeper,
                    parallel_workers=1,
                    _planned_windows=(window,),
                    _schema_ready=True,
                )

        completed: dict[int, StageResult] = {}
        with ThreadPoolExecutor(
            max_workers=min(worker_count, len(planned)),
            thread_name_prefix="mlomega-night-window",
        ) as pool:
            futures = {
                pool.submit(copy_context().run, _run_one, window): index
                for index, window in enumerate(planned)
            }
            for future in as_completed(futures):
                completed[futures[future]] = future.result()
        for index in range(len(planned)):
            child = completed[index]
            result.windows.extend(child.windows)
            result.outputs.extend(child.outputs)
        return result

    def _estimate_input(window: PlannedWindow, prompt: Mapping[str, Any]) -> int:
        # Enforce the budget against the concrete rendered request, not only the
        # evidence units. Hierarchical adapters add paths, digests, refs, shared
        # context and an executable schema; on V14 Interpersonal those wrappers
        # made a real 24,347-token request look like 17,043 tokens. Keep declared
        # accounting as a lower bound for adapters with opaque prompt objects.
        declared = sum(u.tokens for u in window.units) + prompt_overhead_tokens
        rendered = estimate_tokens_for_text(
            json.dumps(prompt, ensure_ascii=False, sort_keys=True, default=str)
        )
        return max(declared, rendered)

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

    def _resolve_rejection(
        window: PlannedWindow,
        key: str,
        attempt: int,
        input_digest: str,
        violations: Mapping[str, Any],
    ) -> bool:
        """Run the stage's deterministic alternative strategy for a rejected window.

        The stage owns the escalation (local JSON repair, a targeted repair prompt
        that quotes the precise violations, or a split-into-two-sub-windows + merge
        + lossless re-verification). The callback receives a context carrying the
        live checkpoint connection, scope, budget, the shared ``StageResult`` and a
        ``drive`` hook that runs a child ``PlannedWindow`` through this very executor
        (so every child is budgeted/validated/checkpointed identically and appended
        to the parent result). It returns True only when it has durably produced and
        validated ALL of the window's replacement child output(s); the parent is
        then recorded SUBDIVIDED (its work lives in the children, exactly like the
        length-subdivision path) and never re-driven on resume. On any incomplete
        coverage the callback fails closed and returns False, and we quarantine.
        """
        context = {
            "con": con,
            "scope": scope,
            "budget": budget,
            "llm": llm,
            "window": window,
            "window_key": key,
            "attempt": attempt,
            "input_digest": input_digest,
            "violations": dict(violations),
            "result": result,
            "drive": _process,
        }
        try:
            handled = bool(resolve_contract_rejection(window, context))
        except Exception as exc:
            cp.record_call_telemetry(
                con, window_key=key, attempt=attempt,
                person_id=scope.person_id, package_date=scope.package_date,
                stage_name=scope.stage_name, model=scope.model,
                why_called=_stage_call_reason(scope.stage_name),
                facts_read={}, facts_produced={"resolve_error": str(exc)[:200]},
                cache_hit=False, estimated_input_tokens=None,
                provider_input_tokens=None, provider_output_tokens=None,
                output_budget=budget.output_reserve, latency_ms=0,
                outcome="contract_resolution_failed", error_kind="contract",
            )
            con.commit()
            return False
        if not handled:
            return False
        # The alternative strategy durably produced the replacement child outputs
        # (appended to ``result`` via the drive hook). Mark the parent subdivided so
        # a resume re-reads the children, never the parent, and does NOT count the
        # parent as a leaf for ``all_completed``.
        cp.mark_state(con, key, cp.STATE_SUBDIVIDED,
                      error_text="contract_rejection_resolved_by_split")
        con.commit()
        return True

    def _process(window: PlannedWindow) -> None:
        # The plan digest covers per-unit content, but adapters also carry shared
        # context (bundle, rules, schemas, prior outputs) in the rendered prompt.
        # Fingerprint the exact LLM request before resume lookup so changing any
        # common input can never reuse a stale validated checkpoint.
        prompt = (
            render_window(window)
            if render_window is not None
            else render(window.units)
        )
        effective_input_digest = content_digest({
            "planned_input_digest": window.spec.input_digest,
            "rendered_prompt_digest": content_digest(prompt),
        })
        key = cp.window_key(
            person_id=scope.person_id, package_date=scope.package_date,
            stage_name=scope.stage_name, input_digest=effective_input_digest,
            window_index=window.spec.window_index, adapter_version=scope.adapter_version,
            prompt_version=scope.prompt_version, model=scope.model,
        )
        existing = cp.get_window(con, key)
        state = existing["state"] if existing else None
        facts_read = {
            "primary_refs": list(window.spec.primary_refs),
            "overlap_refs": list(window.spec.overlap_refs),
        }
        why_called = _stage_call_reason(scope.stage_name)

        # Resume: a leaf that already reached a durable end state is not redone.
        # EXCEPTION (Codex post-#6): a window quarantined for a CONTRACT rejection
        # BEFORE the deterministic alternative strategy existed (proof: no row in
        # night_llm_contract_rejections_v19 for this exact input) never exhausted
        # that strategy — its quarantine is not final. When the stage now provides
        # one, re-drive the window: the first call captures the rejection with its
        # full audit detail, the identical-retry ban then hands over to the
        # alternative strategy. A quarantine that already went through the ladder
        # (rejection rows exist) stays terminal.
        if state == cp.STATE_QUARANTINED and (
            resolve_contract_rejection is not None
            and str(existing.get("error_text") or "") == "invalid output (contract)"
            and not cp.window_has_contract_rejection(
                con, window_key=key, input_digest=effective_input_digest
            )
        ):
            state = None
        # An OVER-BUDGET single-unit quarantine is NEVER final on resume: the input
        # budget (``context_window``) is NOT part of the checkpoint key and may have
        # grown between runs (Gate B 014448: the PRO engine-field budget was lifted
        # from the local ~24k to the DeepSeek context, so a ~29k bundle prefix now
        # fits), or a resolver may now be available to split it. Re-drive it: if it
        # now fits it completes; otherwise it re-quarantines identically (idempotent).
        if state == cp.STATE_QUARANTINED and (
            str(existing.get("error_text") or "") == "single unit exceeds input budget"
        ):
            state = None
        # A LENGTH quarantine (the model's OUTPUT was truncated, finish=length) is
        # likewise not final on resume: the output budget (``output_reserve``) is NOT
        # part of the checkpoint key and may have grown between runs (Gate B 183352:
        # the PRO v14 hierarchical output cap was lifted from the local 4096 to
        # DeepSeek's 8192, so a clarification output that truncated now fits).
        # Re-drive it: if it now fits it completes; otherwise it re-quarantines
        # identically (idempotent, still fail-closed on a genuinely oversized output).
        if state == cp.STATE_QUARANTINED and (
            str(existing.get("error_text") or "").startswith("llm_error:length")
        ):
            state = None
        if state in (cp.STATE_COMPLETED, cp.STATE_QUARANTINED):
            if state == cp.STATE_COMPLETED:
                cp.record_call_telemetry(
                    con, window_key=key, attempt=0,
                    person_id=scope.person_id, package_date=scope.package_date,
                    stage_name=scope.stage_name, model=scope.model,
                    why_called=why_called, facts_read=facts_read,
                    facts_produced={"output_digest": existing.get("output_digest")},
                    cache_hit=True,
                    estimated_input_tokens=existing.get("input_tokens"),
                    provider_input_tokens=None, provider_output_tokens=None,
                    output_budget=existing.get("output_budget"), latency_ms=0,
                    outcome="checkpoint_reuse",
                )
                con.commit()
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
            resume_error = str(existing.get("error_text") or "")
            if resume_error.startswith("contract_rejection_resolved_by_split"):
                # This parent was resolved by the stage's contract-split strategy,
                # whose child windows carry the strategy's own keys (not the length
                # subdivision's). Re-run the same deterministic strategy: it is
                # idempotent — every checkpointed child window resumes as COMPLETED
                # and no LLM call is repaid. Nothing else can reconstruct those
                # children (their indexes/refs are the strategy's), so this is the
                # only resume path that keeps the resolved window lossless.
                if resolve_contract_rejection is not None and _resolve_rejection(
                    window, key, int(existing.get("attempts") or 0),
                    effective_input_digest, {"rule": "resume_resolved_split"},
                ):
                    return
                _quarantine(
                    window, key, int(existing.get("attempts") or 0),
                    "invalid output (contract)",
                )
                return
            if not subdivide_on_length and resume_error.startswith("llm_error:length"):
                # A higher-level adapter may need to split OUTPUT schemas rather
                # than input evidence. Convert an older/resumed subdivision into
                # an explicit terminal signal and do not re-drive its children.
                _quarantine(window, key, int(existing.get("attempts") or 0), resume_error or "llm_error:length")
                return
            subs = subdivide(window, stage_name=scope.stage_name)
            for sub in subs:
                _process(sub)
            return

        input_tokens = _estimate_input(window, prompt)
        cp.upsert_window(
            con, key=key, person_id=scope.person_id, package_date=scope.package_date,
            stage_name=scope.stage_name, input_digest=effective_input_digest,
            window_index=window.spec.window_index, adapter_version=scope.adapter_version,
            prompt_version=scope.prompt_version, model=scope.model,
            state=cp.STATE_RUNNING, input_tokens=input_tokens, output_budget=budget.output_reserve,
        )
        con.commit()

        # Refuse over-budget. First try the planner subdivision (halves the
        # window's PRIMARY UNITS). A single oversized unit cannot be halved that
        # way; before quarantining it, hand it to the stage's deterministic
        # resolver, which splits the unit BY ITS TURNS into contiguous, exclusively
        # owned ranges (read-only overlap context, lossless merge re-verified) —
        # exactly the detail/segmentation ``_resolve_rejection``. The reason and
        # the split are persisted; a resume repays no model call (Codex option A).
        if input_tokens > budget.max_input_tokens:
            if _split_and_recurse(window, key, "input exceeds budget"):
                return
            if resolve_contract_rejection is not None:
                violations = {
                    "rule": "single_unit_exceeds_input_budget",
                    "input_tokens": int(input_tokens),
                    "max_input_tokens": int(budget.max_input_tokens),
                }
                cp.record_contract_rejection(
                    con, window_key=key, attempt=0,
                    person_id=scope.person_id, package_date=scope.package_date,
                    stage_name=scope.stage_name, model=scope.model,
                    strategy="over_budget_single_unit",
                    input_digest=effective_input_digest,
                    raw_output=None, parsed_output=None, violations=violations,
                )
                con.commit()
                if _resolve_rejection(window, key, 0, effective_input_digest, violations):
                    return
            _quarantine(window, key, 0, "single unit exceeds input budget")
            return

        last_error = ""
        for attempt in range(1, max_attempts + 1):
            # Refuse a PROVEN-identical retry before spending it. When the stage
            # provides a deterministic alternative strategy it also guarantees a
            # deterministic model (temperature 0) and an UNCHANGED prompt for this
            # window (same effective_input_digest), so once a contract rejection
            # exists for this exact input a strict retry is guaranteed to reproduce
            # it. Skip the call and hand over to the alternative strategy (or
            # quarantine): the 2nd strictly-identical request never leaves the host.
            # Without a strategy the historic bounded repair (one distinct extra
            # attempt) is preserved for callers that rely on it.
            if (
                attempt > 1
                and resolve_contract_rejection is not None
                and cp.window_has_contract_rejection(
                    con, window_key=key, input_digest=effective_input_digest
                )
            ):
                last_error = "invalid output (contract)"
                if _resolve_rejection(
                    window, key, attempt - 1, effective_input_digest,
                    {"rule": "identical_retry_refused"},
                ):
                    return
                _quarantine(window, key, attempt - 1, last_error)
                return

            cp.bump_attempt(con, key)
            con.commit()
            call = llm.generate(prompt, output_budget=budget.output_reserve)

            candidate = call.data
            if call.ok:
                try:
                    candidate = (
                        normalize_window_output(call.data, window)
                        if normalize_window_output is not None
                        else normalize_output(call.data, window.units)
                    )
                except Exception:
                    candidate = None

            if call.ok and validate(candidate):
                durable_output = decorate_output(candidate, window.primary_units)
                digest = cp.record_output(con, key, durable_output)
                cp.record_call_telemetry(
                    con, window_key=key, attempt=attempt,
                    person_id=scope.person_id, package_date=scope.package_date,
                    stage_name=scope.stage_name, model=scope.model,
                    why_called=why_called, facts_read=facts_read,
                    facts_produced=_produced_fact_summary(durable_output),
                    cache_hit=False, estimated_input_tokens=input_tokens,
                    provider_input_tokens=call.prompt_tokens,
                    provider_output_tokens=call.completion_tokens,
                    output_budget=budget.output_reserve, latency_ms=call.latency_ms,
                    outcome="validated", finish_reason=call.finish_reason,
                )
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

            if call.ok and not validate(candidate):
                # A contract rejection is never lost: persist the raw model output,
                # the parsed candidate, the precise violations and the digests so
                # the audit shows WHICH rule failed on WHICH value, and so a
                # byte-identical retry can be detected and REFUSED.
                last_error = "invalid output (contract)"
                strategy = "initial" if attempt == 1 else "repeat"
                try:
                    violations = (
                        dict(describe_contract_violation(candidate, window))
                        if describe_contract_violation is not None
                        else {"rule": "contract_validate_false"}
                    )
                except Exception as exc:
                    violations = {"rule": "contract_validate_false",
                                  "describe_error": str(exc)[:200]}
                # Compute the raw-output digest and check it against PRIOR rejections
                # of this window BEFORE persisting the current one. If this exact
                # (window, input, output) triplet already appeared, the model just
                # produced a strictly identical rejected answer: a retry is proven
                # pointless (temperature 0) and is FORBIDDEN — we escalate/quarantine
                # instead of paying another identical call (economy + honesty).
                output_digest = cp.content_output_digest(call.data)
                identical_retry = cp.contract_rejection_seen(
                    con, window_key=key, input_digest=effective_input_digest,
                    output_digest=output_digest,
                )
                cp.record_contract_rejection(
                    con, window_key=key, attempt=attempt,
                    person_id=scope.person_id, package_date=scope.package_date,
                    stage_name=scope.stage_name, model=scope.model,
                    strategy=strategy, input_digest=effective_input_digest,
                    raw_output=call.data, parsed_output=candidate,
                    violations=violations, finish_reason=call.finish_reason,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                )
                cp.record_call_telemetry(
                    con, window_key=key, attempt=attempt,
                    person_id=scope.person_id, package_date=scope.package_date,
                    stage_name=scope.stage_name, model=scope.model,
                    why_called=why_called, facts_read=facts_read,
                    facts_produced={"rejection_output_digest": output_digest,
                                    "violations": violations, "strategy": strategy,
                                    "identical_retry": identical_retry},
                    cache_hit=False,
                    estimated_input_tokens=input_tokens,
                    provider_input_tokens=call.prompt_tokens,
                    provider_output_tokens=call.completion_tokens,
                    output_budget=budget.output_reserve, latency_ms=call.latency_ms,
                    outcome="contract_rejected", finish_reason=call.finish_reason,
                    error_kind="contract",
                )
                con.commit()
                # Escalate to the stage's deterministic alternative strategy either
                # when a retry is proven identical, or once the bounded repair budget
                # (one distinct extra attempt) is exhausted. Never apply a partial.
                exhausted = identical_retry or attempt >= 2
                if exhausted and resolve_contract_rejection is not None:
                    handled = _resolve_rejection(
                        window, key, attempt, effective_input_digest, violations
                    )
                    if handled:
                        return
                    _quarantine(window, key, attempt, last_error)
                    return
                if exhausted:
                    _quarantine(window, key, attempt, last_error)
                    return
                continue

            kind = call.error_kind or "unknown"
            last_error = f"llm_error:{kind} finish={call.finish_reason}"
            cp.record_call_telemetry(
                con, window_key=key, attempt=attempt,
                person_id=scope.person_id, package_date=scope.package_date,
                stage_name=scope.stage_name, model=scope.model,
                why_called=why_called, facts_read=facts_read,
                facts_produced={}, cache_hit=False,
                estimated_input_tokens=input_tokens,
                provider_input_tokens=call.prompt_tokens,
                provider_output_tokens=call.completion_tokens,
                output_budget=budget.output_reserve, latency_ms=call.latency_ms,
                outcome="provider_error", finish_reason=call.finish_reason,
                error_kind=kind,
            )
            con.commit()
            if kind in ("length", "invalid_json", "contract"):
                # Output too big / malformed -> subdivide the INPUT and retry.
                if kind == "length" and not subdivide_on_length:
                    _quarantine(window, key, attempt, last_error)
                elif not _split_and_recurse(window, key, last_error):
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
