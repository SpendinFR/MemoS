from __future__ import annotations

"""Concrete one-phone V19 runtime used by the SessionHub HTTP process."""

import asyncio
import importlib.util
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name: str, filename: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gateway = _load("gateway", "gateway.py")
live_pipeline = _load("v19_live_pipeline", "live_pipeline.py")
delivery_adapter = _load("v19_delivery_adapter", "delivery_adapter.py")
clip_recorder_mod = _load("v19_clip_recorder_runtime", "clip_recorder.py")
gpu_arbiter_mod = _load("v19_gpu_arbiter_runtime", "gpu_arbiter.py")


class DataChannelRenderer(delivery_adapter.RendererHub):
    def __init__(self, ingress: Any) -> None:
        super().__init__()
        self.ingress = ingress

    async def push(self, intent: Any) -> None:
        payload = intent.model_dump_json()
        sent = int(self.ingress.send_ui_intent(payload))
        if sent <= 0:
            # DeliveryAdapter must not mark a queued intervention delivered while
            # the phone is temporarily disconnected. It will be retried on open.
            raise ConnectionError("no open PhoneOnly DataChannel")
        await super().push(intent)


class PhoneOnlyRuntime:
    def __init__(
        self,
        session_id: str,
        *,
        person_id: str = "me",
        db_path: Any = None,
        ingress_factory: Callable[..., Any] | None = None,
        pipeline_factory: Callable[..., Any] | None = None,
        clip_recorder_factory: Callable[..., Any] | None = None,
        arbiter_factory: Callable[..., Any] | None = None,
        close_day: Callable[..., Any] | None = None,
        allow_rerun: bool = False,
    ) -> None:
        self.session_id = session_id
        self.person_id = person_id
        self.recent_errors: deque[str] = deque(maxlen=20)
        # E47-C livrable 6: when this is a SECOND (or later) live session on the
        # same day, its close-day must REOPEN the day's already-completed close-day
        # run so this session's data is consolidated too (multi-session/day). The
        # manager sets this on any session created after a same-day close-day
        # already completed.
        self.allow_rerun = bool(allow_rerun)
        product_pipeline = pipeline_factory is None
        conversation = None
        keyframe_sink = None
        live_session_id: str | None = None
        if product_pipeline:
            conversation = live_pipeline.conversation_bridge.ConversationBridge(person_id=person_id)
            live_session_id = conversation.ensure_session()
            keyframe_sink = live_pipeline.visionrt.default_keyframe_sink(
                person_id=person_id, live_session_id=live_session_id, db_path=db_path
            )

        self.arbiter: Any = None
        if product_pipeline or arbiter_factory is not None:
            try:
                self.arbiter = (arbiter_factory or gpu_arbiter_mod.GpuArbiter)()
            except Exception as exc:
                self._record_pipeline_error(f"gpu_arbiter.init: {exc}")

        self.clip_recorder: Any = None
        self.clip_metrics: dict[str, Any] = {}
        recorder_factory = clip_recorder_factory
        if product_pipeline and recorder_factory is None:
            recorder_factory = clip_recorder_mod.ClipRecorder
        if recorder_factory is not None:
            try:
                config = clip_recorder_mod.load_recorder_config()
                self.clip_recorder = recorder_factory(
                    person_id=person_id,
                    session_id=live_session_id or session_id,
                    config=config,
                    db_path=db_path,
                )
                self.clip_recorder.start()
            except Exception as exc:
                self.clip_recorder = None
                self._record_pipeline_error(f"clip_recorder.init: {exc}")

        ingress_ctor = ingress_factory or gateway.AiortcIngress
        ingress_kwargs: dict[str, Any] = {
            "session_id": session_id,
            "standalone_signaling": False,
        }
        if self.clip_recorder is not None:
            ingress_kwargs["clip_recorder"] = self.clip_recorder
        try:
            self.ingress = ingress_ctor(**ingress_kwargs)
        except TypeError:  # simple injected test doubles / legacy constructors
            try:
                self.ingress = ingress_ctor(session_id=session_id)
            except Exception:
                self._stop_clip_recorder()
                raise
        except Exception:
            self._stop_clip_recorder()
            raise

        pipeline_ctor = pipeline_factory or live_pipeline.LivePipeline
        pipeline_kwargs: dict[str, Any] = {
            "session_id": session_id,
            "live_session_id": live_session_id,
            "ingress": self.ingress,
            "person_id": person_id,
            "db_path": db_path,
            "conversation_bridge": conversation,
            "keyframe_sink": keyframe_sink,
            "enable_worldbrain": True,
            "enable_conversation": True,
            "enable_audio_archive": True,
            "enable_identity": True,
            "enable_intents": True,
            "enable_proactivity": True,
            "enable_replay": True,
            "enable_tts": True,
            "enable_stranger_profiles": True,
            "enable_fine_intel": True,
        }
        if product_pipeline:
            pipeline_kwargs.update({
                "arbiter": self.arbiter,
                "defer_final_processing": True,
                "on_error": self._record_pipeline_error,
            })
        try:
            self.pipeline = pipeline_ctor(**pipeline_kwargs)
        except Exception:
            self._stop_clip_recorder()
            raise
        self.ingress.on_audio_chunk = self._on_audio_chunk
        self.delivery_adapter = delivery_adapter.DeliveryAdapter(
            renderer=DataChannelRenderer(self.ingress)
        )
        self.ingress.on_receipt = self._on_receipt
        if hasattr(self.ingress, "on_datachannel_open"):
            self.ingress.on_datachannel_open = self._on_datachannel_open
        self.video_task: asyncio.Task[Any] | None = None
        self.delivery_task: asyncio.Task[Any] | None = None
        self.ended = False
        self.close_day_started = False
        self.close_day_status = "not_started"
        self.end_status = "active"
        self._end_lock = asyncio.Lock()
        self._delivery_lock = asyncio.Lock()
        self._close_day = close_day
        self.audio_chunks = 0
        self.final_segments = 0
        self.live_session_id: str | None = live_session_id
        self._last_frame_drops = 0

    def _record_pipeline_error(self, message: str) -> None:
        self.recent_errors.append(str(message)[:500])

    async def start(self) -> None:
        if self.video_task is None:
            # Iteration starts the ingress without opening its legacy aiohttp
            # listener; signaling itself remains on SessionHub port 8710.
            self.video_task = asyncio.create_task(self.pipeline.run_video())
            self.delivery_task = asyncio.create_task(self._delivery_loop())
            await asyncio.sleep(0)

    async def _delivery_loop(self) -> None:
        while not self.ended:
            try:
                self._update_degraded_health()
                await self._dispatch_deliveries()
            except ConnectionError:
                pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.recent_errors.append(str(exc)[:500])
            await asyncio.sleep(0.5)

    def _update_degraded_health(self) -> None:
        if not hasattr(self.pipeline, "update_degraded"):
            return
        now = time.monotonic()
        free_vram: int | None = None
        if self.arbiter is not None:
            try:
                snapshot = self.arbiter.snapshot()
                if getattr(snapshot, "available", False):
                    free_vram = int(snapshot.free_mb)
            except Exception as exc:
                self._record_pipeline_error(f"gpu_arbiter.snapshot: {exc}")
        frame_drops = 0
        if hasattr(self.ingress, "stats"):
            try:
                total_drops = int((self.ingress.stats() or {}).get("frames_dropped", 0))
                frame_drops = max(0, total_drops - self._last_frame_drops)
                self._last_frame_drops = total_drops
            except Exception as exc:
                self._record_pipeline_error(f"ingress.stats: {exc}")
        try:
            self.pipeline.update_degraded(live_pipeline.degraded.DegradedSignals(
                now_ts=now,
                heartbeat_ts=now,
                free_vram_mb=free_vram,
                frame_drops=frame_drops,
            ))
        except Exception as exc:
            self._record_pipeline_error(f"degraded.update: {exc}")

    async def _on_datachannel_open(self) -> None:
        try:
            if hasattr(self.pipeline, "set_device_gate_authoritative"):
                self.pipeline.set_device_gate_authoritative(True)
            if hasattr(self.pipeline, "push_wake_word") and not self.pipeline.push_wake_word():
                self.recent_errors.append("wake_word: no open DataChannel")
            self.pipeline.deliver_morning_briefing()
            await self._dispatch_deliveries()
        except ConnectionError:
            pass
        except Exception as exc:
            self.recent_errors.append(str(exc)[:500])

    async def _dispatch_deliveries(self) -> list[Any]:
        async with self._delivery_lock:
            return await self.delivery_adapter.dispatch_once()

    def _on_receipt(self, raw: str) -> None:
        # E47-C §4: an additive DataChannel control message from the device (agent A)
        # arms a wake-word command window. It is NOT a UIReceipt — route it first,
        # then fall through to receipt handling for everything else. Shape:
        #   {"type":"control","action":"wake_word"|"command", "is_command":true}
        try:
            import json as _json

            payload = _json.loads(raw)
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload.get("type") == "device_command_result":
            if payload.get("action") == "set_wake_word" and hasattr(self.pipeline, "confirm_wake_word"):
                try:
                    self.pipeline.confirm_wake_word(payload.get("command_id"), bool(payload.get("ok")))
                except Exception as exc:
                    self.recent_errors.append(("wake_ack: " + str(exc))[:500])
            return
        if isinstance(payload, dict) and payload.get("type") == "device_transcript":
            if hasattr(self.pipeline, "on_device_transcript"):
                try:
                    self.pipeline.on_device_transcript(payload)
                except Exception as exc:
                    self.recent_errors.append(("device_transcript: " + str(exc))[:500])
            return
        if isinstance(payload, dict) and (
            payload.get("type") == "control" or "is_command" in payload
        ):
            if payload.get("is_command") or payload.get("action") in ("wake_word", "command"):
                try:
                    self.pipeline.arm_command_window()
                except Exception as exc:
                    self.recent_errors.append(("control: " + str(exc))[:500])
            return
        try:
            receipt = delivery_adapter.UIReceipt.model_validate_json(raw)
            self.delivery_adapter.record_receipt(receipt)
        except Exception as exc:
            self.recent_errors.append(("receipt: " + str(exc))[:500])

    def _on_audio_chunk(
        self, samples: Any, src_rate: int, source_timing: dict[str, Any] | None = None
    ) -> Any:
        self.audio_chunks += 1
        before = int(self.pipeline.metrics().get("conversation_turns", 0))
        if source_timing is None:
            out = self.pipeline.on_audio_chunk(samples, src_rate)
        else:
            try:
                out = self.pipeline.on_audio_chunk(samples, src_rate, source_timing)
            except TypeError:
                # Compatibility for an injected pre-E60 pipeline; the product
                # LivePipeline accepts and persists source timing.
                out = self.pipeline.on_audio_chunk(samples, src_rate)
        after_metrics = self.pipeline.metrics()
        after = int(after_metrics.get("conversation_turns", 0))
        if "audio_finals_emitted" in after_metrics:
            self.final_segments = int(after_metrics["audio_finals_emitted"])
        else:
            self.final_segments += max(0, after - before)
        return out

    async def end_session_only(self, *, drain_timeout_s: float = 5.0) -> dict[str, Any]:
        async with self._end_lock:
            if self.ended:
                return self.status()
            try:
                self.end_status = "draining"
                if hasattr(self.ingress, "stop_accepting_media"):
                    await self.ingress.stop_accepting_media()
                if hasattr(self.ingress, "drain_audio"):
                    await self.ingress.drain_audio(timeout_s=drain_timeout_s)
                if hasattr(self.pipeline, "flush_audio"):
                    await asyncio.to_thread(self.pipeline.flush_audio)
                await self.close_transport()
                self.end_status = "ending_pipeline"
                await asyncio.to_thread(self.pipeline.end_session, strict=True)
                conversation = getattr(self.pipeline, "conversation", None)
                self.live_session_id = getattr(conversation, "live_session_id", None)
                if conversation is not None:
                    await asyncio.to_thread(
                        conversation.end_session, notes="explicit phone_only end", strict=True,
                    )
                if not self.live_session_id:
                    raise RuntimeError("BrainLive live_session_id was never created")
                if hasattr(self.pipeline, "release_live_resources"):
                    await asyncio.to_thread(self.pipeline.release_live_resources)
                await asyncio.to_thread(self._release_core_live_caches)
                self.ended = True
                self.end_status = "completed"
                if self.delivery_task is not None:
                    self.delivery_task.cancel()
                    await asyncio.gather(self.delivery_task, return_exceptions=True)
            except Exception as exc:
                self.recent_errors.append(str(exc)[:500])
                self.end_status = "error"
                await asyncio.to_thread(self._stop_clip_recorder)
            return self.status()

    async def run_close_day(self) -> dict[str, Any]:
        if not self.ended:
            raise RuntimeError("end_session must complete before CloseDay")
        self.close_day_started = True
        self.close_day_status = "running"
        try:
            result = await asyncio.to_thread(
                self._run_close_day, person_id=self.person_id, live_session_id=self.live_session_id,
            )
            self.close_day_status = str((result or {}).get("status") or "completed")
        except Exception as exc:
            self.recent_errors.append(str(exc)[:500])
            self.close_day_status = "error"
        return self.status()

    async def end_and_close_day(self, *, drain_timeout_s: float = 5.0) -> dict[str, Any]:
        await self.end_session_only(drain_timeout_s=drain_timeout_s)
        if self.end_status == "completed" and self.close_day_status != "completed":
            await self.run_close_day()
        return self.status()

    def _run_close_day(self, **kwargs: Any) -> dict[str, Any]:
        if self._close_day is not None:
            return self._close_day(**kwargs)
        import json
        import subprocess

        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if not python.exists():
            raise RuntimeError(f"core Python environment missing: {python}")
        command = [
            str(python), str(ROOT / "scripts" / "run_phoneonly_close_day.py"),
            "--person-id", str(kwargs["person_id"]),
            "--live-session-id", str(kwargs["live_session_id"]),
        ]
        # E47-C livrable 6: a second same-day session reopens the completed day.
        if self.allow_rerun:
            command.append("--allow-rerun")
        proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if lines:
            try:
                return json.loads(lines[-1])
            except json.JSONDecodeError:
                pass
        raise RuntimeError((proc.stderr or proc.stdout or "CloseDay subprocess failed")[-2000:])

    @staticmethod
    def _release_core_live_caches() -> None:
        from mlomega_audio_elite.runtime_v18_8 import release_live_model_caches

        release_live_model_caches()

    async def close_transport(self) -> None:
        await self.ingress.close()
        if self.video_task is not None:
            # ASGI test transports and server shutdown may already have cancelled
            # the consumer task; transport closure remains idempotent.
            await asyncio.gather(self.video_task, return_exceptions=True)
        await asyncio.to_thread(self._stop_clip_recorder)

    def _stop_clip_recorder(self) -> None:
        recorder = self.clip_recorder
        if recorder is None:
            return
        try:
            self.clip_metrics = dict(recorder.stop() or {})
        except Exception as exc:
            self._record_pipeline_error(f"clip_recorder.stop: {exc}")
        finally:
            self.clip_recorder = None

    def status(self) -> dict[str, Any]:
        metrics = dict(self.pipeline.metrics())
        if hasattr(self.ingress, "stats"):
            metrics.update(self.ingress.stats())
        conversation = getattr(self.pipeline, "conversation", None)
        archive = getattr(self.pipeline, "audio_archive", None)
        metrics.update(
            {
                "session_id": self.session_id,
                "person_id": self.person_id,
                "live_session_id": self.live_session_id or getattr(conversation, "live_session_id", None),
                "audio_chunks_received": self.audio_chunks,
                "segments_finals": int(metrics.get("audio_finals_emitted", self.final_segments)),
                "transcripts": metrics.get("conversation_turns", 0),
                "turns_brainlive": metrics.get("conversation_turns", 0),
                "keyframes_archived": metrics.get("keyframes_recorded", 0),
                "speech_segments_archived": getattr(archive, "metrics", {}).get("segments_archived", 0) if archive else 0,
                "end_session": self.end_status,
                "close_day": self.close_day_status,
                "recent_errors": list(self.recent_errors),
                "ui_intents_delivered": len(self.delivery_adapter.renderer.sent),
                "clip_recording": dict(self.clip_metrics) if self.clip_metrics else (
                    dict(getattr(self.clip_recorder, "metrics", {}).to_dict())
                    if self.clip_recorder is not None and hasattr(getattr(self.clip_recorder, "metrics", None), "to_dict")
                    else {}
                ),
            }
        )
        return metrics


