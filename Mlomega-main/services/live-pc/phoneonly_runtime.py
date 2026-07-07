from __future__ import annotations

"""Concrete one-phone V19 runtime used by the SessionHub HTTP process."""

import asyncio
import importlib.util
import sys
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
        close_day: Callable[..., Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.person_id = person_id
        ingress_ctor = ingress_factory or gateway.AiortcIngress
        try:
            self.ingress = ingress_ctor(session_id=session_id, standalone_signaling=False)
        except TypeError:  # simple injected test doubles
            self.ingress = ingress_ctor(session_id=session_id)
        conversation = None
        keyframe_sink = None
        if pipeline_factory is None:
            conversation = live_pipeline.conversation_bridge.ConversationBridge(person_id=person_id)
            live_session_id = conversation.ensure_session()
            keyframe_sink = live_pipeline.visionrt.default_keyframe_sink(
                person_id=person_id, live_session_id=live_session_id, db_path=db_path
            )
        self.pipeline = (pipeline_factory or live_pipeline.LivePipeline)(
            session_id=session_id,
            live_session_id=live_session_id if pipeline_factory is None else None,
            ingress=self.ingress,
            person_id=person_id,
            db_path=db_path,
            conversation_bridge=conversation,
            keyframe_sink=keyframe_sink,
            enable_worldbrain=True,
            enable_conversation=True,
            enable_audio_archive=True,
            enable_identity=True,
            enable_intents=True,
            enable_proactivity=True,
            enable_replay=True,
            enable_stranger_profiles=True,
            enable_fine_intel=True,
        )
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
        self.recent_errors: deque[str] = deque(maxlen=20)
        self._end_lock = asyncio.Lock()
        self._delivery_lock = asyncio.Lock()
        self._close_day = close_day
        self.audio_chunks = 0
        self.final_segments = 0
        self.live_session_id: str | None = None

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
                await self._dispatch_deliveries()
            except ConnectionError:
                pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.recent_errors.append(str(exc)[:500])
            await asyncio.sleep(0.5)

    async def _on_datachannel_open(self) -> None:
        try:
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
        try:
            receipt = delivery_adapter.UIReceipt.model_validate_json(raw)
            self.delivery_adapter.record_receipt(receipt)
        except Exception as exc:
            self.recent_errors.append(("receipt: " + str(exc))[:500])

    def _on_audio_chunk(self, samples: Any, src_rate: int) -> Any:
        self.audio_chunks += 1
        before = int(self.pipeline.metrics().get("conversation_turns", 0))
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

    async def get_or_create(self, session_id: str) -> PhoneOnlyRuntime:
        async with self._lock:
            if self.active is not None and self.active.session_id != session_id:
                if self.active.ended and self.active.close_day_status == "completed":
                    self.active = None
                else:
                    raise RuntimeError(f"phone already active: {self.active.session_id}")
            if self.active is None or self.active.session_id != session_id:
                self.active = self.runtime_factory(session_id=session_id, **self.runtime_kwargs)
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
