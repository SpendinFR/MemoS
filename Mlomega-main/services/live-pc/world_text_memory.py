from __future__ import annotations

"""Durable, evidenced OCR observations and conservative price comparisons."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import statistics
import unicodedata
from typing import Any, Mapping


_SCHEMA = """
CREATE TABLE IF NOT EXISTS world_text_observations_v19(
  text_observation_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  live_session_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  place_key TEXT,
  category TEXT NOT NULL,
  text TEXT NOT NULL,
  normalized_text TEXT NOT NULL,
  comparison_key TEXT,
  numeric_value REAL,
  currency TEXT,
  source TEXT NOT NULL,
  source_frame_id TEXT,
  target_track_id TEXT,
  latitude REAL,
  longitude REAL,
  location_accuracy_m REAL,
  confidence REAL NOT NULL,
  truth_level TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_text_owner_place_time_v19
  ON world_text_observations_v19(person_id,place_key,observed_at);
CREATE INDEX IF NOT EXISTS idx_world_text_owner_key_v19
  ON world_text_observations_v19(person_id,comparison_key,observed_at);

CREATE TABLE IF NOT EXISTS world_text_anomalies_v19(
  anomaly_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  text_observation_id TEXT NOT NULL,
  anomaly_type TEXT NOT NULL,
  current_value REAL NOT NULL,
  reference_value REAL NOT NULL,
  sample_count INTEGER NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(text_observation_id) REFERENCES world_text_observations_v19(text_observation_id)
);
"""

_PRICE = re.compile(
    r"(?<!\d)(\d{1,5}(?:[.,]\d{1,2})?)\s*(€|eur(?:os?)?|\$|usd|£|gbp)(?=\s|$|[.,;:])",
    re.IGNORECASE,
)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9€$£]+", " ", text.casefold()).split())


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    return prefix + "_" + hashlib.sha256(payload).hexdigest()[:24]


def _category(text: str) -> str:
    folded = _fold(text)
    groups = (
        ("medicine", ("mg", "comprime", "dose", "medicament", "pharmacie")),
        ("legal", ("contrat", "clause", "article", "signature", "obligation")),
        ("menu_price", ("menu", "prix", "eur", "€", "restaurant", "baguette")),
        ("address", ("rue", "avenue", "boulevard", "adresse", "cedex")),
        ("notice", ("notice", "attention", "danger", "mode d emploi")),
    )
    for category, words in groups:
        if any(word in folded for word in words):
            return category
    return "world_text"


class WorldTextMemory:
    def __init__(
        self,
        *,
        person_id: str,
        live_session_id: str,
        db_path: str | Path | None,
    ) -> None:
        self.person_id = str(person_id or "me")
        self.live_session_id = str(live_session_id or "live")
        self.db_path = Path(db_path or "storage/memory.db")
        self.metrics = {"stored": 0, "deduped": 0, "price_anomalies": 0}
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=3.0)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)
            columns = {
                str(row["name"])
                for row in con.execute(
                    "PRAGMA table_info(world_text_observations_v19)"
                ).fetchall()
            }
            for name in ("latitude", "longitude", "location_accuracy_m"):
                if name not in columns:
                    con.execute(
                        f"ALTER TABLE world_text_observations_v19 "
                        f"ADD COLUMN {name} REAL"
                    )

    @staticmethod
    def _price(text: str) -> tuple[float | None, str | None, str | None]:
        match = _PRICE.search(text)
        if not match:
            return None, None, None
        value = float(match.group(1).replace(",", "."))
        raw_currency = match.group(2).casefold()
        currency = "EUR" if raw_currency in {"€", "eur", "euro", "euros"} else (
            "USD" if raw_currency in {"$", "usd"} else "GBP"
        )
        signature = _fold(_PRICE.sub(" PRICE ", text))
        return value, currency, signature or None

    def record(
        self,
        result: Mapping[str, Any],
        *,
        request: Mapping[str, Any],
        place_key: str | None,
        observed_at: datetime | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        content = result.get("content")
        if not isinstance(content, Mapping):
            return None, None
        text = " ".join(str(content.get("text") or "").split())[:4000]
        if not text:
            return None, None
        now = observed_at or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        frame_id = str(result.get("source_frame_id") or "")
        track_id = str(result.get("target_track_id") or request.get("track_id") or "")
        normalized = _fold(text)
        value, currency, comparison_key = self._price(text)
        place = _fold(place_key)[:200] or None
        observation_id = _stable_id(
            "worldtext",
            self.person_id,
            self.live_session_id,
            frame_id,
            track_id,
            normalized,
        )
        evidence = list(result.get("evidence_refs") or [])
        detail = {
            "lines": list(content.get("lines") or [])[:50],
            "request_kind": str(request.get("kind") or "ocr"),
            "request_query": str(request.get("query") or "")[:200] or None,
        }
        location = (
            request.get("location")
            if isinstance(request.get("location"), Mapping)
            else {}
        )
        try:
            latitude = float(location.get("latitude"))
            longitude = float(location.get("longitude"))
            location_accuracy = float(location.get("horizontal_accuracy_m"))
        except (TypeError, ValueError):
            latitude = longitude = location_accuracy = None
        if latitude is not None:
            detail["location"] = {
                "latitude": latitude,
                "longitude": longitude,
                "horizontal_accuracy_m": location_accuracy,
                "source": str(location.get("source") or "android_location"),
            }

        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                """INSERT OR IGNORE INTO world_text_observations_v19(
                     text_observation_id,person_id,live_session_id,observed_at,
                     place_key,category,text,normalized_text,comparison_key,
                     numeric_value,currency,source,source_frame_id,target_track_id,
                     latitude,longitude,location_accuracy_m,confidence,truth_level,
                     evidence_refs_json,detail_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id,
                    self.person_id,
                    self.live_session_id,
                    now_iso,
                    place,
                    _category(text),
                    text,
                    normalized,
                    comparison_key,
                    value,
                    currency,
                    str(content.get("source") or "ocr"),
                    frame_id or None,
                    track_id or None,
                    latitude,
                    longitude,
                    location_accuracy,
                    float(result.get("confidence") or 0.0),
                    str(result.get("truth_level") or "observed"),
                    json.dumps(evidence, ensure_ascii=False),
                    json.dumps(detail, ensure_ascii=False, sort_keys=True),
                ),
            )
            inserted = int(con.execute("SELECT changes()").fetchone()[0])
            if not inserted:
                con.commit()
                self.metrics["deduped"] += 1
                return None, None

            prior: list[sqlite3.Row] = []
            if value is not None and comparison_key and place:
                prior = con.execute(
                    """SELECT text_observation_id,numeric_value,evidence_refs_json
                       FROM world_text_observations_v19
                       WHERE person_id=? AND place_key=? AND comparison_key=?
                         AND currency=? AND text_observation_id<>?
                         AND numeric_value IS NOT NULL
                       ORDER BY observed_at DESC LIMIT 20""",
                    (
                        self.person_id,
                        place,
                        comparison_key,
                        currency,
                        observation_id,
                    ),
                ).fetchall()

            anomaly = None
            if len(prior) >= 3 and value is not None:
                reference = float(
                    statistics.median(float(row["numeric_value"]) for row in prior)
                )
                delta = value - reference
                if reference > 0 and abs(delta) >= max(0.30, reference * 0.25):
                    anomaly_id = _stable_id("worldtextanomaly", observation_id)
                    refs = [f"world_text_observations_v19:{observation_id}"] + [
                        f"world_text_observations_v19:{row['text_observation_id']}"
                        for row in prior[:5]
                    ]
                    confidence = min(0.9, 0.62 + len(prior) * 0.04)
                    con.execute(
                        """INSERT OR IGNORE INTO world_text_anomalies_v19(
                             anomaly_id,person_id,text_observation_id,anomaly_type,
                             current_value,reference_value,sample_count,confidence,
                             status,evidence_refs_json,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            anomaly_id,
                            self.person_id,
                            observation_id,
                            "price_change",
                            value,
                            reference,
                            len(prior),
                            confidence,
                            "candidate",
                            json.dumps(refs, ensure_ascii=False),
                            now_iso,
                        ),
                    )
                    anomaly = {
                        "anomaly_id": anomaly_id,
                        "current_value": value,
                        "reference_value": reference,
                        "currency": currency,
                        "sample_count": len(prior),
                        "confidence": confidence,
                        "evidence_refs": refs,
                        "direction": "higher" if delta > 0 else "lower",
                    }
            con.commit()

        self.metrics["stored"] += 1
        if anomaly is not None:
            self.metrics["price_anomalies"] += 1
        return {
            "text_observation_id": observation_id,
            "text": text,
            "place_key": place,
            "category": _category(text),
            "numeric_value": value,
            "currency": currency,
            "comparison_key": comparison_key,
            "evidence_refs": evidence,
        }, anomaly

    def anomaly_intent(self, anomaly: Mapping[str, Any], *, text: str) -> dict[str, Any]:
        currency = str(anomaly.get("currency") or "")
        unit = "€" if currency == "EUR" else currency
        current = float(anomaly["current_value"])
        reference = float(anomaly["reference_value"])
        direction = "au-dessus" if anomaly.get("direction") == "higher" else "en dessous"
        return {
            "type": "ui_intent",
            "ui_intent_id": str(anomaly["anomaly_id"]),
            "producer": "world_text",
            "component": "context_card",
            "content": {
                "kind": "price_change",
                "title": "Prix inhabituel",
                "text": (
                    f"{current:.2f} {unit} est {direction} de la médiane observée "
                    f"ici ({reference:.2f} {unit}, "
                    f"{int(anomaly['sample_count'])} observations)."
                ),
                "observed_text": text[:500],
                "memory_write": False,
            },
            "truth_level": "inferred",
            "confidence": float(anomaly["confidence"]),
            "priority": 0.55,
            "ttl_ms": 12_000,
            "evidence_refs": list(anomaly.get("evidence_refs") or []),
        }
