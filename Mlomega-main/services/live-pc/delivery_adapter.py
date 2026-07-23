from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from packages.contracts.python.models import UIIntent, UIReceipt
from mlomega_audio_elite.db import connect
from mlomega_audio_elite.utils import json_loads
from mlomega_audio_elite.v18_8_live_policy import record_delivery_feedback
from mlomega_audio_elite.v18_delivery import ensure_delivery_schema

# Module-level so FastAPI can resolve the `websocket: WebSocket` annotation:
# with `from __future__ import annotations`, get_type_hints() looks the name up
# in the MODULE globals — a WebSocket imported only inside create_app() is
# invisible there and FastAPI silently degrades it to a required query param,
# closing every connection with code 1008 (bug found by the E29 phone_only e2e).
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover - only without API deps installed
    FastAPI = WebSocket = WebSocketDisconnect = None  # type: ignore[assignment]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def delivery_row_to_ui_intent(row: sqlite3.Row | dict[str, Any]) -> UIIntent:
    data = dict(row)
    evidence = json_loads(data.get("evidence_json") or "{}") or {}
    candidate = evidence.get("candidate") or {}
    if not isinstance(candidate, dict):
        candidate = {}
    refs = evidence.get("evidence_refs") or evidence.get("refs") or []
    if not refs:
        refs = candidate.get("evidence_refs") or []
    if isinstance(refs, str):
        refs = [refs]
    kind = str(candidate.get("kind") or "")
    message = str(data.get("message") or candidate.get("message") or "").strip()
    titles = {
        "attribute_changed": "Changement observé",
        "clarification": "Précision nécessaire",
        "conflict_warning": "Attention",
        "found_object": "Objet retrouvé",
        "prediction": "Suggestion",
    }
    component = "context_card"
    content: dict[str, Any] = {
        # ContextCard renders ``text|body``. Keep ``message`` for historical
        # consumers, but make the canonical UI contract complete at the PC edge.
        "text": message,
        "body": message,
        "message": message,
        "title": str(candidate.get("title") or titles.get(kind) or "Contexte"),
        "kind": kind or "context",
        "source": str(candidate.get("source") or "brainlive"),
        "action_type": data.get("action_type") or "notify",
    }
    producer = "brainlive"
    ttl_ms = 15000
    ui_intent_id = str(candidate.get("ui_intent_id") or f"ui-{data.get('delivery_id') or uuid.uuid4()}")
    if kind == "task_panel":
        parsed = json_loads(data.get("message") or "{}", {}) or {}
        if isinstance(parsed, dict):
            content = parsed
            component = "task_panel"
            producer = "ultralive"
            ttl_ms = max(1, int(candidate.get("ttl_ms") or 3_600_000))
    return UIIntent(
        ui_intent_id=ui_intent_id, producer=producer, source_frame_id=None,
        component=component, anchor={"type": "panel", "position": "side"},
        content=content,
        truth_level="inferred", confidence=1.0, priority=max(0.0, min(1.0, float(data.get("priority") or 0.0))),
        ttl_ms=ttl_ms, evidence_refs=list(refs), delivery_id=data.get("delivery_id"),
    )


@dataclass
class RendererHub:
    sent: list[UIIntent] = field(default_factory=list)

    async def push(self, intent: UIIntent) -> None:
        self.sent.append(intent)


