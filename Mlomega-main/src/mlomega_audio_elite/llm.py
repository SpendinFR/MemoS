from __future__ import annotations

import json
import math
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any

from .config import get_settings
from .runtime_v18_7 import classify_failure, record_phase_event, retry_operation, runtime_phase


class EliteLLMError(RuntimeError):
    """Base local-LLM failure."""

    def __init__(self, message: str, *, raw: str = "", finish_reason: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw
        self.finish_reason = finish_reason


class LLMTruncatedOutputError(EliteLLMError):
    """Provider stopped at an output/token boundary before a complete answer."""


class LLMContractError(EliteLLMError):
    """The model returned JSON that violates the declared executable contract."""


class LLMInvalidJsonError(LLMContractError):
    """The provider returned a completed response that is not a usable JSON object."""


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any]
    raw: str = ""
    error: str | None = None
    error_kind: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _is_post_stop_phase() -> bool:
    return runtime_phase().startswith("post_stop")


def _short_caller(*, skip: int = 2, depth: int = 4) -> str:
    """A compact caller signature (module:function@line chain) for load tracing.

    Point 4 (Gate B): we must never again GUESS which module loads which model in
    which phase. Every Ollama/llama.cpp request records the short call stack of the
    site that triggered it, so a resident 9B in a live/post-stop phase is instantly
    attributable to its caller."""
    import inspect

    frames: list[str] = []
    try:
        stack = inspect.stack()
    except Exception:
        return "unknown"
    try:
        for frame_info in stack[skip: skip + depth]:
            module = frame_info.frame.f_globals.get("__name__", "?")
            frames.append(f"{module}:{frame_info.function}@{frame_info.lineno}")
    finally:
        del stack
    return " <- ".join(frames) if frames else "unknown"


def effective_ollama_timeout(requested: float, *, poststop_min_timeout_s: float | None = None) -> float:
    settings = get_settings()
    requested = max(1.0, float(requested))
    if _is_post_stop_phase():
        # The first local model invocation may need to load gigabytes.  Never
        # lower an explicit caller timeout, but guard against old 45/180s hard
        # defaults in the daily closure.  VLM uses its own lower phase budget.
        return max(requested, poststop_min_timeout_s or settings.poststop_llm_timeout_s)
    return requested


def ollama_generate(
    payload: dict[str, Any],
    *,
    base_url: str | None = None,
    timeout: float,
    component: str,
    retry_max: int | None = None,
    poststop_min_timeout_s: float | None = None,
) -> dict[str, Any]:
    """Single retrying local Ollama transport for LLM and VLM callers."""
    settings = get_settings()
    url = (base_url or settings.ollama_base_url).rstrip("/") + "/api/generate"
    effective_timeout_s = effective_ollama_timeout(timeout, poststop_min_timeout_s=poststop_min_timeout_s)
    body = dict(payload)
    # Structured project calls consume ``response``. Qwen3.5 otherwise spends
    # the output budget in its separate ``thinking`` field and may return an
    # empty response, which is not a valid JSON contract result.
    body.setdefault("think", False)
    body.setdefault(
        "keep_alive",
        settings.ollama_keep_alive_poststop if _is_post_stop_phase() else settings.ollama_keep_alive_live,
    )

    def request_once() -> dict[str, Any]:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=effective_timeout_s) as response:
            raw = response.read().decode("utf-8")
        try:
            outer = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMInvalidJsonError(f"Ollama outer response is not JSON: {exc}", raw=raw) from exc
        if not isinstance(outer, dict):
            raise LLMInvalidJsonError("Ollama outer response is not an object", raw=raw)
        if outer.get("error"):
            raise EliteLLMError(f"Ollama returned error: {outer['error']}")
        return outer

    record_phase_event("ollama_request", component=component, model=body.get("model"), timeout_s=effective_timeout_s)
    # Interactive live calls have a user-visible deadline. Reusing the nightly
    # retry policy here turned one 20 s help request into three attempts plus the
    # 15 s/60 s post-stop backoffs (137 s measured on 20260718). A live timeout is
    # an honest immediate degrade; durable post-stop callers keep their bounded
    # recovery retries.
    effective_retry_max = (
        retry_max
        if retry_max is not None
        else (settings.poststop_retry_max if _is_post_stop_phase() else 0)
    )
    return retry_operation(
        request_once,
        component=component,
        max_retries=effective_retry_max,
        on_retry=lambda attempt, failure, delay: record_phase_event(
            "ollama_retry", component=component, model=body.get("model"), attempt=attempt, error_code=failure.code, delay_s=delay
        ),
    )


