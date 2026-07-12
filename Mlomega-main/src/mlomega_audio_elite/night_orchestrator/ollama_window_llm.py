"""E64-F wave 1 - wrap the real OllamaJsonClient as a WindowLLM.

The executor (E64-C) speaks the tiny ``WindowLLM`` protocol (``generate(prompt,
*, output_budget) -> LLMCallResult``). This adapter binds the real
``OllamaJsonClient`` behind it, mapping its ``LLMResult`` states onto the
executor's ``error_kind`` policy vocabulary:

- truncated / ``finish_reason=length`` -> ``"length"``   (executor subdivides)
- malformed / contract JSON            -> ``"invalid_json"``
- timeout / connection / unavailable   -> ``"timeout"`` / ``"unavailable"`` (retry)

The BUSINESS prompt is NOT here: the adapter receives the already-rendered
``system``/``prompt`` from the stage's ``build_window_prompt`` and only forwards
them, honouring the per-window ``output_budget`` as ``max_output_tokens``. Thinking
is already disabled inside ``OllamaJsonClient`` for JSON contracts.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .executor import LLMCallResult

_LENGTH_FINISH = {"length", "max_tokens", "token_limit", "limit"}


def _classify(result: Any) -> str:
    """Map an LLMResult's failure to an executor error_kind."""
    finish = str(getattr(result, "finish_reason", "") or "").lower()
    kind = str(getattr(result, "error_kind", "") or "").lower()
    if finish in _LENGTH_FINISH or kind in {
        "length", "truncated", "truncation", "truncated_output",
    }:
        return "length"
    if kind in {"invalid_json", "json", "contract", "schema"}:
        return "invalid_json"
    if kind in {"timeout"}:
        return "timeout"
    if kind in {
        "unavailable", "connection", "network", "provider",
        "transient_runtime_error",
    }:
        return "unavailable"
    # Unknown non-ok: treat as transient so it is retried, never applied.
    return "unavailable"


class OllamaWindowLLM:
    """Adapt ``OllamaJsonClient`` to the executor's ``WindowLLM`` protocol."""

    def __init__(
        self,
        *,
        system: str,
        client: Any = None,
        schema_hint: Mapping[str, Any] | None = None,
        format_schema: Mapping[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> None:
        if client is None:
            # Imported lazily so the night_orchestrator package stays importable
            # without Ollama configured (tests inject a fake client).
            from ..llm import OllamaJsonClient

            client = OllamaJsonClient()
        self._client = client
        self._system = system
        self._schema_hint = dict(schema_hint) if schema_hint else None
        self._format_schema = dict(format_schema) if format_schema else None
        self._timeout = float(timeout)
        self.model = str(getattr(client, "model", "ollama-json"))

    @staticmethod
    def _prompt_text(prompt: Mapping[str, Any] | str) -> str:
        if isinstance(prompt, str):
            return prompt
        # build_window_prompt may return {"prompt": "...", ...} or a structured
        # payload; prefer an explicit prompt string, else serialise deterministically.
        if isinstance(prompt, Mapping) and isinstance(prompt.get("prompt"), str):
            return prompt["prompt"]
        return json.dumps(prompt, ensure_ascii=False, sort_keys=True, default=str)

    def generate(self, prompt: Mapping[str, Any] | str, *, output_budget: int) -> LLMCallResult:
        user = self._prompt_text(prompt)
        try:
            result = self._client.generate_json(
                self._system,
                user,
                self._schema_hint,
                self._timeout,
                max_output_tokens=int(output_budget),
                format_schema=self._format_schema,
            )
        except Exception as exc:  # network / provider fault -> transient, retryable
            return LLMCallResult(ok=False, error_kind="unavailable", finish_reason=f"exception:{type(exc).__name__}")

        if getattr(result, "ok", False):
            return LLMCallResult(
                ok=True,
                data=getattr(result, "data", None),
                finish_reason=getattr(result, "finish_reason", None),
            )
        return LLMCallResult(
            ok=False,
            error_kind=_classify(result),
            finish_reason=getattr(result, "finish_reason", None),
        )
