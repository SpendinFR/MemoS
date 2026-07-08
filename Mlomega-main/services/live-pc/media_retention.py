from __future__ import annotations

"""MediaRetention — E54: media retention & disk budget on the REAL tables.

Decision (user, 2026-07-08): **keep everything**, budget **100 GB**, be able to
replay clips/audio at any time. So retention is conservative by construction:

* a media that ANY proof cites is **never** deleted — not by age, not by budget;
* only **unreferenced** media older than ``retention_days`` are purge-eligible;
* the global byte budget evicts the **oldest unreferenced** media first, and if
  the whole overshoot is referenced it deletes **nothing** and returns a WARN.

Three operations, all best-effort (never raise, never block the close-day):

1. ``transcode_audio`` — after the nightly re-transcription (close-day done), the
   archived VAD WAVs (``brainlive_audio_segments_v154`` chunks) are transcoded to
   Opus via ffmpeg (~÷10). The DB chunk/source paths are repointed to the ``.opus``
   file, the ORIGINAL sha256 is kept in metadata (reversible), and the WAV is
   removed only after the Opus exists and its size is sane. Disabled/degraded
   honestly when ffmpeg is absent.
2. ``purge_unreferenced`` — unreferenced media older than ``retention_days`` are
   deleted (file + owning table rows) coherently.
3. ``enforce_budget`` — if total media usage exceeds ``total_gb``, evict the oldest
   unreferenced media first until back under budget; a referenced overshoot is a
   WARN, not a deletion.

**Where "referenced" lives in the real schema** (inspected, not guessed): the
evidence chain is a set of ``evidence_refs_json`` / ``evidence_json`` columns
across the V18/V19 tables. A keyframe is cited as the string ``"frame:<frame_id>"``
(worldbrain/visionrt) and/or as ``{"source_table": ..., "source_id": "<id>"}``; a
clip via ``visual_events_v19.asset_id`` (FK) or its ``visual_asset_id`` in refs;
an audio WAV is the deep-audio evidence pointed at by its ``brainlive_sensor_events``
``speech_segment`` row (``source_path``/``chunk_path``). We scan every evidence
column for these tokens — a media is referenced if any token for it is found.
"""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# Every column across the schema that can hold an evidence reference. Scanned as
# raw text for id/path tokens — cheap, table-name-agnostic, and robust to the
# different ref shapes ("frame:<id>", {"source_id": ...}, bare paths).
_EVIDENCE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("visual_events_v19", "evidence_refs_json"),
    ("visual_events_v19", "observation_json"),
    ("visual_events_v19", "entity_json"),
    ("scene_session_summaries_v19", "evidence_refs_json"),
    ("world_entity_links_v19", "evidence_refs_json"),
    ("brain2_spatial_routine_models", "evidence_refs_json"),
    ("brain2_visual_task_models", "evidence_refs_json"),
    ("life_model_entries_v19", "evidence_refs_json"),
    ("predictions_v19", "evidence_refs_json"),
    ("prediction_outcomes_v19", "evidence_refs_json"),
    ("self_schema_v19", "evidence_refs_json"),
    ("brainlive_life_hypotheses", "evidence_json"),
)


@dataclass
class RetentionConfig:
    total_gb: float = 100.0
    warn_gb: float = 80.0
    retention_days: int = 90
    transcode_audio: bool = True
    # A media younger than this is never age-purged even when unreferenced (a
    # very recent capture may not yet have been consolidated into evidence).
    min_age_days_floor: int = 1

    @property
    def total_bytes(self) -> int:
        return int(self.total_gb * 1024 * 1024 * 1024)

    @property
    def warn_bytes(self) -> int:
        return int(self.warn_gb * 1024 * 1024 * 1024)


@dataclass
class MediaItem:
    """One media on disk, joined to the row(s) that own it."""

    media_kind: str            # 'keyframe' | 'clip' | 'audio'
    path: str
    captured_at: str | None
    size_bytes: int
    tokens: tuple[str, ...]    # id/path tokens that make it 'referenced' if cited
    # Coherent deletion targets: (table, pk_column, pk_value).
    rows: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    referenced: bool = False


