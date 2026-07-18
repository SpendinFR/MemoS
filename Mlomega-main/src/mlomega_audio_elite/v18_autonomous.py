"""V18 autonomous insights: scoped candidate queue, never immediate canonical mutation."""
from __future__ import annotations
import os
from typing import Any

from .db import connect, insert_only, write_transaction
from .governance_v18 import conversation_in_scope, strict_one
from .utils import json_dumps, now_iso, stable_id

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS v18_autonomous_candidate_runs(
  run_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  status TEXT NOT NULL,
  output_json TEXT NOT NULL DEFAULT '{}',
  error_text TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS v18_autonomous_candidates(
  candidate_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  candidate_type TEXT NOT NULL,
  title TEXT,
  summary TEXT,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  counter_evidence_json TEXT NOT NULL DEFAULT '[]',
  confidence REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate',
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v18_autonomous_candidate_owner ON v18_autonomous_candidates(person_id,status,created_at);
"""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _compiled_autonomous_enabled() -> bool:
    return os.environ.get("MLOMEGA_E64_AUTONOMOUS_COMPILER", "1") != "0"


def _compile_strict_autonomous_candidates(
    con: Any, *, conversation_id: str, person_id: str,
) -> dict[str, Any] | None:
    """Reuse validated strict-engine semantics instead of asking a second LLM.

    ``None`` means the strict fact run is not complete and authorizes the legacy
    fallback.  A complete-but-empty run is an honest valid-empty result.
    """
    try:
        complete = con.execute(
            """SELECT 1 FROM brain2_shared_fact_runs_v19
               WHERE conversation_id=? AND status='complete' LIMIT 1""",
            (conversation_id,),
        ).fetchone()
    except Exception:
        return None
    if not complete:
        return None

    from .utils import json_loads

    try:
        rows = con.execute(
            """SELECT r.engine_name,r.episode_id,o.output_json,o.evidence_json,
                      o.counter_evidence_json,o.confidence
               FROM v13_engine_runs r
               JOIN v13_engine_outputs o ON o.engine_run_id=r.engine_run_id
               WHERE r.conversation_id=? AND r.person_id=?
                 AND r.status IN ('ok','completed')
                 AND o.validation_status='valid'
               ORDER BY r.finished_at,r.engine_run_id,o.output_id""",
            (conversation_id, person_id),
        ).fetchall()
    except Exception:
        return None
    insights: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        *, engine: str, field: str, item: dict[str, Any], insight_type: str,
        title: Any, summary: Any, episode_id: Any,
        default_evidence: Any, default_counter: Any, default_confidence: Any,
        prediction_target: str = "none", predicted_value: Any = "",
        probability: Any = None, intervention: Any = "",
        watch_for: Any = None, verification_question: Any = "",
    ) -> None:
        title_text = str(title or summary or field).strip()[:300]
        summary_text = str(summary or title_text).strip()[:4000]
        marker = stable_id(
            "compiled-autonomous", conversation_id, engine, field,
            insight_type, title_text, summary_text,
        )
        if marker in seen:
            return
        seen.add(marker)
        confidence = _clamp(item.get("confidence", default_confidence))
        probability_value = _clamp(
            probability if probability is not None else confidence
        )
        risk = _clamp(item.get("risk_level"))
        score = max(confidence, probability_value, risk)
        evidence = _as_list(item.get("why") or item.get("evidence") or default_evidence)
        if not evidence:
            evidence = [{
                "source_engine": engine,
                "source_field": field,
                "source_digest": stable_id(
                    "strict-output-ref", conversation_id, engine, field,
                    json_dumps(item),
                ),
            }]
        insights.append({
            "insight_type": insight_type,
            "priority": (
                "critical" if score >= 0.9 else "high" if score >= 0.7
                else "medium" if score >= 0.4 else "low"
            ),
            "person_id": person_id,
            "episode_id": episode_id,
            "title": title_text,
            "summary": summary_text,
            "prediction_target": prediction_target,
            "predicted_value": str(predicted_value or ""),
            "probability": probability_value,
            "confidence": confidence,
            "why": evidence,
            "similar_cases": _as_list(item.get("similar_cases")),
            "counter_evidence": _as_list(
                item.get("counter_evidence") or default_counter
            ),
            "assumptions": _as_list(item.get("assumptions")),
            "intervention": str(intervention or ""),
            "watch_for": _as_list(watch_for),
            "verification_question": str(verification_question or ""),
        })

    for row in rows:
        engine = str(row["engine_name"])
        output = json_loads(row["output_json"], {})
        if not isinstance(output, dict):
            continue
        defaults = {
            "engine": engine,
            "episode_id": row["episode_id"],
            "default_evidence": output.get("evidence")
            or json_loads(row["evidence_json"], []),
            "default_counter": output.get("counter_evidence")
            or json_loads(row["counter_evidence_json"], []),
            "default_confidence": output.get("confidence", row["confidence"]),
        }
        if engine == "pattern_miner":
            for field in ("candidate_patterns", "confirmed_patterns"):
                for item in _as_list(output.get(field)):
                    if not isinstance(item, dict):
                        continue
                    kind = str(item.get("pattern_type") or "pattern")
                    add(
                        field=field, item=item,
                        insight_type=("loop_risk" if any(
                            token in kind.lower() for token in ("loop", "risk", "conflict")
                        ) else "hypothesis"),
                        title=item.get("title") or item.get("pattern_key") or kind,
                        summary=item.get("description") or item.get("title")
                        or item.get("pattern_key") or kind,
                        watch_for=item.get("activation_contexts"), **defaults,
                    )
        elif engine == "prediction_engine":
            for item in _as_list(output.get("predictions")):
                if not isinstance(item, dict):
                    continue
                target = str(item.get("prediction_target") or "next_action")
                value = str(item.get("predicted_value") or "")
                add(
                    field="predictions", item=item, insight_type="prediction",
                    title=f"Prédiction {target}: {value}", summary=value,
                    prediction_target=target, predicted_value=value,
                    probability=item.get("probability"),
                    intervention="; ".join(
                        str(value) for value in _as_list(item.get("interventions"))
                    ),
                    watch_for=item.get("verification_plan"), **defaults,
                )
        elif engine == "simulation_engine":
            for field in ("branches", "future_scenarios"):
                for item in _as_list(output.get(field)):
                    if not isinstance(item, dict):
                        continue
                    summary = item.get("summary") or item.get("expected_path") or item.get("path")
                    add(
                        field=field, item=item,
                        insight_type=(
                            "warning" if _clamp(item.get("risk_level")) >= 0.5
                            else "hypothesis"
                        ),
                        title=item.get("branch_name") or item.get("scenario_type") or "Scénario",
                        summary=summary or "Scénario à surveiller",
                        prediction_target="next_trajectory",
                        predicted_value=summary or "",
                        probability=item.get("probability"),
                        intervention=item.get("recommended_intervention"),
                        watch_for=item.get("if_condition"), **defaults,
                    )
        elif engine == "outcome_tracker":
            for item in _as_list(output.get("open_loops")):
                if isinstance(item, dict):
                    question = item.get("what_would_close_it") or ""
                    add(
                        field="open_loops", item=item,
                        insight_type="question_to_user",
                        title=item.get("item") or "Boucle ouverte",
                        summary=item.get("risk_if_unclosed") or item.get("item")
                        or "Boucle ouverte",
                        watch_for=question, verification_question=question, **defaults,
                    )
        elif engine == "social_model_engine":
            for item in _as_list(output.get("conflict_loops")):
                if isinstance(item, dict):
                    add(
                        field="conflict_loops", item=item, insight_type="loop_risk",
                        title=item.get("summary") or "Boucle interpersonnelle",
                        summary=item.get("escalation_path") or item.get("summary")
                        or "Boucle interpersonnelle",
                        intervention=item.get("deescalation_path"),
                        watch_for=item.get("trigger_pattern"), **defaults,
                    )
        elif engine == "causality_engine":
            for item in _as_list(output.get("causal_hypotheses")):
                if isinstance(item, dict):
                    add(
                        field="causal_hypotheses", item=item,
                        insight_type="hypothesis",
                        title=item.get("hypothesis") or "Hypothèse causale",
                        summary=item.get("hypothesis") or (
                            f"{item.get('cause') or ''} → {item.get('effect') or ''}"
                        ), **defaults,
                    )
        elif engine == "contradiction_engine":
            for item in _as_list(output.get("contradictions")):
                if isinstance(item, dict):
                    add(
                        field="contradictions", item=item, insight_type="warning",
                        title=item.get("contradiction_type") or "Contradiction à vérifier",
                        summary=item.get("possible_explanation") or (
                            f"{item.get('declared') or ''} / {item.get('observed') or ''}"
                        ),
                        probability=item.get("severity"),
                        verification_question="Quelle interprétation est correcte ?",
                        **defaults,
                    )
        elif engine == "intervention_engine":
            for item in _as_list(output.get("trajectory_warnings")):
                if isinstance(item, dict):
                    add(
                        field="trajectory_warnings", item=item, insight_type="warning",
                        title=item.get("warning_type") or "Risque de trajectoire",
                        summary=item.get("summary") or "Risque de trajectoire",
                        probability=item.get("risk_level"), **defaults,
                    )
            for item in _as_list(output.get("interventions")):
                if isinstance(item, dict):
                    add(
                        field="interventions", item=item, insight_type="intervention",
                        title=item.get("goal") or "Intervention candidate",
                        summary=item.get("desired_path") or item.get("goal")
                        or "Intervention candidate",
                        intervention="; ".join(
                            str(value) for value in _as_list(item.get("actions"))
                        ),
                        watch_for=item.get("verification_plan"), **defaults,
                    )

    confidences = [_clamp(item.get("confidence")) for item in insights]
    return {
        "insights": insights,
        "global_summary": (
            f"{len(insights)} candidat(s) compilé(s) depuis les sorties Brain2 "
            "strictes validées; aucune réanalyse brute."
        ),
        "missing_context": [],
        "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "compiler": "strict_engine_outputs_v1",
    }


def install_autonomous(module: Any) -> dict[str, Any]:
    # Preserve the legacy schema initializer.  The legacy module has no public
    # ``SCHEMA`` constant, so replaying a guessed script was a broken bridge.
    old_ensure_autonomous_schema = module.ensure_autonomous_schema

    def ensure_autonomous_schema() -> None:
        old_ensure_autonomous_schema()
        with connect() as con,write_transaction(con):
            con.executescript(SCHEMA)

    def run_autonomous_insights(conversation_id: str, *, person_id: str, trigger_type: str = "post_ingest") -> dict[str,Any]:
        if not person_id: raise ValueError("V18 autonomous insights requires explicit person_id")
        ensure_autonomous_schema()
        compiled = None
        with connect() as con:
            if not conversation_in_scope(con,conversation_id=conversation_id,person_id=person_id):
                raise ValueError("conversation is not proven in supplied person scope")
            if _compiled_autonomous_enabled():
                compiled = _compile_strict_autonomous_candidates(
                    con, conversation_id=conversation_id, person_id=person_id,
                )
            bundle = (
                None if compiled is not None
                else module._bundle_for_autonomy(con,conversation_id,person_id)
            )
        run_id=stable_id("v18autonrun",conversation_id,person_id,trigger_type,now_iso())
        try:
            out = compiled if compiled is not None else module._llm_json(
                "Tu es un générateur de candidats autonomes V18. JSON strict. Les sorties sont des hypothèses candidates, jamais des vérités ni des mutations automatiques.",
                {"mission":"Proposer des hypothèses/predictions/interventions candidates. Citer des preuves et contre-preuves. Aucune mise à jour de mémoire canonique.","bundle":bundle,"schema":module.INSIGHT_SCHEMA},
                module.INSIGHT_SCHEMA,
                stage_context={
                    "stage_name":"v18_autonomous_candidates",
                    "person_id":person_id,
                    "package_date":now_iso()[:10],
                    "source_ref":conversation_id,
                },
            )
            status="ok"; error=None
        except Exception as exc:
            out={"insights":[]}; status="error"; error=str(exc)[:2000]
        created=[]
        with connect() as con,write_transaction(con):
            insert_only(con,"v18_autonomous_candidate_runs",{"run_id":run_id,"conversation_id":conversation_id,"person_id":person_id,"trigger_type":trigger_type,"status":status,"output_json":json_dumps(out),"error_text":error,"created_at":now_iso()},on_conflict="ignore")
            if status=="ok":
                for index,item in enumerate(out.get("insights") or []):
                    if not isinstance(item,dict):continue
                    evidence=item.get("why") or item.get("evidence") or []
                    if isinstance(evidence,str): evidence=[evidence]
                    counter=item.get("counter_evidence") or []
                    if isinstance(counter,str): counter=[counter]
                    cid=stable_id("v18autoncandidate",run_id,index,item.get("title"),item.get("summary"))
                    insert_only(con,"v18_autonomous_candidates",{
                        "candidate_id":cid,"run_id":run_id,"conversation_id":conversation_id,"person_id":person_id,
                        "candidate_type":str(item.get("insight_type") or "hypothesis"),"title":str(item.get("title") or item.get("summary") or "Autonomous candidate")[:300],
                        "summary":str(item.get("summary") or "")[:4000],"evidence_json":json_dumps(evidence),"counter_evidence_json":json_dumps(counter),
                        "confidence":max(0.0,min(1.0,float(item.get("confidence") or 0.0))),"status":"candidate","raw_json":json_dumps(item),"created_at":now_iso(),"updated_at":now_iso(),
                    },on_conflict="ignore")
                    created.append(cid)
        return {"version":"18.0.0-autonomous-candidates","run_id":run_id,"conversation_id":conversation_id,"person_id":person_id,"status":status,"candidate_ids":created,"error":error}
    return {"ensure_autonomous_schema":ensure_autonomous_schema,"run_autonomous_insights":run_autonomous_insights}


def install_behavior(module: Any) -> dict[str,Any]:
    old_build=module.build_v13_for_conversation
    old_all=module.build_v13_all
    def build_v13_for_conversation(conversation_id: str, *, require_llm: bool|None=None, max_episodes:int|None=None, person_id:str|None=None, run_extensions:bool=True)->dict[str,Any]:
        if not person_id: raise ValueError("V18 V13 build requires explicit person_id")
        # Core strict build validates scope. Extensions are re-run explicitly,
        # avoiding old default-user autonomous writes.
        core=old_build(conversation_id,require_llm=require_llm,max_episodes=max_episodes,person_id=person_id,run_extensions=False)
        if not run_extensions:return core
        from .brain2_flow_v13_3 import build_subtopic_segments,discover_latent_outcomes_from_conversation
        from .autonomous_v13_4 import run_autonomous_insights
        return {**core,
                "v13_3_subtopics":build_subtopic_segments(conversation_id),
                "v13_3_latent_outcomes":discover_latent_outcomes_from_conversation(conversation_id,person_id=person_id),
                "v13_4_autonomous_candidates":run_autonomous_insights(conversation_id,person_id=person_id,trigger_type="post_v13_build")}
    def build_v13_all(*,require_llm:bool|None=None,max_episodes_per_conversation:int|None=None)->dict[str,Any]:
        # Original all-mode used every conversation with a hidden default owner.
        with connect() as con:
            rows=con.execute("SELECT conversation_id,person_id FROM v18_conversation_scopes WHERE active=1 ORDER BY conversation_id,person_id").fetchall()
        grouped:dict[str,set[str]]={}
        for r in rows: grouped.setdefault(str(r['conversation_id']),set()).add(str(r['person_id']))
        results=[];skipped=[]
        for cid,owners in grouped.items():
            if len(owners)!=1:skipped.append({"conversation_id":cid,"reason":"ambiguous_owner"});continue
            results.append(build_v13_for_conversation(cid,require_llm=require_llm,max_episodes=max_episodes_per_conversation,person_id=next(iter(owners))))
        return {"version":"18.0.0-v13-batch","results":results,"skipped":skipped,"conversations":len(results)}
    return {"build_v13_for_conversation":build_v13_for_conversation,"build_v13_all":build_v13_all}