def llamacpp_chat_json(
    *,
    base_url: str,
    model: str,
    system: str,
    prompt: str,
    json_schema: dict[str, Any] | None,
    max_output_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    """Call llama.cpp's OpenAI-compatible endpoint with a strict JSON grammar.

    The direct backend is opt-in (``MLOMEGA_LLM_BACKEND=llamacpp``). It keeps
    the same executable project contract as Ollama; only the local transport is
    different.
    """
    url = base_url.rstrip("/") + "/v1/chat/completions"
    effective_timeout_s = effective_ollama_timeout(timeout)
    response_format: dict[str, Any]
    if json_schema:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "mlomega_contract",
                "strict": True,
                "schema": json_schema,
            },
        }
    else:
        response_format = {"type": "json_object"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": prompt + "\n\nReturn one compact JSON object only.",
            },
        ],
        "stream": False,
        "temperature": 0.0,
        "max_tokens": int(max_output_tokens),
        "response_format": response_format,
    }

    def request_once() -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=effective_timeout_s) as response:
            raw = response.read().decode("utf-8")
        try:
            outer = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMInvalidJsonError(
                f"llama.cpp outer response is not JSON: {exc}", raw=raw
            ) from exc
        if not isinstance(outer, dict):
            raise LLMInvalidJsonError("llama.cpp outer response is not an object", raw=raw)
        if outer.get("error"):
            raise EliteLLMError(f"llama.cpp returned error: {outer['error']}")
        return outer

    record_phase_event(
        "llamacpp_request",
        component="llamacpp_json",
        model=model,
        timeout_s=effective_timeout_s,
    )
    return retry_operation(request_once, component="llamacpp_json")


def ollama_unload(*, model: str | None = None, base_url: str | None = None) -> None:
    """Ask Ollama to expire a model after a heavyweight phase; best effort only."""
    settings = get_settings()
    if not model:
        return
    try:
        payload = {"model": model, "keep_alive": "0"}
        req = urllib.request.Request(
            (base_url or settings.ollama_base_url).rstrip("/") + "/api/generate",
            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=settings.ollama_connect_timeout_s):
            pass
        record_phase_event("ollama_unload", model=model)
    except Exception as exc:
        record_phase_event("ollama_unload_failed", model=model, error=str(exc)[:200])


def _schema_hint_to_json_schema(hint: Any) -> dict[str, Any]:
    """Translate the project's executable schema templates for Ollama.

    The same template remains validated after generation by
    ``_validate_schema_hint``.  Sending the equivalent JSON Schema to Ollama
    prevents the model from omitting required keys or changing their types in
    the first place instead of spending a repair pass on avoidable syntax.
    """
    if hint is None:
        return {}
    if isinstance(hint, dict):
        properties = {key: _schema_hint_to_json_schema(value) for key, value in hint.items()}
        required = [key for key, value in hint.items() if value is not None]
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        return schema
    if isinstance(hint, list):
        return {
            "type": "array",
            "items": _schema_hint_to_json_schema(hint[0]) if hint else {},
        }
    if isinstance(hint, bool):
        return {"type": "boolean"}
    if isinstance(hint, (int, float)):
        return {"type": "number"}
    if isinstance(hint, str):
        choices = [part.strip() for part in hint.split("|")]
        if len(choices) > 1 and all(choices):
            return {"type": "string", "enum": choices}
        return {"type": "string"}
    return {}


