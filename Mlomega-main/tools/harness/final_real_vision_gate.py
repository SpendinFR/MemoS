from __future__ import annotations

"""Real open-vocabulary focus gate: captured pixels -> VLM -> memory -> UI contract.

Only the physical phone boundary is simulated: the input is a real captured
keyframe. No detector/VLM output is stubbed. A red VLM result, invalid bbox,
contract failure, missing durable sighting, or invented bearing makes the gate
fail.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mlomega_audio_elite.db import init_db
from mlomega_audio_elite.v19_visual_store import ensure_v19_visual_schema
from packages.contracts.python.models import UIIntent


def _load(name: str, relative: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


live_pipeline = _load(
    "final_real_live_pipeline", "services/live-pc/live_pipeline.py"
)
worldbrain = _load("final_real_worldbrain", "services/live-pc/worldbrain.py")
spatial = _load("final_real_spatial", "services/live-pc/spatial.py")


class CaptureDeviceBoundary:
    """Simulates only the phone DataChannel and records exact product payloads."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send_ui_intent(self, payload: str) -> int:
        self.messages.append(json.loads(payload))
        return 1


def run_gate(
    *,
    image_path: Path,
    db_path: Path,
    query: str,
    model: str,
    ocr_image_path: Path | None = None,
) -> dict[str, Any]:
    import cv2

    frame = cv2.imread(str(image_path))
    if frame is None:
        raise AssertionError(f"unreadable image: {image_path}")
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)
    ensure_v19_visual_schema(db_path)
    os.environ["MLOMEGA_DB"] = str(db_path)

    # The requested object is deliberately outside the fixed COCO vocabulary.
    # The production fallback itself is exercised with the real local model.
    device = CaptureDeviceBoundary()
    pipeline = live_pipeline.LivePipeline(
        session_id="final-real-vlm-transport",
        live_session_id="final-real-vlm",
        person_id="me",
        db_path=db_path,
        ingress=device,
        enable_detector=False,
        enable_worldbrain=True,
        enable_conversation=False,
        enable_intents=False,
        enable_live_discourse=False,
    )
    pipeline.vision.vlm = live_pipeline.visionrt.VlmCrop(
        model=model, timeout_s=60.0
    )
    frame_id = image_path.stem
    pipeline._latest_frame_bgr = frame
    pipeline._latest_envelope = SimpleNamespace(
        frame_id=frame_id, rotation=0, captured_at_utc=None
    )
    started = time.perf_counter()
    intent = pipeline._route_vision_focus({"kind": "find", "query": query})
    elapsed_s = time.perf_counter() - started
    UIIntent.model_validate(intent)
    content = intent.get("content") or {}
    if content.get("state") != "visible":
        raise AssertionError(f"real VLM did not prove visibility: {content}")
    if intent.get("component") != "object_outline":
        raise AssertionError(f"wrong UI component: {intent.get('component')}")
    if (intent.get("anchor") or {}).get("type") != "screen_bbox":
        raise AssertionError(f"missing direct screen bbox: {intent.get('anchor')}")

    # Simulate only camera motion, not a tracker/model answer: move the actual
    # captured pixels and feed the next frame through the production video path.
    # The VLM must not be called again; KLT must refresh the same UIIntent/entity.
    motion = frame.copy()
    matrix = __import__("numpy").float32([[1, 0, 12], [0, 1, 0]])
    motion = cv2.warpAffine(motion, matrix, (frame.shape[1], frame.shape[0]))
    pipeline.on_video_frame(
        motion,
        SimpleNamespace(
            frame_id=f"{frame_id}-motion",
            rotation=0,
            captured_at_utc=None,
            pose_valid=False,
        ),
        now=time.monotonic() + 0.2,
    )
    tracked = next(
        (
            message for message in reversed(device.messages)
            if message.get("type") == "ui_intent"
            and (message.get("content") or {}).get("source") == "visual_tracker"
        ),
        None,
    )
    if tracked is None:
        raise AssertionError("VLM bbox did not seed the UltraLive visual tracker")
    if tracked.get("ui_intent_id") != intent.get("ui_intent_id"):
        raise AssertionError(f"tracker changed UI identity: {tracked}")
    initial_x = float((intent.get("anchor") or {}).get("bbox", {}).get("x") or 0.0)
    tracked_x = float((tracked.get("anchor") or {}).get("bbox", {}).get("x") or 0.0)
    if tracked_x <= initial_x:
        raise AssertionError(
            f"tracker did not follow rightward camera-frame motion: {initial_x} -> {tracked_x}"
        )

    ocr_intent = None
    if ocr_image_path is not None:
        ocr_frame = cv2.imread(str(ocr_image_path))
        if ocr_frame is None:
            raise AssertionError(f"unreadable OCR image: {ocr_image_path}")
        pipeline._latest_frame_bgr = ocr_frame
        pipeline._latest_envelope = SimpleNamespace(
            frame_id=ocr_image_path.stem, rotation=0, captured_at_utc=None
        )
        ocr_intent = pipeline._route_vision_focus(
            {"kind": "ocr", "translate": True, "language": "en"}
        )
        UIIntent.model_validate(ocr_intent)
        ocr_content = ocr_intent.get("content") or {}
        if not str(ocr_content.get("text") or "").strip():
            raise AssertionError(f"real OCR returned no text: {ocr_content}")
        if ocr_content.get("translation_status") != "sent_to_device":
            raise AssertionError(f"translation did not cross DataChannel: {ocr_content}")
        translation = next(
            (
                message
                for message in device.messages
                if message.get("type") == "device_command"
                and message.get("action") == "translate_text"
            ),
            None,
        )
        if not translation or translation.get("text") != ocr_content.get("text"):
            raise AssertionError(f"wrong translation payload: {translation}")

    # Reopen the memory as a new live session: this proves persistence, not an
    # in-memory object surviving the first call.
    reopened = worldbrain.WorldBrain(
        person_id="me",
        live_session_id="final-real-vlm-next",
        db_path=db_path,
        service_db_path=db_path,
        publish_world_state=False,
    )
    durable = reopened.find_entity_record(query)
    if not durable or durable.get("entity_id") != intent.get("entity_id"):
        raise AssertionError(f"durable sighting missing: {durable}")
    last_seen = spatial.answer_find(
        entity_id=str(durable["entity_id"]),
        entity=durable,
        spatial=spatial.PoseKeyframeMap(),
        session_id="final-real-vlm-next",
        visible=False,
        query=query,
    )
    if last_seen.get("bearing") is not None:
        raise AssertionError("2D VLM sighting invented a 3D bearing")

    return {
        "status": "passed",
        "proof_level": "real_pixels_real_vlm_real_db_contract",
        "image": str(image_path),
        "query": query,
        "model": model,
        "elapsed_s": round(elapsed_s, 3),
        "live_intent": intent,
        "tracked_intent": tracked,
        "ocr_translation_intent": ocr_intent,
        "device_payloads": device.messages,
        "durable_record": durable,
        "last_seen_intent": last_seen,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--query", default="lunettes de soleil")
    parser.add_argument("--model", default="qwen3-vl:8b")
    parser.add_argument("--ocr-image", type=Path)
    args = parser.parse_args()
    report = run_gate(
        image_path=args.image,
        db_path=args.db,
        query=args.query,
        model=args.model,
        ocr_image_path=args.ocr_image,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
