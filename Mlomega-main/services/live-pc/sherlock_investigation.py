from __future__ import annotations

"""Explicit, bounded visual investigation sessions for the live Eye stream.

Sherlock is deliberately separate from continuous Memory and from the public
profile lookup bearing the same nickname.  Nothing is created until the wearer
starts a session.  Every pixel-changing operation keeps the immutable original,
its hash and its derivation parameters; enhanced pixels are never promoted to an
observation.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, Mapping

import cv2
import numpy as np


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sherlock_sessions_v19(
  sherlock_session_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  live_session_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  capture_count INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sherlock_session_owner_v19
  ON sherlock_sessions_v19(person_id,started_at);

CREATE TABLE IF NOT EXISTS sherlock_evidence_v19(
  evidence_id TEXT PRIMARY KEY,
  sherlock_session_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  live_session_id TEXT NOT NULL,
  evidence_kind TEXT NOT NULL,
  parent_evidence_id TEXT,
  observed_at TEXT NOT NULL,
  source_frame_id TEXT,
  media_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  bbox_json TEXT,
  truth_level TEXT NOT NULL,
  derivation_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sherlock_evidence_session_v19
  ON sherlock_evidence_v19(sherlock_session_id,observed_at);

CREATE TABLE IF NOT EXISTS sherlock_findings_v19(
  finding_id TEXT PRIMARY KEY,
  sherlock_session_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  finding_kind TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  statement TEXT NOT NULL,
  truth_level TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sherlock_findings_session_v19
  ON sherlock_findings_v19(sherlock_session_id,observed_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clean_bbox(raw: Any, width: int, height: int) -> list[int] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    # Focus bboxes can be either normalised screen coordinates or pixels.
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
        x1, x2 = x1 * width, x2 * width
        y1, y2 = y1 * height, y2 * height
    left = max(0, min(width - 1, int(round(min(x1, x2)))))
    right = max(1, min(width, int(round(max(x1, x2)))))
    top = max(0, min(height - 1, int(round(min(y1, y2)))))
    bottom = max(1, min(height, int(round(max(y1, y2)))))
    return [left, top, right, bottom] if right > left and bottom > top else None


class SherlockInvestigation:
    """One opt-in investigation session tied to the real live video pipeline."""

    def __init__(
        self,
        *,
        person_id: str,
        live_session_id: str,
        db_path: Any,
        emit_ui_intent: Callable[[dict[str, Any]], Any] | None = None,
        replay_service: Any = None,
        evidence_root: Any = None,
        max_captures: int = 120,
        max_duration_s: float = 20 * 60,
        auto_interval_s: float = 5.0,
        media_url_base: str = "/replay/media/sherlock",
    ) -> None:
        self.person_id = person_id or "me"
        self.live_session_id = live_session_id
        self.db_path = Path(db_path) if db_path else None
        base = (
            Path(evidence_root)
            if evidence_root is not None
            else (self.db_path.parent if self.db_path else Path.cwd() / "storage")
            / "sherlock_evidence"
        )
        self.evidence_root = base.resolve()
        self.max_captures = max(1, min(int(max_captures), 500))
        self.max_duration_s = max(60.0, min(float(max_duration_s), 3600.0))
        self.auto_interval_s = max(2.0, min(float(auto_interval_s), 30.0))
        self.media_url_base = media_url_base.rstrip("/")
        self._emit = emit_ui_intent
        self.replay_service = replay_service
        self._lock = threading.RLock()
        self._session_id: str | None = None
        self._started_monotonic = 0.0
        self._last_auto_at = 0.0
        self._last_signature: np.ndarray | None = None
        self._capture_count = 0
        self.metrics = {
            "sessions_started": 0,
            "captures": 0,
            "auto_captures": 0,
            "enhancements": 0,
            "comparisons": 0,
            "findings": 0,
            "refused_inactive": 0,
            "refused_cap": 0,
        }

    @property
    def active(self) -> bool:
        with self._lock:
            return self._session_id is not None and not self._expired()

    @property
    def session_id(self) -> str | None:
        with self._lock:
            return self._session_id

    def _connect(self) -> sqlite3.Connection:
        if self.db_path is None:
            raise RuntimeError("Sherlock requires a durable DB path")
        con = sqlite3.connect(str(self.db_path), timeout=10.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=10000")
        con.executescript(_SCHEMA)
        return con

    def _expired(self) -> bool:
        return bool(
            self._session_id
            and self._started_monotonic
            and time.monotonic() - self._started_monotonic > self.max_duration_s
        )

    def _session_dir(self, session_id: str | None = None) -> Path:
        sid = session_id or self._session_id
        if not sid:
            raise RuntimeError("Sherlock session is inactive")
        path = (self.evidence_root / sid).resolve()
        if self.evidence_root != path.parent:
            raise RuntimeError("unsafe Sherlock evidence path")
        return path

    def _emit_ui(self, intent: dict[str, Any]) -> None:
        if self._emit is not None:
            self._emit(intent)

    def _card(
        self,
        text: str,
        *,
        title: str = "Sherlock",
        truth_level: str = "observed",
        confidence: float = 1.0,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "ui_intent",
            "ui_intent_id": f"sherlock-{uuid.uuid4().hex}",
            "producer": "sherlock",
            "component": "context_card",
            "anchor": {"type": "head_locked"},
            "content": {"kind": "sherlock", "title": title, "text": text},
            "truth_level": truth_level,
            "confidence": float(confidence),
            "priority": 0.72,
            "ttl_ms": 12000,
            "evidence_refs": list(evidence_refs or []),
        }

    def start(self, title: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._session_id and self._expired():
                self.stop()
            if self._session_id:
                return self.status(emit=False)
            sid = f"sherlock_{uuid.uuid4().hex}"
            started = _now_iso()
            self._session_id = sid
            self._started_monotonic = time.monotonic()
            self._last_auto_at = 0.0
            self._last_signature = None
            self._capture_count = 0
            self._session_dir(sid).mkdir(parents=True, exist_ok=False)
            with self._connect() as con:
                con.execute(
                    """INSERT INTO sherlock_sessions_v19(
                         sherlock_session_id,person_id,live_session_id,title,status,
                         started_at,ended_at,capture_count,metadata_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        sid,
                        self.person_id,
                        self.live_session_id,
                        str(title or "Enquête visuelle")[:160],
                        "active",
                        started,
                        None,
                        0,
                        _safe_json(
                            {
                                "explicit_opt_in": True,
                                "max_captures": self.max_captures,
                                "max_duration_s": self.max_duration_s,
                            }
                        ),
                    ),
                )
            self.metrics["sessions_started"] += 1
            intent = self._card(
                "Mode enquête actif. Les captures Eye sont bornées et traçables. "
                "Dis « capture cette trace », « compare », « améliore » ou « termine Sherlock »."
            )
            self._emit_ui(intent)
            return {"status": "active", "sherlock_session_id": sid, "ui_intent": intent}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._session_id:
                return {"status": "inactive"}
            sid = self._session_id
            ended = _now_iso()
            with self._connect() as con:
                con.execute(
                    """UPDATE sherlock_sessions_v19
                       SET status='completed',ended_at=?,capture_count=?
                       WHERE sherlock_session_id=?""",
                    (ended, self._capture_count, sid),
                )
            self._session_id = None
            self._last_signature = None
            intent = self._card(
                f"Enquête terminée : {self._capture_count} capture(s) conservée(s).",
                truth_level="observed",
            )
            self._emit_ui(intent)
            return {
                "status": "completed",
                "sherlock_session_id": sid,
                "capture_count": self._capture_count,
                "ui_intent": intent,
            }

    def delete(self, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            sid = session_id or self._session_id
            if not sid:
                return {"status": "inactive"}
            directory = self._session_dir(sid)
            with self._connect() as con:
                con.execute(
                    "DELETE FROM sherlock_findings_v19 WHERE sherlock_session_id=?", (sid,)
                )
                con.execute(
                    "DELETE FROM sherlock_evidence_v19 WHERE sherlock_session_id=?", (sid,)
                )
                con.execute(
                    "DELETE FROM sherlock_sessions_v19 WHERE sherlock_session_id=?", (sid,)
                )
            if directory.is_dir():
                shutil.rmtree(directory)
            if sid == self._session_id:
                self._session_id = None
                self._last_signature = None
                self._capture_count = 0
            intent = self._card("Enquête et médias supprimés.", truth_level="observed")
            self._emit_ui(intent)
            return {"status": "deleted", "sherlock_session_id": sid, "ui_intent": intent}

    def status(self, *, emit: bool = True) -> dict[str, Any]:
        with self._lock:
            if self._expired():
                self.stop()
            state = "active" if self._session_id else "inactive"
            result = {
                "status": state,
                "sherlock_session_id": self._session_id,
                "capture_count": self._capture_count,
                "max_captures": self.max_captures,
            }
            if emit:
                intent = self._card(
                    f"Sherlock {state} — {self._capture_count}/{self.max_captures} captures."
                )
                self._emit_ui(intent)
                result["ui_intent"] = intent
            return result

    def _write_png(
        self,
        frame_bgr: np.ndarray,
        *,
        kind: str,
        parent_id: str | None,
        observed_at: str,
        source_frame_id: str | None,
        bbox: list[int] | None,
        truth_level: str,
        derivation: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            raise ValueError("empty Eye frame")
        ok, encoded = cv2.imencode(".png", frame_bgr)
        if not ok:
            raise RuntimeError("lossless PNG encoding failed")
        payload = bytes(encoded)
        evidence_id = f"shev_{uuid.uuid4().hex}"
        path = self._session_dir() / f"{evidence_id}.png"
        path.write_bytes(payload)
        height, width = frame_bgr.shape[:2]
        with self._connect() as con:
            con.execute(
                """INSERT INTO sherlock_evidence_v19(
                     evidence_id,sherlock_session_id,person_id,live_session_id,
                     evidence_kind,parent_evidence_id,observed_at,source_frame_id,
                     media_path,sha256,width,height,bbox_json,truth_level,
                     derivation_json,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    evidence_id,
                    self._session_id,
                    self.person_id,
                    self.live_session_id,
                    kind,
                    parent_id,
                    observed_at,
                    source_frame_id,
                    str(path),
                    _sha(payload),
                    width,
                    height,
                    _safe_json(bbox) if bbox else None,
                    truth_level,
                    _safe_json(dict(derivation or {})),
                    _safe_json(dict(metadata or {})),
                ),
            )
        return {
            "evidence_id": evidence_id,
            "kind": kind,
            "path": str(path),
            "sha256": _sha(payload),
            "width": width,
            "height": height,
            "bbox": bbox,
            "truth_level": truth_level,
            "ref": f"{self.media_url_base}/{evidence_id}",
            "observed_at": observed_at,
        }

    def capture(
        self,
        frame_bgr: np.ndarray | None,
        envelope: Any = None,
        *,
        bbox: Any = None,
        reason: str = "manual",
        metadata: Mapping[str, Any] | None = None,
        emit: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if not self.active:
                if self._session_id and self._expired():
                    self.stop()
                self.metrics["refused_inactive"] += 1
                return {"status": "inactive", "reason": "start Sherlock first"}
            if self._capture_count >= self.max_captures:
                self.metrics["refused_cap"] += 1
                return {"status": "cap_reached", "max_captures": self.max_captures}
            if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
                return {"status": "no_frame"}
            observed_at = str(
                getattr(envelope, "captured_at_utc", None) or _now_iso()
            )
            frame_id = str(getattr(envelope, "frame_id", "") or "") or None
            full = self._write_png(
                frame_bgr.copy(),
                kind="original",
                parent_id=None,
                observed_at=observed_at,
                source_frame_id=frame_id,
                bbox=None,
                truth_level="observed",
                metadata={"reason": reason, **dict(metadata or {})},
            )
            selected = full
            clean = _clean_bbox(bbox, full["width"], full["height"])
            if clean:
                x1, y1, x2, y2 = clean
                selected = self._write_png(
                    frame_bgr[y1:y2, x1:x2].copy(),
                    kind="crop",
                    parent_id=full["evidence_id"],
                    observed_at=observed_at,
                    source_frame_id=frame_id,
                    bbox=clean,
                    truth_level="observed",
                    derivation={"operation": "pixel_crop", "source_bbox": clean},
                    metadata={"reason": reason},
                )
            self._capture_count += 1
            self.metrics["captures"] += 1
            if reason == "auto_change":
                self.metrics["auto_captures"] += 1
            with self._connect() as con:
                con.execute(
                    """UPDATE sherlock_sessions_v19 SET capture_count=?
                       WHERE sherlock_session_id=?""",
                    (self._capture_count, self._session_id),
                )
            result = {
                "status": "captured",
                "sherlock_session_id": self._session_id,
                "original": full,
                "selected": selected,
            }
            if emit:
                intent = self._media_intent(
                    [selected],
                    title="Capture Sherlock",
                    truth_level="observed",
                )
                self._emit_ui(intent)
                result["ui_intent"] = intent
            return result

    def observe_frame(self, frame_bgr: np.ndarray | None, envelope: Any = None) -> None:
        """Bounded auto-sampling while active; never blocks or runs when inactive."""
        if not self.active:
            if self.session_id is not None:
                self.stop()
            return
        if frame_bgr is None or frame_bgr.size == 0:
            return
        now = time.monotonic()
        if now - self._last_auto_at < self.auto_interval_s:
            return
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        signature = cv2.resize(gray, (32, 18), interpolation=cv2.INTER_AREA)
        changed = self._last_signature is None or float(
            np.mean(cv2.absdiff(signature, self._last_signature))
        ) >= 12.0
        self._last_signature = signature
        self._last_auto_at = now
        if changed:
            self.capture(frame_bgr, envelope, reason="auto_change", emit=False)

    def record_finding(
        self,
        *,
        kind: str,
        statement: str,
        truth_level: str,
        confidence: float,
        evidence_refs: list[str] | None = None,
        detail: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            if not self.active:
                return None
            finding_id = f"shfind_{uuid.uuid4().hex}"
            row = {
                "finding_id": finding_id,
                "kind": str(kind),
                "statement": str(statement)[:1000],
                "truth_level": str(truth_level),
                "confidence": max(0.0, min(float(confidence), 1.0)),
                "evidence_refs": list(dict.fromkeys(evidence_refs or []))[:32],
                "detail": dict(detail or {}),
                "observed_at": observed_at or _now_iso(),
            }
            with self._connect() as con:
                con.execute(
                    """INSERT INTO sherlock_findings_v19(
                         finding_id,sherlock_session_id,person_id,finding_kind,
                         observed_at,statement,truth_level,confidence,
                         evidence_refs_json,detail_json,status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        finding_id,
                        self._session_id,
                        self.person_id,
                        row["kind"],
                        row["observed_at"],
                        row["statement"],
                        row["truth_level"],
                        row["confidence"],
                        _safe_json(row["evidence_refs"]),
                        _safe_json(row["detail"]),
                        "candidate" if row["truth_level"] != "observed" else "recorded",
                    ),
                )
            self.metrics["findings"] += 1
            return row

    def observe_scene_delta(self, delta: Mapping[str, Any]) -> None:
        if not self.active:
            return
        entities = list(delta.get("entities") or [])
        removed = list(delta.get("removed") or delta.get("removed_track_ids") or [])
        labels = [
            str(item.get("label") or "")
            for item in entities
            if isinstance(item, Mapping) and item.get("label")
        ]
        if not labels and not removed:
            return
        frame_id = str(delta.get("frame_id") or "")
        self.record_finding(
            kind="scene_delta",
            statement=(
                "Objets suivis : " + ", ".join(labels[:12])
                + (f"; disparus : {len(removed)}" if removed else "")
            ),
            truth_level="observed",
            confidence=1.0,
            evidence_refs=[f"frame:{frame_id}"] if frame_id else [],
            detail={
                "labels": labels[:24],
                "removed": removed[:24],
                "frame_id": frame_id or None,
            },
        )

    def observe_change_attention(self, cue: Mapping[str, Any] | None) -> None:
        if not self.active or not isinstance(cue, Mapping):
            return
        self.record_finding(
            kind="change_attention",
            statement=str(cue.get("message") or "Changement de scène détecté."),
            truth_level="probable",
            confidence=float(cue.get("score") or 0.0),
            evidence_refs=list(cue.get("evidence_refs") or []),
            detail={
                "zone": cue.get("zone"),
                "appeared": list(cue.get("appeared") or []),
                "disappeared": list(cue.get("disappeared") or []),
            },
        )

    def observe_focus_result(
        self, request: Mapping[str, Any], result: Mapping[str, Any] | None
    ) -> None:
        """Attach real OCR/detector focus output to the active case timeline."""
        if not self.active or not isinstance(result, Mapping):
            return
        content = result.get("content")
        if not isinstance(content, Mapping):
            return
        kind = str(content.get("kind") or request.get("kind") or "focus")
        text = str(content.get("text") or "").strip()
        label = str(content.get("label") or "").strip()
        if not text and not label:
            return
        truth = str(result.get("truth_level") or "unknown")
        self.record_finding(
            kind=f"focus_{kind}",
            statement=text or f"Objet observé : {label}",
            truth_level=truth,
            confidence=float(result.get("confidence") or 0.0),
            evidence_refs=list(result.get("evidence_refs") or []),
            detail={
                "source_frame_id": result.get("source_frame_id"),
                "source": content.get("source"),
                "label": label or None,
                "screen_bbox": content.get("screen_bbox"),
                "ocr_lines": list(content.get("lines") or [])[:30],
            },
            observed_at=str(result.get("created_at") or _now_iso()),
        )

    def enhance(self, evidence_id: str | None = None) -> dict[str, Any]:
        """Deterministic readability enhancement; never changes observed truth."""
        with self._lock:
            source = self._evidence_row(evidence_id)
            if source is None:
                return {"status": "no_evidence"}
            image = cv2.imread(str(source["media_path"]), cv2.IMREAD_COLOR)
            if image is None:
                return {"status": "media_missing", "evidence_id": source["evidence_id"]}
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            light, a, b = cv2.split(lab)
            light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
            enhanced = cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR)
            blurred = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
            enhanced = cv2.addWeighted(enhanced, 1.35, blurred, -0.35, 0)
            enhanced = cv2.resize(
                enhanced, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LANCZOS4
            )
            derived = self._write_png(
                enhanced,
                kind="enhanced",
                parent_id=str(source["evidence_id"]),
                observed_at=_now_iso(),
                source_frame_id=source["source_frame_id"],
                bbox=json.loads(source["bbox_json"]) if source["bbox_json"] else None,
                truth_level="enhanced_candidate",
                derivation={
                    "pipeline": ["CLAHE_L2", "unsharp_1.35", "Lanczos_x2"],
                    "source_sha256": source["sha256"],
                },
            )
            self.metrics["enhancements"] += 1
            original = self._row_public(source)
            intent = self._media_intent(
                [original, derived],
                title="Original / rehaussement",
                truth_level="enhanced_candidate",
            )
            self._emit_ui(intent)
            return {
                "status": "enhanced",
                "original": original,
                "enhanced": derived,
                "ui_intent": intent,
            }

    def compare(
        self, first_evidence_id: str | None = None, second_evidence_id: str | None = None
    ) -> dict[str, Any]:
        """Measured visual comparison. It proposes no identity or causal claim."""
        with self._lock:
            rows = self._latest_evidence_rows(limit=2)
            first = self._evidence_row(first_evidence_id) if first_evidence_id else (
                rows[1] if len(rows) > 1 else None
            )
            second = self._evidence_row(second_evidence_id) if second_evidence_id else (
                rows[0] if rows else None
            )
            if first is None or second is None or first["evidence_id"] == second["evidence_id"]:
                return {"status": "need_two_evidence"}
            a = cv2.imread(str(first["media_path"]), cv2.IMREAD_GRAYSCALE)
            b = cv2.imread(str(second["media_path"]), cv2.IMREAD_GRAYSCALE)
            if a is None or b is None:
                return {"status": "media_missing"}
            size = (320, 180)
            ar = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
            br = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
            pixel_similarity = 1.0 - float(np.mean(cv2.absdiff(ar, br))) / 255.0
            # Keep scikit-image off the inactive/live startup path; it is loaded
            # only for an explicit manual comparison.
            from skimage.metrics import structural_similarity

            ssim = float(structural_similarity(ar, br, data_range=255))
            orb = cv2.ORB_create(nfeatures=500)
            ka, da = orb.detectAndCompute(ar, None)
            kb, db = orb.detectAndCompute(br, None)
            match_ratio = 0.0
            matches = 0
            if da is not None and db is not None and len(ka) and len(kb):
                raw = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
                matches = sum(1 for item in raw if item.distance <= 48)
                match_ratio = matches / max(1, min(len(ka), len(kb)))
            score = max(
                0.0,
                min(
                    1.0,
                    pixel_similarity * 0.25 + ssim * 0.45 + match_ratio * 0.30,
                ),
            )
            statement = (
                "Les deux captures sont visuellement très proches."
                if score >= 0.82
                else "Une différence visuelle mesurable existe entre les deux captures."
            )
            refs = [
                f"sherlock:{first['evidence_id']}",
                f"sherlock:{second['evidence_id']}",
            ]
            finding = self.record_finding(
                kind="visual_comparison",
                statement=statement,
                truth_level="probable",
                confidence=score if score >= 0.82 else 1.0 - score,
                evidence_refs=refs,
                detail={
                    "pixel_similarity": round(pixel_similarity, 4),
                    "structural_similarity": round(ssim, 4),
                    "orb_match_ratio": round(match_ratio, 4),
                    "orb_good_matches": matches,
                    "no_identity_or_cause_inferred": True,
                },
            )
            self.metrics["comparisons"] += 1
            intent = self._card(
                statement,
                title="Comparaison Sherlock",
                truth_level="probable",
                confidence=float(finding["confidence"] if finding else 0.0),
                evidence_refs=refs,
            )
            self._emit_ui(intent)
            return {"status": "compared", "finding": finding, "ui_intent": intent}

    def timeline(self) -> dict[str, Any]:
        with self._lock:
            sid = self._session_id
            if not sid:
                return {"status": "inactive"}
            with self._connect() as con:
                session = con.execute(
                    "SELECT * FROM sherlock_sessions_v19 WHERE sherlock_session_id=?",
                    (sid,),
                ).fetchone()
                findings = [
                    dict(row)
                    for row in con.execute(
                        """SELECT finding_kind,observed_at,statement,truth_level,
                                  confidence,evidence_refs_json,detail_json
                           FROM sherlock_findings_v19
                           WHERE sherlock_session_id=? ORDER BY observed_at""",
                        (sid,),
                    ).fetchall()
                ]
                actions: list[dict[str, Any]] = []
                if self._table_exists(con, "live_action_candidates_v19") and session:
                    actions = [
                        dict(row)
                        for row in con.execute(
                            """SELECT action_event_id,action_type,subject_label,
                                      object_label,started_at,ended_at,confidence,
                                      truth_level,evidence_refs_json,detail_json
                               FROM live_action_candidates_v19
                               WHERE person_id=? AND live_session_id=?
                                 AND ended_at>=?
                               ORDER BY ended_at LIMIT 80""",
                            (self.person_id, self.live_session_id, session["started_at"]),
                        ).fetchall()
                    ]
            replay_bundle: dict[str, Any] | None = None
            replay_intent: dict[str, Any] | None = None
            if session is not None and self.replay_service is not None:
                try:
                    replay_bundle = self.replay_service.assemble_bundle(
                        start=str(session["started_at"]), end=_now_iso()
                    )
                    replay_intent = self.replay_service.virtual_screen_intent(
                        replay_bundle
                    )
                    replay_intent["producer"] = "sherlock"
                    replay_intent["truth_level"] = "observed"
                except Exception:
                    replay_bundle = None
                    replay_intent = None
            events: list[dict[str, Any]] = []
            for finding in findings:
                events.append(
                    {
                        "at": finding["observed_at"],
                        "kind": finding["finding_kind"],
                        "text": finding["statement"],
                        "truth_level": finding["truth_level"],
                        "confidence": finding["confidence"],
                        "evidence_refs": json.loads(finding["evidence_refs_json"] or "[]"),
                    }
                )
            for action in actions:
                subject = action.get("subject_label") or "quelqu'un"
                obj = action.get("object_label")
                text = f"{subject}: {action['action_type']}" + (f" ({obj})" if obj else "")
                events.append(
                    {
                        "at": action["ended_at"],
                        "kind": "temporal_action",
                        "text": text,
                        "truth_level": action["truth_level"],
                        "confidence": action["confidence"],
                        "evidence_refs": json.loads(action["evidence_refs_json"] or "[]"),
                    }
                )
            events.sort(key=lambda item: str(item.get("at") or ""))
            lines = [
                f"{str(item['at'])[11:19]} [{item['truth_level']}] {item['text']}"
                for item in events[-12:]
            ]
            intent = self._card(
                "\n".join(lines) if lines else "Aucun indice exploitable pour le moment.",
                title="Timeline Sherlock",
                truth_level="probable" if events else "unknown",
                confidence=1.0 if events else 0.0,
                evidence_refs=[
                    ref for item in events[-12:] for ref in item.get("evidence_refs", [])
                ][:24],
            )
            if replay_intent is not None:
                self._emit_ui(replay_intent)
            self._emit_ui(intent)
            return {
                "status": "ok",
                "events": events,
                "replay_bundle": replay_bundle,
                "replay_intent": replay_intent,
                "ui_intent": intent,
            }

    def _evidence_row(self, evidence_id: str | None) -> sqlite3.Row | None:
        with self._connect() as con:
            if evidence_id:
                return con.execute(
                    """SELECT * FROM sherlock_evidence_v19
                       WHERE evidence_id=? AND person_id=?""",
                    (evidence_id, self.person_id),
                ).fetchone()
            if not self._session_id:
                return None
            return con.execute(
                """SELECT * FROM sherlock_evidence_v19
                   WHERE sherlock_session_id=? ORDER BY rowid DESC LIMIT 1""",
                (self._session_id,),
            ).fetchone()

    def _latest_evidence_rows(self, limit: int) -> list[sqlite3.Row]:
        if not self._session_id:
            return []
        with self._connect() as con:
            return con.execute(
                """SELECT * FROM sherlock_evidence_v19
                   WHERE sherlock_session_id=? AND evidence_kind IN ('original','crop')
                   ORDER BY rowid DESC LIMIT ?""",
                (self._session_id, int(limit)),
            ).fetchall()

    def resolve_media_path(self, evidence_id: str) -> Path | None:
        row = self._evidence_row(evidence_id)
        if row is None:
            return None
        path = Path(str(row["media_path"])).resolve()
        try:
            path.relative_to(self.evidence_root)
        except ValueError:
            return None
        return path if path.is_file() else None

    def _row_public(self, row: Mapping[str, Any]) -> dict[str, Any]:
        evidence_id = str(row["evidence_id"])
        return {
            "evidence_id": evidence_id,
            "kind": row["evidence_kind"],
            "ref": f"{self.media_url_base}/{evidence_id}",
            "at": row["observed_at"],
            "truth_level": row["truth_level"],
            "sha256": row["sha256"],
            "width": row["width"],
            "height": row["height"],
        }

    def _media_intent(
        self, items: list[Mapping[str, Any]], *, title: str, truth_level: str
    ) -> dict[str, Any]:
        frames = [
            {
                "ref": item.get("ref"),
                "at": item.get("observed_at") or item.get("at"),
                "frame_id": item.get("evidence_id"),
                "truth_level": item.get("truth_level"),
            }
            for item in items
        ]
        return {
            "type": "ui_intent",
            "ui_intent_id": f"sherlock-media-{uuid.uuid4().hex}",
            "producer": "sherlock",
            "component": "virtual_screen",
            "content": {
                "kind": "sherlock_evidence",
                "title": title,
                "frames": frames,
                "clips": [],
                "counts": {"frames": len(frames), "clips": 0},
            },
            "truth_level": truth_level,
            "confidence": 1.0,
            "priority": 0.74,
            "ttl_ms": 20000,
            "evidence_refs": [
                f"sherlock:{item.get('evidence_id')}" for item in items
            ],
        }

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        return (
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            is not None
        )