@dataclass
class RetentionReport:
    total_bytes: int = 0
    referenced_bytes: int = 0
    unreferenced_bytes: int = 0
    transcoded: int = 0
    transcode_saved_bytes: int = 0
    transcode_skipped: int = 0
    purged_aged: int = 0
    purged_aged_bytes: int = 0
    evicted_budget: int = 0
    evicted_budget_bytes: int = 0
    warnings: list[str] = field(default_factory=list)
    disabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "disabled" if self.disabled else "ok",
            "total_bytes": self.total_bytes,
            "referenced_bytes": self.referenced_bytes,
            "unreferenced_bytes": self.unreferenced_bytes,
            "transcoded": self.transcoded,
            "transcode_saved_bytes": self.transcode_saved_bytes,
            "transcode_skipped": self.transcode_skipped,
            "purged_aged": self.purged_aged,
            "purged_aged_bytes": self.purged_aged_bytes,
            "evicted_budget": self.evicted_budget,
            "evicted_budget_bytes": self.evicted_budget_bytes,
            "warnings": list(self.warnings),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = str(text).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _size(path: str | Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class MediaRetention:
    """Retention over the real media tables + on-disk files.

    One instance per close-day. All public methods are best-effort: any failure is
    captured as a warning and never raised, so the close-day is never failed by a
    purge/transcode.
    """

    def __init__(
        self,
        *,
        person_id: str,
        config: RetentionConfig | None = None,
        db_path: Any = None,
    ) -> None:
        self.person_id = person_id
        self.config = config or RetentionConfig()
        self.db_path = db_path

    # ------------------------------------------------------------------ db
    def _connect(self):
        from mlomega_audio_elite.db import connect  # type: ignore

        return connect(self.db_path)

    def _table_exists(self, con, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------ referenced
    def _referenced_blob(self, con) -> str:
        """One big lowercased text blob of every evidence column present.

        A media is 'referenced' if any of its tokens (frame_id, asset_id, path,
        sha, sensor path) is a substring of this blob. Cheap and shape-agnostic —
        it catches "frame:<id>", {"source_id": "<id>"}, bare paths and sha refs
        alike, without having to model each ref schema."""
        parts: list[str] = []
        for table, column in _EVIDENCE_COLUMNS:
            if not self._table_exists(con, table):
                continue
            try:
                for (val,) in con.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
                ):
                    if val:
                        parts.append(str(val))
            except Exception:
                continue
        return "\n".join(parts).lower()

    def _is_referenced(self, item: MediaItem, blob: str) -> bool:
        """A token counts as a reference only on a DELIMITED occurrence, so a
        shorter id is not a false-positive substring of a longer one (e.g.
        ``kf-old`` must not match inside ``kf-oldref``). The token must be bounded
        by a non-[a-z0-9] character (or a string edge) on both sides — ids/paths
        use ``-`` and ``.`` internally but are wrapped by quotes/colons/slashes in
        the refs."""
        for tok in item.tokens:
            t = str(tok or "").strip().lower()
            if not t:
                continue
            pat = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
            if re.search(pat, blob):
                return True
        return False

    # ------------------------------------------------------------------ inventory
    def _keyframes(self, con) -> list[MediaItem]:
        items: list[MediaItem] = []
        if not self._table_exists(con, "vision_frames"):
            return items
        rows = con.execute(
            """SELECT frame_id, source_asset_id, image_path, image_sha256, captured_at
               FROM vision_frames WHERE image_path IS NOT NULL"""
        ).fetchall()
        for r in rows:
            path = r["image_path"]
            if not path:
                continue
            frame_id = r["frame_id"]
            asset_id = r["source_asset_id"]
            tokens = tuple(t for t in (
                f"frame:{frame_id}", frame_id, asset_id, r["image_sha256"],
                path, Path(str(path)).name,
            ) if t)
            del_rows: list[tuple[str, str, str]] = [("vision_frames", "frame_id", str(frame_id))]
            if asset_id and self._table_exists(con, "raw_assets"):
                del_rows.append(("raw_assets", "asset_id", str(asset_id)))
            items.append(MediaItem(
                media_kind="keyframe", path=str(path), captured_at=r["captured_at"],
                size_bytes=_size(path), tokens=tokens, rows=tuple(del_rows),
            ))
        return items

    def _clips(self, con) -> list[MediaItem]:
        items: list[MediaItem] = []
        if not self._table_exists(con, "visual_evidence_assets_v19"):
            return items
        rows = con.execute(
            """SELECT visual_asset_id, uri, sha256, frame_id, captured_at, asset_kind
               FROM visual_evidence_assets_v19
               WHERE asset_kind IN ('clip','video','gif') AND uri IS NOT NULL"""
        ).fetchall()
        for r in rows:
            uri = r["uri"]
            if not uri:
                continue
            asset_id = r["visual_asset_id"]
            # A clip is referenced if any visual_event points at it (FK asset_id)
            # or its id/sha/path is cited in an evidence blob.
            tokens = tuple(t for t in (
                asset_id, r["sha256"], r["frame_id"], uri, Path(str(uri)).name,
            ) if t)
            items.append(MediaItem(
                media_kind="clip", path=str(uri), captured_at=r["captured_at"],
                size_bytes=_size(uri), tokens=tokens,
                rows=(("visual_evidence_assets_v19", "visual_asset_id", str(asset_id)),),
            ))
        return items

    def _clip_fk_referenced(self, con) -> set[str]:
        """Clip asset ids pointed at by a visual_events_v19.asset_id FK."""
        out: set[str] = set()
        if not self._table_exists(con, "visual_events_v19"):
            return out
        try:
            for (aid,) in con.execute(
                "SELECT DISTINCT asset_id FROM visual_events_v19 WHERE asset_id IS NOT NULL"
            ):
                if aid:
                    out.add(str(aid))
        except Exception:
            pass
        return out

    def _audio(self, con) -> list[MediaItem]:
        """Archived VAD WAV/Opus chunks. Audio is the nightly deep-audio evidence:
        while its ``brainlive_sensor_events`` speech_segment row exists it is
        referenced. We list the chunk once, keyed on its path, and gather the
        rows to delete together (segment projection + sensor event)."""
        items: list[MediaItem] = []
        if not self._table_exists(con, "brainlive_audio_segments_v154"):
            return items
        rows = con.execute(
            """SELECT segment_id, source_event_id, chunk_path, source_path, absolute_start
               FROM brainlive_audio_segments_v154
               WHERE chunk_path IS NOT NULL"""
        ).fetchall()
        for r in rows:
            path = r["chunk_path"] or r["source_path"]
            if not path:
                continue
            del_rows: list[tuple[str, str, str]] = [
                ("brainlive_audio_segments_v154", "segment_id", str(r["segment_id"]))
            ]
            items.append(MediaItem(
                media_kind="audio", path=str(path), captured_at=r["absolute_start"],
                size_bytes=_size(path),
                # Tokens: the path/name. Referenced iff the sensor event still
                # cites this chunk (handled specially in inventory()).
                tokens=(str(path), Path(str(path)).name),
                rows=tuple(del_rows),
            ))
        return items

    def _audio_referenced_paths(self, con) -> set[str]:
        """Chunk paths still cited by a live speech_segment sensor event — the
        deep-audio evidence link. As long as that row exists the WAV is proof."""
        out: set[str] = set()
        if not self._table_exists(con, "brainlive_sensor_events"):
            return out
        try:
            for (sp,) in con.execute(
                """SELECT source_path FROM brainlive_sensor_events
                   WHERE modality='audio' AND event_type='speech_segment'
                     AND source_path IS NOT NULL"""
            ):
                if sp:
                    out.add(str(sp))
        except Exception:
            pass
        return out

    def inventory(self) -> list[MediaItem]:
        """Every media on disk, each flagged referenced/unreferenced."""
        with self._connect() as con:
            blob = self._referenced_blob(con)
            clip_fk = self._clip_fk_referenced(con)
            audio_refs = self._audio_referenced_paths(con)
            items = self._keyframes(con) + self._clips(con) + self._audio(con)
        for it in items:
            if it.media_kind == "clip":
                # FK from a visual_event, or cited in an evidence blob.
                asset_id = it.rows[0][2] if it.rows else ""
                it.referenced = (asset_id in clip_fk) or self._is_referenced(it, blob)
            elif it.media_kind == "audio":
                it.referenced = (it.path in audio_refs) or self._is_referenced(it, blob)
            else:
                it.referenced = self._is_referenced(it, blob)
        return items

    # ------------------------------------------------------------------ delete
    def _delete_item(self, item: MediaItem) -> int:
        """Delete the on-disk file + owning rows coherently. Returns bytes freed."""
        freed = item.size_bytes
        try:
            p = Path(item.path)
            if p.exists():
                p.unlink()
        except OSError:
            # File already gone (e.g. temp keyframe purged): still drop the rows so
            # the DB stops referencing a missing path.
            pass
        try:
            from mlomega_audio_elite.db import write_transaction  # type: ignore

            with self._connect() as con, write_transaction(con):
                for table, pk_col, pk_val in item.rows:
                    if not self._table_exists(con, table):
                        continue
                    con.execute(f"DELETE FROM {table} WHERE {pk_col}=?", (pk_val,))
                # Audio: also drop the sensor event that made it evidence, so a
                # deleted WAV is not left dangling in the deep-audio input.
                if item.media_kind == "audio" and self._table_exists(con, "brainlive_sensor_events"):
                    con.execute(
                        """DELETE FROM brainlive_sensor_events
                           WHERE source_path=? AND modality='audio'
                             AND event_type='speech_segment'""",
                        (item.path,),
                    )
        except Exception:
            return 0
        return freed

    # ------------------------------------------------------------------ transcode
    def transcode_audio_chunks(self, report: RetentionReport) -> None:
        """WAV → Opus (~÷10) for archived audio, reversible (keeps original sha).

        Runs only after the nightly re-transcription (i.e. from the close-day, once
        the deep-audio stage is done). Disabled by config or when ffmpeg is absent
        — degraded honestly, never a crash. Repoints the DB chunk/source paths to
        the ``.opus`` and stores the original sha256 in the segment speaker_json
        metadata so the move is auditable/reversible."""
        if not self.config.transcode_audio:
            report.warnings.append("transcode_audio disabled by config")
            return
        if not ffmpeg_available():
            report.warnings.append("ffmpeg absent: audio transcode skipped (WAV kept)")
            return
        try:
            from mlomega_audio_elite.db import write_transaction  # type: ignore
            from mlomega_audio_elite.utils import json_dumps, json_loads, now_iso  # type: ignore
        except Exception as exc:
            report.warnings.append(f"transcode core utils unavailable: {exc}"[:120])
            return

        with self._connect() as con:
            if not self._table_exists(con, "brainlive_audio_segments_v154"):
                return
            rows = [dict(r) for r in con.execute(
                """SELECT segment_id, source_event_id, chunk_path, source_path,
                          speaker_json
                   FROM brainlive_audio_segments_v154
                   WHERE chunk_path LIKE '%.wav'"""
            ).fetchall()]
            # The original sha lives on the sensor event (segments table has none);
            # index it by source_path so the transcode can preserve it as metadata.
            sha_by_path: dict[str, str] = {}
            if self._table_exists(con, "brainlive_sensor_events"):
                for r in con.execute(
                    """SELECT source_path, source_sha256 FROM brainlive_sensor_events
                       WHERE modality='audio' AND event_type='speech_segment'
                         AND source_path IS NOT NULL"""
                ):
                    if r["source_path"]:
                        sha_by_path[str(r["source_path"])] = r["source_sha256"]

        for r in rows:
            wav = Path(str(r["chunk_path"]))
            if not wav.exists():
                report.transcode_skipped += 1
                continue
            opus = wav.with_suffix(".opus")
            before = _size(wav)
            try:
                proc = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
                     "-c:a", "libopus", "-b:a", "24k", str(opus)],
                    capture_output=True, timeout=120,
                )
            except Exception as exc:
                report.warnings.append(f"ffmpeg failed on {wav.name}: {exc}"[:120])
                report.transcode_skipped += 1
                continue
            if proc.returncode != 0 or not opus.exists() or _size(opus) == 0:
                report.warnings.append(f"ffmpeg no-output on {wav.name}")
                report.transcode_skipped += 1
                try:
                    if opus.exists():
                        opus.unlink()
                except OSError:
                    pass
                continue

            after = _size(opus)
            new_path = str(opus.resolve())
            try:
                meta = json_loads(r.get("speaker_json"), {}) or {}
                if isinstance(meta, dict):
                    meta.setdefault("transcode", {})
                    meta["transcode"] = {
                        "codec": "opus", "original_ext": "wav",
                        "original_sha256": sha_by_path.get(str(wav.resolve())),
                        "original_path": str(wav.resolve()),
                        "at": now_iso(),
                    }
                with self._connect() as con, write_transaction(con):
                    con.execute(
                        """UPDATE brainlive_audio_segments_v154
                           SET chunk_path=?, source_path=?, speaker_json=?
                           WHERE segment_id=?""",
                        (new_path, new_path, json_dumps(meta), r["segment_id"]),
                    )
                    if self._table_exists(con, "brainlive_sensor_events"):
                        con.execute(
                            """UPDATE brainlive_sensor_events
                               SET source_path=?
                               WHERE source_path=? AND modality='audio'
                                 AND event_type='speech_segment'""",
                            (new_path, str(wav.resolve())),
                        )
            except Exception as exc:
                report.warnings.append(f"transcode db repoint failed {wav.name}: {exc}"[:120])
                try:
                    opus.unlink()
                except OSError:
                    pass
                report.transcode_skipped += 1
                continue

            # DB now points at the Opus; safe to drop the WAV.
            try:
                wav.unlink()
            except OSError:
                pass
            report.transcoded += 1
            report.transcode_saved_bytes += max(0, before - after)

    # ------------------------------------------------------------------ purge/budget
    def _age_days(self, item: MediaItem, now: datetime) -> float:
        dt = _parse_iso(item.captured_at)
        if dt is None:
            # Fall back to file mtime; if unknown, treat as brand new (protected).
            try:
                dt = datetime.fromtimestamp(Path(item.path).stat().st_mtime, tz=timezone.utc)
            except OSError:
                return 0.0
        return (now - dt).total_seconds() / 86400.0

    def purge_unreferenced(self, items: list[MediaItem], report: RetentionReport) -> None:
        """Delete unreferenced media older than retention_days. Referenced media
        are NEVER touched."""
        now = _now()
        floor = max(self.config.retention_days, self.config.min_age_days_floor)
        for it in items:
            if it.referenced:
                continue
            if self._age_days(it, now) < floor:
                continue
            freed = self._delete_item(it)
            if freed or not Path(it.path).exists():
                report.purged_aged += 1
                report.purged_aged_bytes += it.size_bytes
                it.size_bytes = 0  # consumed; don't re-count in budget

    def enforce_budget(self, items: list[MediaItem], report: RetentionReport) -> None:
        """If total media usage exceeds total_gb, evict the OLDEST unreferenced
        media first until under budget. Referenced media are never evicted; a
        fully-referenced overshoot deletes nothing and WARNs."""
        live = [it for it in items if it.size_bytes > 0]
        total = sum(it.size_bytes for it in live)
        report.total_bytes = total
        report.referenced_bytes = sum(it.size_bytes for it in live if it.referenced)
        report.unreferenced_bytes = total - report.referenced_bytes
        if total <= self.config.total_bytes:
            if total >= self.config.warn_bytes:
                report.warnings.append(
                    f"media usage {total / 1e9:.1f} GB over warn {self.config.warn_gb} GB"
                )
            return

        now = _now()
        evictable = sorted(
            (it for it in live if not it.referenced),
            key=lambda it: self._age_days(it, now), reverse=True,  # oldest first
        )
        for it in evictable:
            if total <= self.config.total_bytes:
                break
            freed = self._delete_item(it)
            if freed or not Path(it.path).exists():
                report.evicted_budget += 1
                report.evicted_budget_bytes += it.size_bytes
                total -= it.size_bytes
                it.size_bytes = 0

        if total > self.config.total_bytes:
            report.warnings.append(
                f"over budget by {(total - self.config.total_bytes) / 1e9:.1f} GB "
                f"but remaining media is all referenced — nothing deleted (WARN)"
            )
        report.total_bytes = total

    # ------------------------------------------------------------------ entry
    def run(self, *, transcode: bool = True) -> dict[str, Any]:
        """Full retention pass, best-effort. Order: transcode → age-purge → budget.

        Never raises; every failure is a warning. Returns a report dict."""
        report = RetentionReport()
        try:
            if transcode:
                self.transcode_audio_chunks(report)
            items = self.inventory()
            self.purge_unreferenced(items, report)
            self.enforce_budget(items, report)
        except Exception as exc:  # pragma: no cover - top-level guard
            report.warnings.append(f"retention aborted: {exc}"[:160])
        return report.to_dict()


