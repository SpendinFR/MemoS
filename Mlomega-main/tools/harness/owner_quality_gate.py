from __future__ import annotations

"""Owner-perspective quality gate on an isolated clone of a Gate B database."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _clone_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _insert_row(con: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = list(row)
    marks = ",".join("?" for _ in columns)
    con.execute(
        f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",
        tuple(row[column] for column in columns),
    )


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_conversation(con: sqlite3.Connection, truth: dict[str, Any]) -> str:
    prefix = str(truth.get("source_conversation_prefix") or "")
    rows = con.execute(
        """SELECT c.conversation_id,COUNT(t.turn_id) AS n
           FROM conversations c JOIN turns t ON t.conversation_id=c.conversation_id
           GROUP BY c.conversation_id ORDER BY n DESC"""
    ).fetchall()
    for row in rows:
        if not prefix or str(row[0]).startswith(prefix):
            return str(row[0])
    raise RuntimeError("aucune conversation source compatible avec la vérité")


def _role_for_index(index: int, truth: dict[str, Any]) -> tuple[str, str | None]:
    if index in {int(v) for v in truth.get("owner_turn_indices") or []}:
        return "owner", None
    if index in {int(v) for v in truth.get("mixed_unknown_turn_indices") or []}:
        return "mixed_unknown", None
    for person_id, values in (truth.get("other_turns") or {}).items():
        if index in {int(v) for v in values or []}:
            return "other", str(person_id)
    return "unknown", None


def _materialize_quality_conversation(
    con: sqlite3.Connection, *, truth: dict[str, Any], owner_id: str, owner_name: str
) -> dict[str, Any]:
    con.row_factory = sqlite3.Row
    source_id = _source_conversation(con, truth)
    digest = hashlib.sha256((source_id + truth["version"]).encode()).hexdigest()[:16]
    quality_id = f"owner_quality_{digest}"

    source = dict(con.execute(
        "SELECT * FROM conversations WHERE conversation_id=?", (source_id,)
    ).fetchone())
    source["conversation_id"] = quality_id
    if "participants_json" in source:
        source["participants_json"] = _dump([
            {"person_id": owner_id, "display_name": owner_name, "role": "owner"},
            *[
                {"person_id": pid, "display_name": name, "role": "other"}
                for pid, name in (truth.get("people") or {}).items()
            ],
        ])
    if "speaker_map_json" in source:
        source["speaker_map_json"] = _dump({
            "policy": "turn_level_quality_truth",
            "reason": "source diarization clusters are mixed/split",
        })
    _insert_row(con, "conversations", source)

    source_turns = con.execute(
        "SELECT * FROM turns WHERE conversation_id=? ORDER BY idx", (source_id,)
    ).fetchall()
    copied = {"owner": 0, "other": 0, "unknown": 0, "mixed_unknown": 0}
    quality_turn_ids: list[str] = []
    next_index = 0
    for raw in source_turns:
        row = dict(raw)
        metadata = _json_object(row.get("metadata_json"))
        if str(row.get("speaker_label") or "").startswith("context_") or str(
            metadata.get("evidence_role") or ""
        ) == "system_observation_not_user_speech":
            continue
        source_index = int(row.get("idx") or 0)
        role, other_id = _role_for_index(source_index, truth)
        if role == "owner":
            row["person_id"] = owner_id
        elif role == "other":
            row["person_id"] = other_id
        else:
            row["person_id"] = None
        source_turn_id = str(row["turn_id"])
        row["turn_id"] = "oqturn_" + hashlib.sha256(
            (quality_id + source_turn_id).encode()
        ).hexdigest()[:16]
        row["conversation_id"] = quality_id
        row["idx"] = next_index
        next_index += 1
        metadata["owner_quality_truth"] = {
            "version": truth["version"], "role": role,
            "source_turn_id": source_turn_id, "source_idx": source_index,
        }
        row["metadata_json"] = _dump(metadata)
        _insert_row(con, "turns", row)
        quality_turn_ids.append(str(row["turn_id"]))
        copied[role] += 1

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    con.execute(
        """INSERT INTO self_voice_profile(person_id,display_name,is_user,setup_status,created_at,updated_at)
           VALUES(?,?,1,'quality_fixture',?,?)
           ON CONFLICT(person_id) DO UPDATE SET display_name=excluded.display_name,
             is_user=1,setup_status='quality_fixture',updated_at=excluded.updated_at""",
        (owner_id, owner_name, now, now),
    )
    profiles = {owner_id: owner_name, **(truth.get("people") or {})}
    for person_id, display_name in profiles.items():
        con.execute(
            """INSERT INTO speaker_profiles(person_id,display_name,is_user,aliases_json,notes,created_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(person_id) DO UPDATE SET
               display_name=excluded.display_name,is_user=excluded.is_user,
               aliases_json=excluded.aliases_json""",
            (
                person_id, display_name, 1 if person_id == owner_id else 0,
                _dump([display_name]), "owner_quality_truth_fixture", now,
            ),
        )
    con.commit()
    return {
        "source_conversation_id": source_id,
        "quality_conversation_id": quality_id,
        "turn_counts": copied,
        "quality_turn_ids": quality_turn_ids,
    }


def _reset_clone_llm_checkpoints(con: sqlite3.Connection) -> list[str]:
    """Prevent source-run outputs from masquerading as owner-aware inference."""
    tables = {
        str(row[0]) for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    cleared: list[str] = []
    for table in (
        "night_llm_contract_rejections_v19",
        "night_llm_window_outputs_v19",
        "night_llm_coverage_v19",
        "night_llm_call_telemetry_v19",
        "night_llm_windows_v19",
    ):
        if table in tables:
            con.execute(f"DELETE FROM {table}")
            cleared.append(table)
    con.commit()
    return cleared


def _count(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _audit(
    con: sqlite3.Connection, *, quality_id: str, owner_id: str,
    truth: dict[str, Any], baseline: dict[str, int], stack_result: dict[str, Any],
) -> dict[str, Any]:
    con.row_factory = sqlite3.Row
    from mlomega_audio_elite.brain2_shared_facts_v19 import compact_stage_input

    projection = compact_stage_input(
        con, quality_id, person_id=owner_id, purpose="pattern_mirror"
    )
    roles = [str(turn.get("perspective_role") or "unknown") for turn in projection["turns"]]
    episodes = [dict(row) for row in con.execute(
        "SELECT episode_id,episode_type,topic,situation_summary,confidence FROM episodes WHERE source_conversation_id=?",
        (quality_id,),
    )]
    episode_ids = [str(row["episode_id"]) for row in episodes]
    subthemes: list[dict[str, Any]] = []
    if episode_ids:
        marks = ",".join("?" for _ in episode_ids)
        subthemes = [dict(row) for row in con.execute(
            f"SELECT subtheme_id,episode_id,ordinal,title,summary FROM episode_subthemes_v19 WHERE episode_id IN ({marks}) ORDER BY ordinal",
            tuple(episode_ids),
        )]
    topic_hits: list[list[str]] = []
    for group in truth.get("expected_separate_topics") or []:
        hits = []
        for row in subthemes:
            text = f"{row.get('title') or ''} {row.get('summary') or ''}".casefold()
            if any(str(term).casefold() in text for term in group):
                hits.append(str(row["subtheme_id"]))
        topic_hits.append(hits)
    topics_separate = bool(topic_hits) and all(topic_hits) and not any(
        set(topic_hits[i]) & set(topic_hits[j])
        for i in range(len(topic_hits)) for j in range(i + 1, len(topic_hits))
    )

    turn_id_map = projection.get("_turn_id_map") or {}
    speech_ids = {
        str(turn_id_map.get(str(turn["turn_id"]), turn["turn_id"]))
        for turn in projection["turns"]
    }
    covered: set[str] = set()
    if episode_ids:
        marks = ",".join("?" for _ in episode_ids)
        covered = {
            str(row[0]) for row in con.execute(
                f"""SELECT DISTINCT e.turn_id FROM episode_subtheme_evidence_v19 e
                    JOIN episode_subthemes_v19 s ON s.subtheme_id=e.subtheme_id
                    WHERE s.episode_id IN ({marks})""", tuple(episode_ids)
            )
        }
    facts = [dict(row) for row in con.execute(
        "SELECT fact_id,subject_ref,source_engine,fact_type,evidence_status,epistemic_status,payload_digest FROM brain2_shared_facts_v19 WHERE conversation_id=?",
        (quality_id,),
    )]
    fact_ids = [str(row["fact_id"]) for row in facts]
    cited_fact_ids: set[str] = set()
    if fact_ids:
        marks = ",".join("?" for _ in fact_ids)
        cited_fact_ids = {
            str(row[0]) for row in con.execute(
                f"SELECT DISTINCT fact_id FROM brain2_shared_fact_evidence_v19 WHERE fact_id IN ({marks})",
                tuple(fact_ids),
            )
        }
    duplicate_payloads = [dict(row) for row in con.execute(
        """SELECT payload_digest,COUNT(*) AS duplicate_count
           FROM brain2_shared_facts_v19 WHERE conversation_id=?
           GROUP BY payload_digest HAVING COUNT(*)>1""",
        (quality_id,),
    )]
    cited_cognitive_engines = sorted({
        str(fact.get("source_engine")) for fact in facts
        if fact["fact_id"] in cited_fact_ids
        and fact.get("source_engine") not in {"episode_builder", "capture_engine"}
    })
    required_cognitive_engines = {
        str(engine) for engine in truth.get("required_cited_cognitive_engines") or []
    }
    unsupported_owner_claims = []
    for fact in facts:
        if str(fact.get("subject_ref") or "").casefold() not in {
            owner_id.casefold(), "me", "user", "utilisateur", "owner", "self",
        }:
            continue
        cited_people = [
            row[0] for row in con.execute(
                """SELECT t.person_id FROM brain2_shared_fact_evidence_v19 e
                   JOIN turns t ON t.turn_id=e.turn_id WHERE e.fact_id=?""",
                (fact["fact_id"],),
            )
        ]
        if owner_id not in cited_people:
            unsupported_owner_claims.append(fact["fact_id"])

    confirmed_delta = _count(con, "confirmed_patterns") - baseline["confirmed_patterns"]
    predictions_delta = _count(con, "predictions") - baseline["predictions"]
    checks = {
        "owner_context": projection.get("owner_context", {}).get("person_id") == owner_id,
        "owner_turns": roles.count("owner") >= int(truth.get("minimum_owner_turns") or 1),
        "other_turns": roles.count("other") >= int(truth.get("minimum_other_turns") or 1),
        "one_parent": len(episodes) == 1 and episodes[0].get("episode_type") == "conversation",
        "speech_coverage_100": bool(speech_ids) and speech_ids <= covered,
        "topics_separate": topics_separate,
        "owner_claims_cited_by_owner": not unsupported_owner_claims,
        "all_canonical_facts_cited": set(fact_ids) <= cited_fact_ids,
        "no_exact_duplicate_canonical_facts": not duplicate_payloads,
        "required_cognitive_layers_cited": required_cognitive_engines <= set(cited_cognitive_engines),
        "no_single_session_confirmed_pattern": confirmed_delta <= int(truth.get("maximum_confirmed_patterns_delta") or 0),
        "no_prediction_without_precedents": predictions_delta <= int(truth.get("maximum_predictions_without_precedents_delta") or 0),
    }
    return {
        "go": all(checks.values()),
        "checks": checks,
        "owner_context": projection.get("owner_context"),
        "perspective_counts": {role: roles.count(role) for role in sorted(set(roles))},
        "episodes": episodes,
        "subthemes": subthemes,
        "topic_hits": topic_hits,
        "speech_turns": len(speech_ids),
        "covered_speech_turns": len(speech_ids & covered),
        "facts": len(facts),
        "cited_facts": len(cited_fact_ids),
        "duplicate_canonical_payloads": duplicate_payloads,
        "cited_cognitive_engines": cited_cognitive_engines,
        "required_cited_cognitive_engines": sorted(required_cognitive_engines),
        "unsupported_owner_claims": unsupported_owner_claims,
        "confirmed_patterns_delta": confirmed_delta,
        "predictions_delta": predictions_delta,
        "stack_status": stack_result.get("status"),
        "stack_warnings": stack_result.get("warnings") or [],
    }


def _replay_fact_writers(
    clone: Path, *, previous_report: dict[str, Any], truth: dict[str, Any],
    owner_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """Re-evaluate durable writers over real saved model outputs, with no LLM."""

    fixture = dict(previous_report["fixture"])
    quality_id = str(fixture["quality_conversation_id"])
    previous_audit = previous_report.get("audit") or {}
    with sqlite3.connect(clone) as con:
        con.row_factory = sqlite3.Row
        baseline = {
            "confirmed_patterns": _count(con, "confirmed_patterns")
            - int(previous_audit.get("confirmed_patterns_delta") or 0),
            "predictions": _count(con, "predictions")
            - int(previous_audit.get("predictions_delta") or 0),
        }
        sections = [dict(row) for row in con.execute(
            """SELECT episode_id,engine_name,applies,applicability_reason,output_json
               FROM brain2_shared_engine_sections_v19 WHERE conversation_id=?
               ORDER BY CASE WHEN engine_name='episode_builder' THEN 0 ELSE 1 END,
                        engine_name""",
            (quality_id,),
        )]
        fact_ids = [str(row[0]) for row in con.execute(
            "SELECT fact_id FROM brain2_shared_facts_v19 WHERE conversation_id=?",
            (quality_id,),
        )]
        if fact_ids:
            marks = ",".join("?" for _ in fact_ids)
            con.execute(
                f"DELETE FROM brain2_shared_fact_evidence_v19 WHERE fact_id IN ({marks})",
                tuple(fact_ids),
            )
        for table in (
            "brain2_shared_facts_v19", "brain2_shared_capabilities_v19",
            "brain2_shared_engine_sections_v19", "brain2_shared_fact_runs_v19",
        ):
            con.execute(f"DELETE FROM {table} WHERE conversation_id=?", (quality_id,))

        from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
        from mlomega_audio_elite.brain2_shared_facts_v19 import (
            finish_episode_fact_run, record_engine_not_applicable,
            record_engine_output, record_episode_structure,
        )
        episode_ids = sorted({str(row["episode_id"]) for row in sections})
        for episode_id in episode_ids:
            record_episode_structure(
                con, person_id=owner_id, conversation_id=quality_id,
                episode_id=episode_id,
            )
        for section in sections:
            engine = str(section["engine_name"])
            if engine == "episode_builder":
                continue
            schema = ENGINE_SCHEMAS[engine]
            kwargs = {
                "person_id": owner_id, "conversation_id": quality_id,
                "episode_id": str(section["episode_id"]), "engine_name": engine,
                "schema": schema,
            }
            if int(section["applies"] or 0):
                record_engine_output(
                    con, output=_json_object(section["output_json"]),
                    applicability_reason=str(section["applicability_reason"] or "writer_replay"),
                    **kwargs,
                )
            else:
                record_engine_not_applicable(
                    con, reason=str(section["applicability_reason"] or "not_applicable"),
                    **kwargs,
                )
        for episode_id in episode_ids:
            finish_episode_fact_run(
                con, conversation_id=quality_id, episode_id=episode_id,
            )
        con.commit()
        audit = _audit(
            con, quality_id=quality_id, owner_id=owner_id, truth=truth,
            baseline=baseline,
            stack_result={"status": "writer_replay_no_llm", "warnings": []},
        )
    fixture["writer_replay_source_report"] = previous_report.get("clone_db")
    return fixture, audit, baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--owner-name", required=True)
    parser.add_argument("--truth", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--replay-report",
        help="Replay only durable writers from this previous real-gate report; no LLM.",
    )
    args = parser.parse_args()

    source = Path(args.db).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    clone = output.with_suffix(".db")
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    _clone_database(source, clone)
    os.environ["MLOMEGA_DB"] = str(clone)

    if args.replay_report:
        previous = json.loads(Path(args.replay_report).read_text(encoding="utf-8"))
        fixture, audit, _baseline = _replay_fact_writers(
            clone, previous_report=previous, truth=truth, owner_id=args.owner_id,
        )
        report = {
            "version": "owner-quality-gate-v1-writer-replay",
            "source_db": str(source), "clone_db": str(clone),
            "truth": truth["version"], "fixture": fixture, "audit": audit,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "out": str(output), "clone": str(clone), "go": audit["go"],
            "mode": "writer_replay_no_llm",
        }, ensure_ascii=False))
        return 0 if audit["go"] else 2

    with sqlite3.connect(clone) as con:
        baseline = {
            "confirmed_patterns": _count(con, "confirmed_patterns"),
            "predictions": _count(con, "predictions"),
        }
        fixture = _materialize_quality_conversation(
            con, truth=truth, owner_id=args.owner_id, owner_name=args.owner_name
        )
        fixture["cleared_clone_checkpoint_tables"] = _reset_clone_llm_checkpoints(con)

    from mlomega_audio_elite.gpu_phase_orchestrator import GpuPhaseOrchestrator
    from mlomega_audio_elite.brain2_flow_v13_3 import run_brain2_deep_stack_for_conversation

    gpu = GpuPhaseOrchestrator()
    gpu.enter_text()
    try:
        stack = run_brain2_deep_stack_for_conversation(
            fixture["quality_conversation_id"], person_id=args.owner_id,
            trigger_type="owner_quality_gate", run_v13=True, run_v15_after=False,
            run_periodic_export=False, use_llm=True,
        )
    finally:
        gpu.stop_p1()
    with sqlite3.connect(clone) as con:
        audit = _audit(
            con, quality_id=fixture["quality_conversation_id"],
            owner_id=args.owner_id, truth=truth, baseline=baseline,
            stack_result=stack,
        )
    report = {
        "version": "owner-quality-gate-v1", "source_db": str(source),
        "clone_db": str(clone), "truth": truth["version"],
        "fixture": fixture, "audit": audit,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(output), "clone": str(clone), "go": audit["go"]}, ensure_ascii=False))
    return 0 if audit["go"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