class SinglePhoneRuntimeManager:
    """Explicit mono-device policy: never overwrite a different live session."""

    def __init__(self, *, runtime_factory: Callable[..., PhoneOnlyRuntime] = PhoneOnlyRuntime, **kwargs: Any) -> None:
        self.runtime_factory = runtime_factory
        self.runtime_kwargs = kwargs
        self.active: PhoneOnlyRuntime | None = None
        self._lock = asyncio.Lock()
        self._close_tasks: dict[str, asyncio.Task[Any]] = {}
        # E47-C livrable 6: how many close-days have completed in this process
        # lifetime. The (n+1)-th session's close-day must reopen the day (multi
        # session/day). Persisted-across-restart safety is provided anyway by the
        # script's own reopen check (a no-op if the day is not completed).
        self._completed_close_days = 0

    async def get_or_create(self, session_id: str) -> PhoneOnlyRuntime:
        async with self._lock:
            if self.active is not None and self.active.session_id != session_id:
                if self.active.ended and self.active.close_day_status == "completed":
                    self._completed_close_days += 1
                    self.active = None
                else:
                    raise RuntimeError(f"phone already active: {self.active.session_id}")
            if self.active is None or self.active.session_id != session_id:
                kwargs = dict(self.runtime_kwargs)
                # A session created after a same-day close-day already completed
                # must reopen it so its own data is consolidated.
                if self._completed_close_days > 0:
                    kwargs.setdefault("allow_rerun", True)
                self.active = self.runtime_factory(session_id=session_id, **kwargs)
                await self.active.start()
            return self.active

    def get(self, session_id: str) -> PhoneOnlyRuntime | None:
        return self.active if self.active is not None and self.active.session_id == session_id else None

    def metrics(self) -> dict[str, Any]:
        return {"mode": "single_phone", "active": self.active.status() if self.active else None}

    def start_close_day(self, session_id: str) -> asyncio.Task[Any]:
        runtime = self.get(session_id)
        if runtime is None:
            raise RuntimeError("session runtime not found")
        current = self._close_tasks.get(session_id)
        if current is not None and not current.done():
            return current
        if runtime.close_day_status == "completed":
            async def _completed() -> dict[str, Any]:
                return runtime.status()
            current = asyncio.create_task(_completed())
        else:
            current = asyncio.create_task(runtime.run_close_day())
        self._close_tasks[session_id] = current
        return current