def _tighten_hot_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the semantic bounds already enforced by the BrainLive hot gate."""
    props = schema.get("properties") or {}

    def obj(node: dict[str, Any], key: str) -> dict[str, Any]:
        return ((node.get("properties") or {}).get(key) or {})

    def bounded_array(node: dict[str, Any], key: str, maximum: int) -> None:
        target = obj(node, key)
        if target.get("type") == "array":
            target["maxItems"] = maximum

    def probability(node: dict[str, Any], key: str) -> None:
        target = obj(node, key)
        if target.get("type") == "number":
            target.update({"minimum": 0.0, "maximum": 1.0})

    world = props.get("world_state") or {}
    for key in ("who_is_active", "probable_activity"):
        bounded_array(world, key, 6)
    for key in ("evidence", "counter_evidence", "missing_evidence"):
        bounded_array(world, key, 4)
    probability(world, "confidence")

    horizons = props.get("horizons") or {}
    for name in ("H0", "H1", "H2"):
        horizon = obj(horizons, name)
        for key in ("needs", "risks_or_opportunities", "intervention_candidates", "watch_next"):
            bounded_array(horizon, key, 4)
        for key in ("evidence", "counter_evidence"):
            bounded_array(horizon, key, 4)
        probability(horizon, "confidence")

    predictions = props.get("active_predictions") or {}
    predictions["maxItems"] = 3
    prediction = predictions.get("items") or {}
    for key in ("evidence", "counter_evidence", "what_would_confirm", "what_would_refute"):
        bounded_array(prediction, key, 4)
    probability(prediction, "probability")
    probability(prediction, "confidence")

    proactive = props.get("proactive_decision") or {}
    for key in ("evidence", "counter_evidence"):
        bounded_array(proactive, key, 4)
    for key in ("expected_gain", "intrusion_cost", "confidence"):
        probability(proactive, key)

    for key in ("notes_for_brain2", "uncertainties", "needs_evidence"):
        bounded_array(schema, key, 4)
    return schema


def json_schema_for_hint(hint: dict[str, Any]) -> dict[str, Any]:
    """Build the provider schema corresponding to an executable hint."""
    schema = _schema_hint_to_json_schema(hint)
    if {"world_state", "horizons", "proactive_decision"} <= set(hint):
        schema = _tighten_hot_json_schema(schema)
    return schema


class OllamaJsonClient:
    """Strict local LLM JSON client with explicit output-budget/truncation state.

    A parse failure used to collapse timeout, malformed JSON and provider output
    limits into one opaque string.  V18.4 makes those states observable so the
    durable decision worker can retry transient faults and quarantine malformed
    responses without silently treating them as an empty success.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        backend: str | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.enable_ollama:
            raise EliteLLMError("MLOMEGA_ENABLE_OLLAMA=false refusé: l'analyse élite exige Ollama/Qwen.")
        # ``backend=`` is an EXPLICIT override for callers that are Ollama by
        # construction (live providers, fine-intel). Under the process-wide
        # MLOMEGA_LLM_BACKEND=llamacpp, a caller passing an Ollama base_url but
        # no model would otherwise fall back to the llama.cpp P1 alias and hit
        # Ollama's OpenAI endpoint with an unknown model -> HTTP 404 (proven on
        # Gate B run 20260717-115157).
        self.backend = (
            backend or os.environ.get("MLOMEGA_LLM_BACKEND", "ollama")
        ).strip().lower()
        if self.backend == "llamacpp":
            self.base_url = (
                base_url
                or os.environ.get("MLOMEGA_LLAMACPP_BASE_URL")
                or "http://127.0.0.1:8080"
            ).rstrip("/")
            self.model = (
                model
                or os.environ.get("MLOMEGA_LLAMACPP_MODEL")
                or "qwen9b-p3-mlomega"
            )
        elif self.backend == "ollama":
            self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
            self.model = model or (
                settings.ollama_model if _is_post_stop_phase() else settings.ollama_live_model
            )
        else:
            raise EliteLLMError(
                f"MLOMEGA_LLM_BACKEND inconnu: {self.backend!r} (ollama|llamacpp)"
            )

    def generate_json(
        self,
        system: str,
        prompt: str,
        schema_hint: dict[str, Any] | None = None,
        timeout: float = 60,
        *,
        max_output_tokens: int | None = None,
        format_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        try:
            if _is_post_stop_phase():
                configured = int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"))
            else:
                configured = int(os.environ.get("MLOMEGA_V18_LLM_MAX_OUTPUT_TOKENS", "900"))
        except ValueError:
            configured = 4096 if _is_post_stop_phase() else 900
        budget = max(32, int(max_output_tokens if max_output_tokens is not None else configured))
        json_schema = format_schema or (json_schema_for_hint(schema_hint) if schema_hint else None)
        payload = {
            "model": self.model,
            "prompt": f"SYSTEM:\n{system}\n\nUSER:\n{prompt}\n\nReturn one compact JSON object only.",
            "stream": False,
            # Qwen 3.x otherwise spends the bounded response budget on hidden
            # reasoning before emitting the required JSON and can finish with
            # done_reason=length. Strict schema calls need the answer, not a
            # separate thinking trace.
            "think": False,
            "format": json_schema or "json",
            # num_ctx is the total prompt + response window.  Ollama otherwise
            # defaults to 4096 on this workstation, which made a 4096-token
            # post-stop response budget physically impossible once a prompt was
            # present.  Keep live latency small; give per-bundle CloseDay work a
            # measured 16k window (Qwen3.5:9b remains fully GPU-resident on 8GB).
            "options": {
                "temperature": 0.0,
                "num_predict": budget,
                "num_ctx": (
                    get_settings().ollama_context_poststop
                    if _is_post_stop_phase()
                    else get_settings().ollama_context_live
                ),
            },
        }
        # Point 4 (Gate B): make every model load attributable. Journal the exact
        # phase, the model that will REALLY be used, the backend, and the caller
        # chain BEFORE the request leaves — so a resident 9B in a live/post-stop
        # phase can never again be a mystery to be guessed from side effects.
        record_phase_event(
            "llm_client_generate",
            component="ollama_json_client",
            backend=self.backend,
            model=self.model,
            post_stop=_is_post_stop_phase(),
            output_budget=budget,
            caller=_short_caller(),
        )
        raw_outer = ""
        response_text = ""
        finish_reason: str | None = None
        try:
            if self.backend == "llamacpp":
                outer = llamacpp_chat_json(
                    base_url=self.base_url,
                    model=self.model,
                    system=system,
                    prompt=prompt,
                    json_schema=json_schema,
                    max_output_tokens=budget,
                    timeout=timeout,
                )
                choices = outer.get("choices") or []
                choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                message = choice.get("message") if isinstance(choice, dict) else {}
                response_text = str(
                    message.get("content", "") if isinstance(message, dict) else ""
                )
                finish_reason = str(choice.get("finish_reason") or "") or None
            else:
                outer = ollama_generate(
                    payload,
                    base_url=self.base_url,
                    timeout=timeout,
                    component="ollama_json",
                )
                response_text = str(outer.get("response", ""))
                finish_reason = str(outer.get("done_reason") or outer.get("finish_reason") or "") or None
            raw_outer = json.dumps(outer, ensure_ascii=False)
            if self.backend == "llamacpp":
                usage = outer.get("usage") if isinstance(outer, dict) else None
                prompt_tokens = int((usage or {}).get("prompt_tokens") or 0) or None
                completion_tokens = int((usage or {}).get("completion_tokens") or 0) or None
            else:
                prompt_tokens = int(outer.get("prompt_eval_count") or 0) or None
                completion_tokens = int(outer.get("eval_count") or 0) or None
            if (self.backend == "ollama" and outer.get("done") is False) or (finish_reason and finish_reason.lower() in {"length", "max_tokens", "token_limit", "limit"}):
                return LLMResult(
                    ok=False,
                    data={},
                    raw=response_text,
                    error=f"LLM output truncated (finish_reason={finish_reason or 'not_done'})",
                    error_kind="truncated_output",
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError as exc:
                # A provider may omit done_reason.  An unterminated/partial JSON
                # response is still never a normal syntax failure for retry logic.
                return LLMResult(
                    ok=False,
                    data={},
                    raw=response_text,
                    error=f"invalid/truncated JSON: {exc}",
                    error_kind="truncated_output" if response_text.strip() else "invalid_json",
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            if not isinstance(data, dict):
                return LLMResult(
                    ok=False, data={}, raw=response_text,
                    error="Réponse LLM JSON non-objet.", error_kind="invalid_json",
                    finish_reason=finish_reason, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            return LLMResult(
                ok=True, data=data, raw=response_text, finish_reason=finish_reason,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            )
        except Exception as exc:
            failure = classify_failure(exc)
            return LLMResult(
                ok=False,
                data={},
                raw=response_text or raw_outer,
                error=str(exc),
                error_kind="transient_runtime_error" if failure.retryable else failure.code,
                finish_reason=finish_reason,
            )

    def require_json(
        self,
        system: str,
        prompt: str,
        schema_hint: dict[str, Any] | None = None,
        timeout: float = 60,
        *,
        max_output_tokens: int | None = None,
        format_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        res = self.generate_json(
            system, prompt, schema_hint=schema_hint, timeout=timeout,
            max_output_tokens=max_output_tokens, format_schema=format_schema,
        )
        if not res.ok:
            if res.error_kind == "truncated_output":
                raise LLMTruncatedOutputError(f"Ollama/Qwen output truncated or incomplete: {res.error}", raw=res.raw, finish_reason=res.finish_reason)
            if res.error_kind == "invalid_json":
                # A completed but invalid model answer is repairable exactly once
                # by a durable caller; it is not a generic runtime fault.
                raise LLMInvalidJsonError(f"Ollama/Qwen JSON output violates contract: {res.error}", raw=res.raw, finish_reason=res.finish_reason)
            raise EliteLLMError(f"Ollama/Qwen n'a pas produit de JSON valide: {res.error}", raw=res.raw, finish_reason=res.finish_reason)
        return res.data


# --- V18 executable JSON-contract validation ---------------------------------
# ``schema_hint`` used to be documentation only.  It is now an executable
# contract by default: a syntactically valid object is not treated as a valid
# model output if it omits required fields, changes types, contains non-finite
# numeric values, or introduces undeclared fields.  Callers that need a truly
# free-form payload must pass ``schema_hint=None`` explicitly.

def _schema_value_type(value: Any) -> str:
    if value is None:
        return "optional"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _validate_schema_hint(value: Any, hint: Any, *, path: str = "$", forbid_extra: bool = True) -> None:
    """Validate JSON recursively against the project's schema-template format."""
    if hint is None:
        return
    if isinstance(hint, dict):
        if not isinstance(value, dict):
            raise LLMContractError(f"{path}: expected object, got {_schema_value_type(value)}")
        required = {key for key, nested in hint.items() if nested is not None}
        missing = sorted(key for key in required if key not in value)
        if missing:
            raise LLMContractError(f"{path}: missing required fields {missing}")
        if forbid_extra:
            extras = sorted(key for key in value if key not in hint)
            if extras:
                raise LLMContractError(f"{path}: undeclared fields {extras}")
        for key, nested in hint.items():
            if key not in value:
                continue
            current = value[key]
            if current is None:
                if nested is not None:
                    raise LLMContractError(f"{path}.{key}: null not allowed")
                continue
            _validate_schema_hint(current, nested, path=f"{path}.{key}", forbid_extra=forbid_extra)
        return
    if isinstance(hint, list):
        if not isinstance(value, list):
            raise LLMContractError(f"{path}: expected array, got {_schema_value_type(value)}")
        if hint:
            for index, current in enumerate(value):
                _validate_schema_hint(current, hint[0], path=f"{path}[{index}]", forbid_extra=forbid_extra)
        return
    if isinstance(hint, bool):
        if type(value) is not bool:
            raise LLMContractError(f"{path}: expected boolean, got {_schema_value_type(value)}")
        return
    if isinstance(hint, (int, float)) and not isinstance(hint, bool):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise LLMContractError(f"{path}: expected finite number, got {_schema_value_type(value)}")
        return
    if isinstance(hint, str):
        if not isinstance(value, str):
            raise LLMContractError(f"{path}: expected string, got {_schema_value_type(value)}")
        return


_v17_require_json = OllamaJsonClient.require_json


def _v18_require_json(
    self: OllamaJsonClient,
    system: str,
    prompt: str,
    schema_hint: dict[str, Any] | None = None,
    timeout: float = 60,
    *,
    max_output_tokens: int | None = None,
    format_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _v17_require_json(
        self, system, prompt, schema_hint=schema_hint, timeout=timeout,
        max_output_tokens=max_output_tokens, format_schema=format_schema,
    )
    strict = os.environ.get("MLOMEGA_V18_STRICT_LLM_CONTRACTS", "true").strip().lower() not in {"0", "false", "no", "off"}
    if strict and schema_hint is not None:
        _validate_schema_hint(data, schema_hint, forbid_extra=True)
    return data


OllamaJsonClient.require_json = _v18_require_json