class WebSocketRendererHub(RendererHub):
    """Broadcast UIIntent JSON to connected companion-web/XR renderers."""

    def __init__(self) -> None:
        super().__init__()
        self._clients: set[Any] = set()

    async def connect(self, websocket: Any) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: Any) -> None:
        self._clients.discard(websocket)

    async def push(self, intent: UIIntent) -> None:
        await super().push(intent)
        if not self._clients:
            return
        payload = intent.model_dump_json()
        stale: list[Any] = []
        for websocket in list(self._clients):
            try:
                await websocket.send_text(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


class DeliveryAdapter:
    def __init__(self, renderer: RendererHub | None = None) -> None:
        # The dispatch loop starts before the first H1 candidate. On a brand-new
        # database the producer has therefore not had a chance to lazily create
        # its queue yet; initialise it before the very first poll.
        ensure_delivery_schema()
        self.renderer = renderer or RendererHub()

    def poll_queued(self, *, limit: int = 20) -> list[sqlite3.Row]:
        with connect() as con:
            return list(con.execute(
                """SELECT * FROM brainlive_intervention_delivery_queue
                   WHERE delivery_status='queued' ORDER BY priority DESC, created_at ASC LIMIT ?""", (limit,)
            ).fetchall())

    async def dispatch_once(self) -> list[UIIntent]:
        intents: list[UIIntent] = []
        for row in self.poll_queued():
            intent = delivery_row_to_ui_intent(row)
            await self.renderer.push(intent)
            record_delivery_feedback(delivery_id=str(row["delivery_id"]), feedback_type="delivered", feedback_source="xr_adapter", evidence={"ui_intent_id": intent.ui_intent_id})
            intents.append(intent)
        return intents

    def record_receipt(self, receipt: UIReceipt) -> dict[str, Any] | None:
        if not receipt.delivery_id:
            return None
        return record_delivery_feedback(
            delivery_id=receipt.delivery_id, feedback_type=receipt.event, feedback_source="xr_adapter",
            observed_at=receipt.observed_at, evidence=receipt.model_dump(),
        )


def create_app(adapter: DeliveryAdapter | None = None):
    """Create the V19 delivery WebSocket app used by companion-web.

    Endpoint contract:
    * GET /health returns basic readiness and connected renderer count.
    * WS /ws pushes queued BrainLive UIIntent messages as JSON.
    * Messages received on /ws are UIReceipt JSON and are persisted via V18.8 feedback.
    """
    if FastAPI is None:  # pragma: no cover - exercised only without API deps installed
        raise RuntimeError("fastapi is required for delivery_adapter.create_app()")

    renderer = adapter.renderer if adapter else WebSocketRendererHub()
    if not isinstance(renderer, WebSocketRendererHub):
        renderer = WebSocketRendererHub()
    app_adapter = adapter or DeliveryAdapter(renderer=renderer)
    app_adapter.renderer = renderer
    app = FastAPI(title="MLOmega V19 delivery adapter")
    dispatch_task: asyncio.Task[Any] | None = None

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "connected_renderers": len(renderer._clients), "sent_intents": len(renderer.sent)}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await renderer.connect(websocket)
        await app_adapter.dispatch_once()
        try:
            while True:
                data = await websocket.receive_text()
                receipt = UIReceipt.model_validate_json(data)
                app_adapter.record_receipt(receipt)
        except WebSocketDisconnect:
            renderer.disconnect(websocket)

    async def _continuous_dispatch() -> None:
        while True:
            try:
                await app_adapter.dispatch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient DB/renderer error must not kill the product loop.
                pass
            await asyncio.sleep(0.5)

    @app.on_event("startup")
    async def _startup() -> None:
        nonlocal dispatch_task
        dispatch_task = asyncio.create_task(_continuous_dispatch())

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        nonlocal dispatch_task
        if dispatch_task is not None:
            dispatch_task.cancel()
            await asyncio.gather(dispatch_task, return_exceptions=True)
            dispatch_task = None

    # Serve the real browser viewer from the same process/port as its WebSocket.
    web_root = Path(__file__).resolve().parents[2] / "apps" / "companion-web"
    if web_root.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(web_root), html=True), name="companion-web")

    app.state.delivery_adapter = app_adapter
    app.state.renderer = renderer
    return app


async def main_loop(interval_s: float = 0.5, adapter: DeliveryAdapter | None = None) -> None:
    adapter = adapter or DeliveryAdapter()
    while True:
        await adapter.dispatch_once()
        await asyncio.sleep(interval_s)


if __name__ == "__main__":
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="MLOmega companion-web delivery server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8706)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