def load_retention_config(profile_path: str | Path | None = None) -> RetentionConfig:
    """Build a RetentionConfig from a profile's ``storage_quota:`` block.

    Reads ``configs/profiles/rtx3070.yaml`` by default (the VisionRT profile), then
    falls back to coded defaults for any missing key — same keys the DOCTOR
    ``-Quota`` check reads."""
    cfg = RetentionConfig()
    path = Path(profile_path) if profile_path else (_ROOT / "configs" / "profiles" / "rtx3070.yaml")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sq = (data.get("storage_quota") or {}) if isinstance(data, dict) else {}
        if isinstance(sq, dict):
            cfg.total_gb = float(sq.get("total_gb", cfg.total_gb))
            cfg.warn_gb = float(sq.get("warn_gb", cfg.warn_gb))
            cfg.retention_days = int(sq.get("retention_days", cfg.retention_days))
            cfg.transcode_audio = bool(sq.get("transcode_audio", cfg.transcode_audio))
    except Exception:
        pass
    return cfg


def run_media_retention(
    *, person_id: str, db_path: Any = None, profile_path: str | Path | None = None,
) -> dict[str, Any]:
    """Best-effort convenience entry for the close-day wiring. Never raises."""
    try:
        cfg = load_retention_config(profile_path)
        return MediaRetention(person_id=person_id, config=cfg, db_path=db_path).run()
    except Exception as exc:  # pragma: no cover - top-level guard
        return {"status": "error", "error": str(exc)[:160], "warnings": []}
