from __future__ import annotations

"""Opt-in cloud provider adapters used by the PRO CloseDay profile.

Nothing imports this module on the default local path.  The adapters deliberately
use the standard library so enabling PRO does not mutate either committed venv.
Every request is reserved and reconciled through ``cloud_budget_v19``.
"""

import base64
import hashlib
import json
import mimetypes
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .cloud_budget_v19 import (
    CloudBudgetExceeded,
    cloud_budget_policy,
    mark_cloud_in_flight,
    reconcile_cloud_cost,
    release_cloud_reservation,
    reserve_cloud_cost,
    usd_to_eur,
)


DEEPSEEK_TARIFFS_USD_PER_M = {
    "deepseek-v4-pro": {"cache_hit": 0.003625, "cache_miss": 0.435, "output": 0.87},
    "deepseek-v4-flash": {"cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28},
}
GROQ_WHISPER_USD_PER_HOUR = {"whisper-large-v3": 0.111, "whisper-large-v3-turbo": 0.04}
GEMINI_TARIFFS_USD_PER_M = {
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}
try:
    _MAX_CLOUD_IN_FLIGHT = max(1, min(40, int(os.environ.get("MLOMEGA_CLOUD_MAX_IN_FLIGHT", "12"))))
except ValueError:
    _MAX_CLOUD_IN_FLIGHT = 12
_CLOUD_REQUEST_SLOTS = threading.BoundedSemaphore(_MAX_CLOUD_IN_FLIGHT)
_BUNDLE_WARM_LOCK = threading.Lock()
_BUNDLE_WARM_RESPONSES: dict[tuple[str, str], str] = {}


@dataclass
class BundlePrefixContext:
    bundle_id: str
    canonical_json: str
    digest: str
    warm_responses: dict[str, str] = field(default_factory=dict)


_BUNDLE_PREFIX: ContextVar[BundlePrefixContext | None] = ContextVar(
    "mlomega_cloud_bundle_prefix", default=None
)


@contextmanager
def cloud_bundle_prefix(bundle_id: str, bundle_payload: dict[str, Any]) -> Iterator[BundlePrefixContext]:
    canonical = json.dumps(bundle_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    context = BundlePrefixContext(
        bundle_id=str(bundle_id),
        canonical_json=canonical,
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    token = _BUNDLE_PREFIX.set(context)
    try:
        yield context
    finally:
        _BUNDLE_PREFIX.reset(token)


def current_bundle_prefix() -> BundlePrefixContext | None:
    return _BUNDLE_PREFIX.get()


class CloudProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _require_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CloudProviderError(f"{name} absent; ajoute-la dans le fichier .env avant --pro")
    return value


def _safe_http_error(exc: urllib.error.HTTPError) -> CloudProviderError:
    # Provider bodies can echo request metadata or prompt fragments. Do not put
    # them in an exception that may be persisted by the CloseDay recovery log.
    return CloudProviderError(
        f"cloud HTTP {exc.code}", status=int(exc.code),
        retryable=int(exc.code) in {408, 409, 429, 500, 502, 503, 504},
    )


def _request(
    request: urllib.request.Request,
    *,
    timeout: float,
    retries: int = 4,
) -> tuple[bytes, int, int]:
    last: Exception | None = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            with _CLOUD_REQUEST_SLOTS:
                with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
                    return response.read(), int(getattr(response, "status", 200)), attempt
        except urllib.error.HTTPError as exc:
            failure = _safe_http_error(exc)
            last = failure
            if not failure.retryable or attempt >= retries:
                raise failure from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = CloudProviderError(f"cloud transport unavailable: {type(exc).__name__}", retryable=True)
            if attempt >= retries:
                raise last from exc
        retry_after = 0.0
        if isinstance(last, CloudProviderError) and getattr(last, "status", None) == 429:
            try:
                retry_after = float(os.environ.get("MLOMEGA_CLOUD_429_MIN_WAIT_S", "1"))
            except ValueError:
                retry_after = 1.0
        delay = min(60.0, max(retry_after, (2.0 ** attempt) + random.random() * 0.25))
        time.sleep(delay)
    raise last or CloudProviderError("cloud request failed")


def _json_request(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
    retries: int = 4,
) -> tuple[dict[str, Any], int, int]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "MLOmega-V19-PRO/1.0",
            **headers,
        },
        method="POST",
    )
    raw, status, retry_count = _request(request, timeout=timeout, retries=retries)
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CloudProviderError("cloud response is not JSON") from exc
    if not isinstance(value, dict):
        raise CloudProviderError("cloud response JSON is not an object")
    return value, status, retry_count


def _estimated_tokens(*texts: str) -> int:
    # Reservation only: intentionally conservative for French/JSON UTF-8 input.
    return max(1, sum(len(text.encode("utf-8")) for text in texts) // 3)


def _deepseek_cost_eur(model: str, usage: dict[str, Any]) -> tuple[float, int, int, int, int]:
    tariff = DEEPSEEK_TARIFFS_USD_PER_M[model]
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    hit = int(usage.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or max(0, prompt - hit))
    usd = (hit * tariff["cache_hit"] + miss * tariff["cache_miss"] + completion * tariff["output"]) / 1_000_000
    return usd_to_eur(usd), prompt, hit, miss, completion


_WARM_PROMPT = "Acknowledge this evidence bundle as compact JSON: {\"bundle_loaded\":true}."


def _deepseek_messages(
    system: str, prompt: str, *, model: str, warm_only: bool = False
) -> list[dict[str, str]]:
    context = current_bundle_prefix()
    if context is None:
        return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    common = [
        {"role": "system", "content": "MLOmega CloseDay shared evidence prefix. Preserve provenance; never invent absent evidence."},
        {"role": "user", "content": context.canonical_json},
    ]
    if warm_only:
        return common + [{"role": "user", "content": _WARM_PROMPT}]
    warm = context.warm_responses.get(model, "{\"bundle_loaded\":true}")
    # The expensive canonical evidence is an exact byte-for-byte prefix. The
    # historical engine instructions retain both their original role and bytes.
    return common + [
        {"role": "user", "content": _WARM_PROMPT},
        {"role": "assistant", "content": warm},
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def deepseek_chat_json(
    *,
    system: str,
    prompt: str,
    json_schema: dict[str, Any] | None,
    max_output_tokens: int,
    timeout: float,
    model: str | None = None,
) -> dict[str, Any]:
    selected = (model or os.environ.get("MLOMEGA_DEEPSEEK_MODEL") or "deepseek-v4-pro").strip()
    if selected not in DEEPSEEK_TARIFFS_USD_PER_M:
        raise CloudProviderError(f"unsupported DeepSeek model: {selected}")
    context = current_bundle_prefix()
    warm_key = (context.digest, selected) if context is not None else None
    if context is not None and selected not in context.warm_responses:
        cached_warm = _BUNDLE_WARM_RESPONSES.get(warm_key)
        if cached_warm:
            context.warm_responses[selected] = cached_warm
    if context is not None and selected not in context.warm_responses:
        # Episode packs fan out after one shared prefix.  Double-check under a
        # process lock so concurrent first callers never buy N identical warmups.
        with _BUNDLE_WARM_LOCK:
            cached_warm = _BUNDLE_WARM_RESPONSES.get(warm_key)
            if cached_warm:
                context.warm_responses[selected] = cached_warm
            if selected not in context.warm_responses:
                warm_outer = _deepseek_request(
                    messages=_deepseek_messages("", "", model=selected, warm_only=True), model=selected,
                    max_output_tokens=48, timeout=timeout, stage_name="bundle_prefix_warm",
                    json_schema={"type": "object"},
                )
                choices = warm_outer.get("choices") or []
                message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
                warm_text = str(message.get("content") or "").strip()
                try:
                    parsed = json.loads(warm_text)
                except Exception:
                    parsed = {}
                if not isinstance(parsed, dict) or parsed.get("bundle_loaded") is not True:
                    raise CloudProviderError("DeepSeek bundle prefix warm-up contract failed")
                context.warm_responses[selected] = warm_text
                _BUNDLE_WARM_RESPONSES[warm_key] = warm_text
    return _deepseek_request(
        messages=_deepseek_messages(system, prompt, model=selected), model=selected,
        max_output_tokens=max_output_tokens, timeout=timeout,
        stage_name="closeday_text", json_schema=json_schema,
    )


def warm_bundle_prefix(
    bundle_id: str, bundle_payload: dict[str, Any], *, timeout: float = 60.0,
    model: str | None = None,
) -> str:
    """Pay the ONE cache-priming warm-up for an episode prefix, deduplicated.

    CHANTIER 2 step 2: emit one warm-up per unique episode so the concurrent
    engine fan-out that follows hits the cache instead of re-sending the full
    prefix N times.  Reuses the exact per-digest dedup in ``deepseek_chat_json``
    (process lock + ``_BUNDLE_WARM_RESPONSES``), so a repeated episode or a resume
    never buys a second warm-up.  The caller applies ONE cache-settle wait after
    warming every episode, never one wait per episode.
    """
    selected = (model or os.environ.get("MLOMEGA_DEEPSEEK_MODEL") or "deepseek-v4-pro").strip()
    with cloud_bundle_prefix(bundle_id, bundle_payload) as context:
        warm_key = (context.digest, selected)
        cached = _BUNDLE_WARM_RESPONSES.get(warm_key)
        if cached:
            return cached
        with _BUNDLE_WARM_LOCK:
            cached = _BUNDLE_WARM_RESPONSES.get(warm_key)
            if cached:
                return cached
            warm_outer = _deepseek_request(
                messages=_deepseek_messages("", "", model=selected, warm_only=True),
                model=selected, max_output_tokens=48, timeout=timeout,
                stage_name="bundle_prefix_warm", json_schema={"type": "object"},
            )
            choices = warm_outer.get("choices") or []
            message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
            warm_text = str(message.get("content") or "").strip()
            try:
                parsed = json.loads(warm_text)
            except Exception:
                parsed = {}
            if not isinstance(parsed, dict) or parsed.get("bundle_loaded") is not True:
                raise CloudProviderError("DeepSeek bundle prefix warm-up contract failed")
            _BUNDLE_WARM_RESPONSES[warm_key] = warm_text
            return warm_text


def _deepseek_request(
    *, messages: list[dict[str, str]], model: str, max_output_tokens: int,
    timeout: float, stage_name: str, json_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    api_key = _require_key("DEEPSEEK_API_KEY")
    tariff = DEEPSEEK_TARIFFS_USD_PER_M[model]
    estimated_input = _estimated_tokens(*(str(item.get("content") or "") for item in messages))
    worst_usd = (estimated_input * tariff["cache_miss"] + max_output_tokens * tariff["output"]) / 1_000_000
    try:
        reservation = reserve_cloud_cost(
            provider="deepseek", model=model, stage_name=stage_name,
            worst_case_eur=usd_to_eur(worst_usd), tariff=tariff,
        )
    except CloudBudgetExceeded:
        if model == "deepseek-v4-pro" and cloud_budget_policy() == "flash":
            return _deepseek_request(
                messages=messages, model="deepseek-v4-flash",
                max_output_tokens=max_output_tokens, timeout=timeout,
                stage_name=f"{stage_name}_budget_flash", json_schema=json_schema,
            )
        raise
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": int(max_output_tokens),
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    # DeepSeek currently supports JSON object mode, not arbitrary response_schema.
    # The existing executable project contract still validates the returned JSON.
    if json_schema:
        payload["messages"] = messages + [{"role": "system", "content": "Output must satisfy this JSON Schema exactly: " + json.dumps(json_schema, ensure_ascii=False, separators=(",", ":"))}]
    sent = False
    started = time.monotonic()
    try:
        # Persist the durable reserved->in_flight frontier before the HTTP send so
        # a crash mid-call is recovered as ``uncertain`` (OBS-70), never released.
        mark_cloud_in_flight(reservation)
        sent = True
        outer, status, retries = _json_request(
            os.environ.get("MLOMEGA_DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions",
            payload, headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout, retries=int(os.environ.get("MLOMEGA_CLOUD_HTTP_RETRIES", "4")),
        )
        usage = outer.get("usage") if isinstance(outer.get("usage"), dict) else {}
        actual_eur, prompt_tokens, hit, miss, completion = _deepseek_cost_eur(model, usage)
        reconcile_cloud_cost(
            reservation, actual_eur=actual_eur, input_tokens=prompt_tokens,
            cache_hit_tokens=hit, cache_miss_tokens=miss, output_tokens=completion,
            latency_ms=int((time.monotonic() - started) * 1000), http_status=status,
            retry_count=retries, usage=usage,
        )
        return outer
    except Exception as exc:
        release_cloud_reservation(
            reservation, error_code=type(exc).__name__, request_was_sent=sent,
        )
        raise


def _wave_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            return float(handle.getnframes()) / float(rate) if rate else 0.0
    except Exception as exc:
        raise CloudProviderError(f"Groq PRO expects a readable WAV tape: {path.name}") from exc


@contextmanager
def _groq_upload_file(path: Path) -> Iterator[Path]:
    """Keep direct uploads below the 25 MiB free-tier boundary, losslessly."""

    if path.stat().st_size <= 24 * 1024 * 1024:
        yield path
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CloudProviderError("ffmpeg is required to compress a Groq tape larger than 24 MiB")
    handle = tempfile.NamedTemporaryFile(prefix="mlomega-groq-", suffix=".flac", delete=False)
    compressed = Path(handle.name)
    handle.close()
    try:
        process = subprocess.run(
            [ffmpeg, "-y", "-i", str(path), "-ar", "16000", "-ac", "1", "-c:a", "flac", str(compressed)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            timeout=float(os.environ.get("MLOMEGA_GROQ_FFMPEG_TIMEOUT_S", "300")),
            check=False,
        )
        if process.returncode != 0 or not compressed.is_file() or compressed.stat().st_size <= 0:
            raise CloudProviderError("ffmpeg could not create the lossless Groq FLAC upload")
        if compressed.stat().st_size > 95 * 1024 * 1024:
            raise CloudProviderError("Groq audio upload remains above the 100 MiB dev limit")
        yield compressed
    finally:
        compressed.unlink(missing_ok=True)


def _normalize_transcription_language(provider_language: Any, requested_language: str) -> tuple[str, str]:
    """Return the ISO-like code WhisperX expects and the untouched provider label."""
    raw = str(provider_language or "").strip()
    requested = str(requested_language or "").strip().lower().replace("_", "-").split("-", 1)[0]
    candidate = raw.lower().replace("_", "-").split("-", 1)[0]
    if candidate.isalpha() and 2 <= len(candidate) <= 3:
        return candidate, raw
    if requested.isalpha() and 2 <= len(requested) <= 3:
        return requested, raw
    # PRO currently supplies an explicit language. Keep a conservative generic
    # fallback for direct adapter callers instead of passing a full language name
    # to whisperx.load_align_model().
    known = {
        "english": "en", "french": "fr", "german": "de", "spanish": "es",
        "italian": "it", "portuguese": "pt", "dutch": "nl", "japanese": "ja",
        "korean": "ko", "chinese": "zh", "arabic": "ar", "russian": "ru",
    }
    return known.get(candidate, candidate or "en"), raw


def groq_transcribe(audio_path: Path, *, language: str, timeout: float = 900.0) -> dict[str, Any]:
    path = Path(audio_path).expanduser().resolve()
    api_key = _require_key("GROQ_API_KEY")
    duration = _wave_duration_seconds(path)
    model = os.environ.get("MLOMEGA_GROQ_WHISPER_MODEL", "whisper-large-v3").strip()
    if model not in GROQ_WHISPER_USD_PER_HOUR:
        raise CloudProviderError(f"unsupported Groq Whisper model: {model}")
    billed_seconds = max(10.0, duration)
    actual_eur = usd_to_eur((billed_seconds / 3600.0) * GROQ_WHISPER_USD_PER_HOUR[model])
    reservation = reserve_cloud_cost(
        provider="groq", model=model, stage_name="deep_audio_transcription",
        worst_case_eur=actual_eur,
        tariff={"usd_per_audio_hour": GROQ_WHISPER_USD_PER_HOUR[model], "minimum_billed_seconds": 10},
    )
    sent = False
    started = time.monotonic()
    try:
        with _groq_upload_file(path) as upload_path:
            boundary = f"----mlomega-{uuid4().hex}"
            parts: list[bytes] = []
            def field(name: str, value: str) -> None:
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
            field("model", model)
            field("response_format", "verbose_json")
            field("temperature", "0")
            if language:
                field("language", language)
            mime = "audio/flac" if upload_path.suffix.lower() == ".flac" else "audio/wav"
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{upload_path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
                + upload_path.read_bytes() + b"\r\n"
            )
            parts.append(f"--{boundary}--\r\n".encode())
            request = urllib.request.Request(
                os.environ.get("MLOMEGA_GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/") + "/audio/transcriptions",
                data=b"".join(parts), method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "MLOmega-V19-PRO/1.0",
                },
            )
            mark_cloud_in_flight(reservation)
            sent = True
            raw, status, retries = _request(request, timeout=timeout, retries=int(os.environ.get("MLOMEGA_CLOUD_HTTP_RETRIES", "4")))
        outer = json.loads(raw.decode("utf-8"))
        if not isinstance(outer, dict) or not isinstance(outer.get("segments"), list):
            raise CloudProviderError("Groq verbose_json response has no segments")
        normalized_language, provider_language = _normalize_transcription_language(
            outer.get("language"), language
        )
        outer["language"] = normalized_language
        outer["provider_language"] = provider_language
        reconcile_cloud_cost(
            reservation, actual_eur=actual_eur, audio_seconds=duration,
            latency_ms=int((time.monotonic() - started) * 1000), http_status=status,
            retry_count=retries, usage={"duration_seconds": duration, "billed_seconds": billed_seconds},
        )
        return outer
    except Exception as exc:
        release_cloud_reservation(reservation, error_code=type(exc).__name__, request_was_sent=sent)
        raise


def gemini_vision_json(
    image_path: Path, *, system: str, prompt: str, schema: dict[str, Any],
    max_output_tokens: int, timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(image_path).expanduser().resolve()
    api_key = _require_key("GEMINI_API_KEY")
    model = os.environ.get("MLOMEGA_GEMINI_VLM_MODEL", "gemini-3.1-flash-lite").strip()
    tariff = GEMINI_TARIFFS_USD_PER_M.get(model)
    if tariff is None:
        raise CloudProviderError(f"unsupported Gemini VLM model: {model}")
    estimated_input = _estimated_tokens(system, prompt) + 1500
    worst_eur = usd_to_eur((estimated_input * tariff["input"] + max_output_tokens * tariff["output"]) / 1_000_000)
    reservation = reserve_cloud_cost(
        provider="gemini", model=model, stage_name="deep_vision",
        worst_case_eur=worst_eur, tariff=tariff,
    )
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(path.read_bytes()).decode("ascii")}},
            {"text": prompt},
        ]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": int(max_output_tokens),
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    sent = False
    started = time.monotonic()
    try:
        mark_cloud_in_flight(reservation)
        sent = True
        outer, status, retries = _json_request(
            os.environ.get("MLOMEGA_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
            + f"/models/{model}:generateContent",
            payload, headers={"x-goog-api-key": api_key},
            timeout=timeout, retries=int(os.environ.get("MLOMEGA_CLOUD_HTTP_RETRIES", "4")),
        )
        candidates = outer.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates and isinstance(candidates[0], dict) else []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise CloudProviderError("Gemini structured response is not an object")
        usage = outer.get("usageMetadata") if isinstance(outer.get("usageMetadata"), dict) else {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        actual_eur = usd_to_eur((input_tokens * tariff["input"] + output_tokens * tariff["output"]) / 1_000_000)
        latency_ms = int((time.monotonic() - started) * 1000)
        reconcile_cloud_cost(
            reservation, actual_eur=actual_eur, input_tokens=input_tokens,
            output_tokens=output_tokens, image_count=1, latency_ms=latency_ms,
            http_status=status, retry_count=retries, usage=usage,
        )
        return data, {"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens, "latency_ms": latency_ms}
    except Exception as exc:
        release_cloud_reservation(reservation, error_code=type(exc).__name__, request_was_sent=sent)
        raise


__all__ = [
    "BundlePrefixContext", "CloudProviderError", "cloud_bundle_prefix",
    "current_bundle_prefix", "deepseek_chat_json", "gemini_vision_json",
    "groq_transcribe", "warm_bundle_prefix",
]
