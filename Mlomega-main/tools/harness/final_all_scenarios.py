from __future__ import annotations

"""E64 final 3BIS: synthetic two-day product-path scenario gate.

This is not a table-count smoke test. It seeds a fresh memory, calls the real
MemoryQuery/IntentRouter/WorldBrain/BrainLive delivery boundaries, serialises the
actual UIIntent payloads and persists a UI receipt.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mlomega_audio_elite.db import init_db
from mlomega_audio_elite.v19_prediction_loop import ensure_prediction_schema
from mlomega_audio_elite.v19_visual_store import ensure_v19_visual_schema
from mlomega_audio_elite.brainlive_v15 import ensure_brainlive_schema
from mlomega_audio_elite.interpersonal_state_v14_6 import ensure_v14_6_schema
from mlomega_audio_elite.proactive_interventions_v14_7 import ensure_v14_7_schema
from mlomega_audio_elite.brainlive_offline_deep_vision_v16_1 import (
    ensure_deep_vision_schema,
)
from packages.contracts.python.models import UIIntent, UIReceipt


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


memory_query_mod = _load("final_memory_query", "services/live-pc/memory_query.py")
intent_router_mod = _load("final_intent_router", "services/live-pc/intent_router.py")
worldbrain_mod = _load("final_worldbrain", "services/live-pc/worldbrain.py")
spatial_mod = _load("final_spatial", "services/live-pc/spatial.py")
replay_mod = _load("final_replay", "services/live-pc/replay_service.py")
delivery_mod = _load("final_delivery", "services/live-pc/delivery_adapter.py")
scene_adapter_mod = _load(
    "final_scene_adapter", "services/live-pc/brainlive_scene_adapter.py"
)
attribute_mod = _load("final_attribute", "services/live-pc/attribute_memory.py")
change_attention_mod = _load(
    "final_change_attention", "services/live-pc/change_attention.py"
)
proactive_mod = _load("final_proactive", "services/live-pc/proactive_context.py")
identity_mod = _load("final_identity", "services/live-pc/identity_fusion.py")
help_mod = _load("final_help", "services/live-pc/help_mode.py")


NOW = "2026-07-23T10:00:00+00:00"


def _insert(con: sqlite3.Connection, table: str, **row: Any) -> None:
    names = list(row)
    con.execute(
        f"INSERT INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",
        tuple(row[name] for name in names),
    )


def seed_fixture(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    ensure_v19_visual_schema(db_path)
    ensure_prediction_schema(db_path)
    os.environ["MLOMEGA_DB"] = str(db_path)
    ensure_brainlive_schema()
    ensure_v14_6_schema()
    ensure_v14_7_schema()
    ensure_deep_vision_schema()
    attribute_mod.AttributeMemory(service_db_path=db_path)

    with sqlite3.connect(db_path) as con:
        for pid, name, is_user in (
            ("me", "William", 1),
            ("karim", "Karim", 0),
            ("maxime", "Maxime", 0),
            ("sarah", "Sarah", 0),
        ):
            _insert(
                con, "speaker_profiles", person_id=pid, display_name=name,
                is_user=is_user, aliases_json=json.dumps([name]), notes="fixture",
                created_at=NOW,
            )

        conversations = [
            ("conv-karim", "Dernière discussion Karim", "2026-07-20T18:00:00+00:00",
             "2026-07-20T18:30:00+00:00", "projet voyage", ["me", "karim"]),
            ("conv-max-1", "Atlas initial", "2026-06-10T12:00:00+00:00",
             "2026-06-10T12:10:00+00:00", "projet Atlas", ["me", "maxime"]),
            ("conv-max-2", "Atlas évolution", "2026-07-05T12:00:00+00:00",
             "2026-07-05T12:15:00+00:00", "projet Atlas", ["me", "maxime"]),
            ("conv-conflict", "Désaccord", "2026-07-22T20:00:00+00:00",
             "2026-07-22T20:08:00+00:00", "organisation", ["me", "maxime"]),
            ("conv-fuzzy", "Discussion séries", "2026-07-09T19:00:00+00:00",
             "2026-07-09T19:12:00+00:00", "Netflix", ["me", "maxime"]),
            ("conv-replay", "Terrasse", "2026-07-18T20:19:00+00:00",
             "2026-07-18T20:22:00+00:00", "terrasse", ["me", "sarah"]),
        ]
        for cid, title, start, end, topic, people in conversations:
            _insert(
                con, "conversations", conversation_id=cid, title=title,
                started_at=start, ended_at=end, topic=topic, channel="phoneonly",
                participants_json=json.dumps(people),
                speaker_map_json=json.dumps({p: p for p in people}),
                relationship_context_json="{}", source_asset_id=None,
                raw_json="{}", created_at=start,
            )

        turns = [
            ("turn-karim-1", "conv-karim", 0, "Karim", "karim",
             "Je confirme le voyage samedi et je réserve les billets."),
            ("turn-karim-2", "conv-karim", 1, "William", "me",
             "D'accord, je prépare les affaires."),
            ("turn-max-1", "conv-max-1", 0, "Maxime", "maxime",
             "Le projet Atlas devrait rester petit et local."),
            ("turn-max-2", "conv-max-2", 0, "Maxime", "maxime",
             "Pour Atlas, je préfère maintenant une version nationale."),
            ("turn-conf-1", "conv-conflict", 0, "William", "me",
             "Je suis déjà tendu, je veux juste finir calmement."),
            ("turn-conf-2", "conv-conflict", 1, "Maxime", "maxime",
             "Tu changes encore le plan sans prévenir."),
            ("turn-conf-3", "conv-conflict", 2, "William", "me",
             "C'est cette accusation qui m'énerve, arrête."),
            ("turn-fuzzy-1", "conv-fuzzy", 0, "Maxime", "maxime",
             "Netflix a renouvelé la série dont on parlait."),
            ("turn-fuzzy-2", "conv-fuzzy", 1, "William", "me",
             "Oui, celle avec la station spatiale."),
            ("turn-replay-1", "conv-replay", 0, "William", "me",
             "Attention derrière toi, Sarah."),
        ]
        for tid, cid, idx, label, pid, text in turns:
            _insert(
                con, "turns", turn_id=tid, conversation_id=cid, idx=idx,
                speaker_label=label, person_id=pid, start_s=float(idx * 4),
                end_s=float(idx * 4 + 3), text=text, previous_turn_id=None,
                metadata_json="{}",
            )

        _insert(
            con, "conversation_discourse_maps", discourse_id="disc-karim",
            conversation_id="conv-karim", primary_subject="voyage",
            subject_is_stable=1,
            conversation_summary=(
                "Karim a confirmé le voyage samedi et s’est engagé à réserver les billets."
            ),
            emotional_arc="calme", intent_arc="coordination",
            unresolved_questions_json="[]", discourse_json="{}",
            extraction_run_id=None, created_at="2026-07-20T18:31:00+00:00",
        )
        _insert(
            con, "conversation_turning_points", turning_point_id="tp-conflict",
            conversation_id="conv-conflict", turn_id="turn-conf-2", turn_idx=1,
            turning_point_type="escalation",
            summary="La discussion a tourné lorsque Maxime a accusé William de changer le plan.",
            before_state="William déjà tendu", after_state="colère explicite",
            evidence_text="Tu changes encore le plan sans prévenir.",
            confidence=0.85, extraction_run_id=None, metadata_json="{}",
            created_at="2026-07-22T20:09:00+00:00",
        )
        _insert(
            con, "causal_hypotheses", hypothesis_id="hyp-conflict",
            episode_id=None, person_id="me",
            hypothesis_text=(
                "La tension préalable a abaissé le seuil, puis l'accusation a déclenché l'escalade."
            ),
            cause_table="turns", cause_id="turn-conf-1", effect_table="turns",
            effect_id="turn-conf-3", causal_type="trigger", strength=0.75,
            evidence_json=json.dumps(["turn:turn-conf-1", "turn:turn-conf-2"]),
            counter_evidence_json="[]", status="candidate", confidence=0.72,
            created_at=NOW, updated_at=NOW,
        )

        for sid, start, end, place in (
            ("scene-morning", "2022-02-22T08:00:00+00:00", "2022-02-22T11:00:00+00:00", "Maison"),
            ("scene-afternoon", "2022-02-22T14:00:00+00:00", "2022-02-22T17:00:00+00:00", "Bureau"),
        ):
            _insert(
                con, "scene_session_summaries_v19", scene_summary_id=sid,
                person_id="me", live_session_id=sid, summary_start=start,
                summary_end=end, place_hint=place, map_quality=0.8,
                summary_json=json.dumps({"place_hint": place}),
                evidence_refs_json=json.dumps([f"session:{sid}"]), created_at=end,
            )

        _insert(
            con, "attribute_memory_observations", person_id="me",
            subject="zone:boulangerie", attribute="prix baguette",
            value="1,20 €", source="ocr", session="bakery-session",
            observed_at="2026-07-17T09:00:00+00:00",
            evidence_ref="frame:bakery-price",
        )
        _insert(
            con, "personal_language_patterns", language_pattern_id="lang-1",
            person_id="me", expression="en vrai", normalized_expression="en vrai",
            context_type="current", preceding_context=None, following_context=None,
            emotion_context=None, speech_act_context=None, frequency=17,
            last_seen="2026-07-22T10:00:00+00:00", examples_json="[]",
            probability_boost=0.4, confidence=0.9, metadata_json="{}",
            created_at=NOW, updated_at=NOW,
        )
        _insert(
            con, "predictions_v19", prediction_id="pred-week",
            person_id="me", source_entry_id="loop-focus",
            emitted_at=NOW, horizon_start="2026-07-24", horizon_end="2026-07-30",
            statement="Risque de repousser Atlas après deux soirées trop chargées.",
            confidence=0.74, status="open",
            verification_spec_json=json.dumps({"invalidate_if": "Atlas terminé"}),
            evidence_refs_json=json.dumps(["confirmed_patterns:focus-loop"]),
            created_at=NOW,
        )
        _insert(
            con, "predictions_v19", prediction_id="pred-live-glasses",
            person_id="me", source_entry_id="routine-glasses",
            emitted_at=NOW, horizon_start="2026-07-23", horizon_end="2026-07-24",
            statement="Tu voulais reprendre tes lunettes avant de sortir.",
            confidence=0.78, status="open",
            verification_spec_json=json.dumps({"entity_label": "glasses"}),
            evidence_refs_json=json.dumps(["scene_session_summaries_v19:scene-morning"]),
            created_at=NOW,
        )
        _insert(
            con, "v14_6_relationship_state_models",
            model_id="relationship-maxime", person_id="me",
            person_hint="Maxime", known_person_id="maxime",
            relationship_state_summary="Relation directe ; Atlas est le sujet actif.",
            their_typical_states_json="[]",
            their_probable_needs_or_motives_json="[]",
            their_common_avoidances_json="[]",
            how_user_affects_them_json="[]", how_they_affect_user_json="[]",
            communication_style="direct", sensitive_topics_json="[]",
            easy_topics_json=json.dumps(["Atlas"]), repair_conditions_json="[]",
            evidence_json=json.dumps(["turn:turn-max-2"]),
            counter_evidence_json="[]", confidence=0.82,
            created_at=NOW, updated_at=NOW,
        )
        _insert(
            con, "v14_7_intervention_queue",
            queue_id="intervention-maxime-conflict",
            opportunity_id="opportunity-maxime-conflict", person_id="me",
            conversation_id="conv-conflict",
            title="Maxime sujet sensible", priority="high", timing="now",
            channel="context_card",
            message=(
                "Attention : avec Maxime, ce sujet a déjà déclenché une escalade."
            ),
            recommended_action="Ralentir et reformuler.",
            why_now="Maxime est présent.", cooldown_key="maxime-conflict",
            status="ready", due_at=None, expires_at=None, delivered_at=None,
            snoozed_until=None, created_at=NOW, updated_at=NOW,
        )

        _insert(
            con, "episodes", episode_id="episode-success",
            episode_type="goal_progress", source_conversation_id="conv-max-2",
            start_turn_id="turn-max-2", end_turn_id="turn-max-2",
            start_time="2026-07-05T12:00:00+00:00",
            end_time="2026-07-05T12:15:00+00:00",
            participants_json=json.dumps(["me", "maxime"]),
            location_text="bureau", channel="phoneonly", topic="Atlas",
            situation_summary="William devait livrer une première version d'Atlas.",
            trigger_summary="échéance proche", user_state_before_json="{}",
            speech_or_action_summary="découpage en petites étapes",
            target_person_id="maxime", target_reaction_summary="validation",
            user_state_after_json="{}", outcome_summary="version livrée",
            unresolved_tension=None, truth_status="observed", confidence=0.9,
            importance_score=0.8, lifecycle_status="active", metadata_json="{}",
            created_at=NOW, updated_at=NOW,
        )
        _insert(
            con, "action_outcomes", outcome_id="outcome-success",
            intention_id=None, episode_id="episode-success", person_id="me",
            action_taken="Découper Atlas en trois livrables courts.",
            result="La première version a été livrée à temps.", success_level=0.9,
            delay_text=None, obstacle_encountered="fatigue",
            emotion_after="satisfait",
            lesson="Le découpage borné évite le blocage.",
            evidence_text="version livrée", truth_status="observed",
            confidence=0.9, metadata_json="{}", created_at=NOW, updated_at=NOW,
        )
        _insert(
            con, "choice_episodes", choice_id="choice-success",
            episode_id="episode-success", person_id="me", turn_id="turn-max-2",
            choice_context="Comment livrer Atlas", options_json="[]",
            criteria_json="[]", preferred_option_before=None,
            chosen_option="Trois livrables courts", rejected_options_json="[]",
            decision_time="2026-07-05T12:05:00+00:00",
            confidence_before=0.5, confidence_after=0.9,
            reason_given="Réduire le risque", real_reason_hypothesis=None,
            outcome_id="outcome-success", satisfaction_after=0.9,
            regret_after=0.0, evidence_text="turn-max-2",
            truth_status="observed", confidence=0.9, metadata_json="{}",
            created_at=NOW, updated_at=NOW,
        )

        _insert(
            con, "brainlive_sessions", live_session_id="final-live",
            person_id="me", started_at=NOW, ended_at=None, status="active",
            session_title="Final scenarios", active_location_hint="salon",
            active_people_json=json.dumps(["maxime"]),
            active_conversation_id=None, current_mode="deep_live",
            h0_goal=None, h1_goal=None, h2_goal=None, metadata_json="{}",
            created_at=NOW, updated_at=NOW,
        )

        replay_image = db_path.parent / "replay-frame.jpg"
        replay_image.write_bytes(b"\xff\xd8\xff\xd9")
        _insert(
            con, "visual_evidence_assets_v19", visual_asset_id="asset-replay",
            person_id="me", live_session_id="replay-session",
            asset_kind="keyframe", uri=str(replay_image), sha256="fixture",
            frame_id="frame-replay", clip_id=None,
            captured_at="2026-07-18T20:19:00+00:00", metadata_json="{}",
            created_at="2026-07-18T20:19:00+00:00",
        )
        _insert(
            con, "visual_events_v19", visual_event_id="visual-replay",
            person_id="me", live_session_id="replay-session",
            event_type="person_present", occurred_at="2026-07-18T20:19:00+00:00",
            entity_json=json.dumps({"label": "Sarah"}),
            observation_json=json.dumps({"summary": "Sarah sur la terrasse"}),
            place_json=json.dumps({"place_hint": "terrasse"}),
            truth_level="observed", confidence=0.9,
            evidence_refs_json=json.dumps(["frame:frame-replay"]),
            provenance_json="{}", asset_id="asset-replay",
            created_at="2026-07-18T20:19:00+00:00",
        )
        _insert(
            con, "brainlive_deep_vision_observations_v161",
            deep_observation_id="deep-keys-latest", run_id="deep-run-fixture",
            person_id="me", package_date="2026-07-22",
            bundle_id="deep-bundle-fixture", live_session_id="deep-session",
            frame_id="deep-frame-keys", image_path=str(replay_image),
            frame_time="2026-07-22T19:00:00+00:00", sample_index=0,
            sample_reason="scene_change", model="fixture-vlm", status="ok",
            scene_summary_detailed="Des clés sont visibles sur la console.",
            observed_activity="observation", activity_confidence=0.8,
            location_hint="entrée", spatial_layout="sur la console",
            objects_json=json.dumps(["clés"]), affordances_json="[]",
            visible_text_json="[]", people_presence_json="{}",
            screens_or_devices_json="[]", posture_motion_json="{}",
            work_or_rest_signal_json="{}", smoking_pause_signal_json="{}",
            exact_visual_evidence_json=json.dumps(["frame:deep-frame-keys"]),
            uncertainty_json="[]", qwen_json="{}", latency_ms=100,
            error_text=None, created_at=NOW, updated_at=NOW,
        )
        con.commit()


class FakeIngress:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send_ui_intent(self, payload: str) -> int:
        self.messages.append(json.loads(payload))
        return 1


class FixturePlanLLM:
    """Only replaces model inference; the help state machine and wires are real."""

    cloud_active = False

    def complete_json(self, _system: str, _user: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "title": "Faire un café",
            "domain": "cooking",
            "steps": [
                {
                    "text": "Place la tasse sous la machine.",
                    "action": "place",
                    "objects": [
                        {"name": "la tasse", "label_en": "cup", "role": "target"}
                    ],
                    "gesture": {"kind": "linear", "from": None, "to": "cup"},
                    "timer_seconds": None,
                    "caution": None,
                    "done_when": "voice",
                },
                {
                    "text": "Appuie sur le bouton.",
                    "action": "press",
                    "objects": [
                        {"name": "le bouton", "label_en": "", "role": "target"}
                    ],
                    "gesture": {"kind": "pulse", "from": None, "to": None},
                    "timer_seconds": None,
                    "caution": None,
                    "done_when": "voice",
                },
            ],
        }


def _vision_reply(request: dict[str, Any]) -> dict[str, Any]:
    kind = str(request.get("kind") or "what_is")
    content: dict[str, Any] = {
        "kind": kind, "title": "Vision", "text": "Texte Midea 1,20 €",
        "lines": [{"text": "Midea 1,20 €"}],
    }
    if request.get("zoom"):
        content.update({"zoom": True, "center": [0.5, 0.5], "factor": 2.0})
    return {
        "type": "ui_intent", "ui_intent_id": f"vision-{kind}",
        "producer": "visionrt", "component": "context_card",
        "content": content, "truth_level": "observed", "confidence": 0.9,
        "priority": 0.7, "ttl_ms": 8000,
        "evidence_refs": ["frame:focus-fixture"],
    }


def run_gate(db_path: Path) -> dict[str, Any]:
    os.environ["MLOMEGA_DB"] = str(db_path)
    replay = replay_mod.ReplayService(
        person_id="me", live_session_id="final-live", db_path=db_path
    )
    memory = memory_query_mod.MemoryQuery(
        person_id="me", db_path=db_path, replay_service=replay
    )
    ingress = FakeIngress()
    router = intent_router_mod.IntentRouter(
        vision_focus=_vision_reply,
        on_device_command=lambda command: ingress.send_ui_intent(json.dumps(command)),
        ask_memory=memory.ask,
        replay_service=replay,
        person_id="me",
        emit_ui_intent=lambda intent: ingress.send_ui_intent(json.dumps(intent)),
    )

    questions = {
        "where_date": "Où j’étais le 22 février 2022 ?",
        "last_encounter": "Qu’a dit Karim la dernière fois que je l’ai vu ?",
        "topic_history": "Combien de fois Maxime m’a parlé du projet Atlas ?",
        "conflict": "Pourquoi je me suis embrouillé avec Maxime hier ?",
        "latest_price": "C’était combien le prix de la baguette à la boulangerie la dernière fois ?",
        "predictions": "Prédit-moi ce qu’il va m’arriver dans les prochains jours.",
        "expression": "C’est quoi mon expression favorite du moment ?",
        "fuzzy": "C’est quoi le truc dont je parlais il y a genre deux semaines avec Maxime à propos de Netflix ?",
        "success": "Comment j’ai réussi à faire ça ?",
        "semantic_replay": "Rejoue la scène avec Sarah où j’ai dit attention derrière.",
    }
    answers: dict[str, dict[str, Any]] = {}
    for key, question in questions.items():
        direct = memory.structured.resolve(question)
        if direct is None:
            raise AssertionError(f"{key}: structured resolver did not claim scenario")
        routed = router.on_transcript(f"interroge ma mémoire : {question}")
        intent = dict(routed).get("ui_intent")
        if not isinstance(intent, dict):
            raise AssertionError(f"{key}: no UI intent")
        UIIntent.model_validate(intent)
        answers[key] = intent

    # Product WorldBrain + spatial query: no fake bearing under a 2D/low-quality map.
    spatial = spatial_mod.PoseKeyframeMap()
    world = worldbrain_mod.WorldBrain(
        person_id="me", live_session_id="final-live", db_path=db_path,
        service_db_path=db_path, spatial=spatial,
        config=worldbrain_mod.WorldBrainConfig(
            promote_min_observations=1, promote_min_confidence=0.3
        ), publish_world_state=False,
    )
    world.ingest_scene_delta({
        "session_id": "final-live", "source_frame_id": "glasses-before",
        "frame_width": 576, "frame_height": 1024, "rotation": 0,
        "mirrored": False, "coordinate_space": "detector_pixels",
        "entities": [{
            "track_id": "glasses", "kind": "object", "label": "glasses",
            "bbox": [40, 100, 180, 220], "confidence": 0.9,
        }], "relations": [], "changes": [], "map_quality": 0.0,
        "evidence_refs": ["frame:glasses-before"],
    })
    record = world.find_entity_record("glasses")
    assert record and record["label"] == "glasses"
    spatial_answer = spatial_mod.answer_find(
        entity_id=record["entity_id"], entity=record, spatial=spatial,
        session_id="final-live", visible=True, query="lunettes",
    )
    assert spatial_answer["content"].get("bearing") is None
    # A different, open-vocabulary object was observed only by the nightly VLM.
    # A fresh process/session must still answer with its latest coarse place and
    # proof, while refusing to invent a bearing because no detector bbox exists.
    fresh_world = worldbrain_mod.WorldBrain(
        person_id="me", live_session_id="final-live-next", db_path=db_path,
        service_db_path=db_path, publish_world_state=False,
    )
    deep_record = fresh_world.find_entity_record("où sont mes clés ?")
    assert deep_record and deep_record["source"] == "deep_vision_last_seen"
    deep_spatial_answer = spatial_mod.answer_find(
        entity_id=deep_record["entity_id"], entity=deep_record, spatial=spatial,
        session_id="final-live-next", visible=False, query="clés",
    )
    assert deep_spatial_answer["content"]["place_hint"] == "entrée"
    assert deep_spatial_answer["content"].get("bearing") is None

    # Add a visible person, then cross the true identity -> relation-prefetch
    # boundary. The two cue modalities are fixture data; fusion, WorldBrain,
    # hot-message construction and relation lookup are production code.
    world.ingest_scene_delta({
        "session_id": "final-live", "source_frame_id": "maxime-visible",
        "frame_width": 576, "frame_height": 1024, "rotation": 0,
        "mirrored": False, "coordinate_space": "detector_pixels",
        "entities": [
            {
                "track_id": "glasses", "kind": "object", "label": "glasses",
                "bbox": [220, 110, 360, 230], "confidence": 0.9,
            },
            {
                "track_id": "max-track", "kind": "person", "label": "person",
                "bbox": [80, 200, 420, 980], "confidence": 0.92,
            },
        ],
        "relations": [],
        "changes": [{
            "type": "moved", "entity_id": record["entity_id"],
            "label": "glasses", "evidence_refs": ["frame:maxime-visible"],
        }],
        "map_quality": 0.0, "evidence_refs": ["frame:maxime-visible"],
    })
    person_record = world.find_entity_record("person")
    assert person_record is not None

    hot_updates: list[dict[str, Any]] = []
    proactive = proactive_mod.ProactiveContext(person_id="me", db_path=db_path)
    proactive.refresh(package_date="2026-07-23")
    adapter = scene_adapter_mod.BrainLiveSceneAdapter(
        person_id="me", live_session_id="final-live", worldbrain=world,
        db_path=db_path, proactive=proactive,
        on_entity_hot_update=hot_updates.append,
    )
    fusion = identity_mod.IdentityFusion(worldbrain=world, scene_adapter=adapter)
    verdict = fusion.resolve(
        entity_id=person_record["entity_id"], track_id="max-track",
        face={
            "matched": True, "person_id": "maxime",
            "name": "Maxime", "score": 0.86,
        },
        voice={
            "matched": True, "person_id": "maxime",
            "name": "Maxime", "score": 0.84,
        },
    )
    assert verdict.identified and verdict.person_id == "maxime"
    relation_updates = [
        update for update in hot_updates
        if update.get("type") == "entity_hot_update"
        and update.get("person_id") == "maxime"
    ]
    assert relation_updates
    assert any(
        pack.get("summary")
        for pack in relation_updates[0].get("relation_pack") or []
    ), "CardProfil must receive a human-readable V14.6 relationship summary"

    proactive_results = adapter.evaluate_situations()
    assert any(result.get("status") == "queued" for result in proactive_results)
    assert adapter.metrics["proactive_predictions"] >= 1
    assert adapter.metrics["proactive_interventions"] >= 1
    assert any(
        update.get("type") == "entity_hot_update"
        and update.get("kind") == "object"
        for update in hot_updates
    )

    # Actual ChangeAttention state machine: first visit learns, leaving freezes,
    # a high-quality re-entry with the phone gone emits one durable cue.
    change_attention = change_attention_mod.ChangeAttention(
        person_id="me", live_session_id="final-live", db_path=db_path,
        scene_adapter=adapter,
    )

    def _zone_snapshot(zone: str, labels: list[str], quality: float) -> dict[str, Any]:
        return {
            "active_zone": zone, "map_quality": quality,
            "entities": [
                {"entity_id": f"{zone}:{label}", "label": label, "lifecycle": "confirmed"}
                for label in labels
            ],
        }

    assert change_attention.on_scene_snapshot(
        _zone_snapshot("salon", ["glasses", "phone"], 0.9)
    ) is None
    assert change_attention.on_scene_snapshot(
        _zone_snapshot("kitchen", ["coffee machine"], 0.9)
    ) is None
    change_result = change_attention.on_scene_snapshot(
        _zone_snapshot("salon", ["glasses"], 0.9)
    )
    assert change_result and change_result["status"] == "queued"
    assert change_result["disappeared"] == ["phone"]

    # Negative boundary: no spatial claim when map quality is insufficient.
    low_quality_attention = change_attention_mod.ChangeAttention(
        person_id="me", live_session_id="final-live-low-quality",
        db_path=db_path, scene_adapter=adapter,
    )
    low_quality_attention.on_scene_snapshot(
        _zone_snapshot("desk", ["keys", "phone"], 0.9)
    )
    low_quality_attention.on_scene_snapshot(
        _zone_snapshot("hall", ["door"], 0.9)
    )
    assert low_quality_attention.on_scene_snapshot(
        _zone_snapshot("desk", ["keys"], 0.1)
    ) is None
    assert low_quality_attention.metrics["silenced_low_quality"] == 1

    help_engine = help_mod.HelpTaskEngine(
        person_id="me", live_session_id="final-live",
        llm_router=FixturePlanLLM(), scene_adapter=adapter, worldbrain=world,
        emit_ui_intent=lambda intent: ingress.send_ui_intent(json.dumps(intent)),
        service_db_path=db_path,
    )

    def _who_is() -> dict[str, Any]:
        named = adapter.known_people.get(person_record["entity_id"]) or {}
        return {
            "type": "ui_intent", "ui_intent_id": "who-is-final",
            "producer": "identity_fusion", "component": "context_card",
            "content": {
                "kind": "who_is",
                "text": f"Je reconnais {named.get('name')}.",
                "person_id": named.get("person_id"),
            },
            "truth_level": "observed", "confidence": named.get("confidence", 0.0),
            "priority": 0.7, "ttl_ms": 6000,
            "evidence_refs": [f"entity:{person_record['entity_id']}"],
        }

    def _scene_changes() -> dict[str, Any]:
        recent = list(world.snapshot().get("recent_changes") or [])[-5:]
        return {
            "type": "ui_intent", "ui_intent_id": "scene-changes-final",
            "producer": "worldbrain", "component": "context_card",
            "content": {
                "kind": "scene_changes",
                "text": (
                    "Changements récents : "
                    + ", ".join(
                        str(c.get("label") or c.get("type") or "changement")
                        for c in recent
                    )
                    + "."
                ) if recent else "Je n'ai pas observé de changement fiable ici.",
                "changes": recent,
            },
            "truth_level": "observed" if recent else "unknown",
            "confidence": 0.8 if recent else 0.0,
            "priority": 0.6, "ttl_ms": 7000,
            "evidence_refs": sorted({
                ref for change in recent
                for ref in (change.get("evidence_refs") or [])
            }),
        }

    # Real router delivery boundary for focus/OCR/zoom/translation, local
    # actions, scene/identity context and the multi-turn help state machine.
    router = intent_router_mod.IntentRouter(
        vision_focus=_vision_reply,
        on_device_command=lambda command: ingress.send_ui_intent(json.dumps(command)),
        ask_memory=memory.ask, who_is=_who_is, scene_changes=_scene_changes,
        replay_service=replay, help_engine=help_engine, person_id="me",
        emit_ui_intent=lambda intent: ingress.send_ui_intent(json.dumps(intent)),
    )
    routed_live = {
        "what_is": router.on_transcript("c'est quoi cet objet"),
        "ocr": router.on_transcript("lis le texte"),
        "zoom": router.on_transcript("zoom"),
        "translate": router.on_transcript("traduis en anglais"),
        "menu": router.on_transcript("menu"),
        "maps": router.on_transcript("ouvre maps vers la gare"),
        "privacy": router.on_transcript("pause privée"),
        "who_is": router.on_transcript("qui est cette personne"),
        "scene_changes": router.on_transcript("qu'est-ce qui a changé"),
    }
    assert all(bool(value.get("handled")) for value in routed_live.values())

    help_flow = [
        router.on_transcript("mode aide"),
        router.on_transcript(
            "j'ai déjà commencé mon café, aide-moi seulement à finir"
        ),
        router.on_transcript("étape suivante"),
        router.on_transcript("répète"),
        router.on_transcript("termine la tâche"),
    ]
    assert [row["intent"] for row in help_flow] == [
        "help_start", "help_start", "help_advance", "help_repeat", "help_stop",
    ]
    assert all(row.get("handled") for row in help_flow)
    assert not help_engine.active

    # Canonical-person appearance across two visual entities/sessions.
    attr = attribute_mod.AttributeMemory(
        person_id="me", worldbrain=world, service_db_path=db_path
    )
    attr.observe_person_appearance(
        entity_id="maxime-visual-day1", canonical_person_id="maxime",
        descriptor={"coiffure": "longue"}, session="day-1",
        evidence_ref="frame:maxime-day1",
    )
    appearance_changes = attr.observe_person_appearance(
        entity_id="maxime-visual-day2", canonical_person_id="maxime",
        descriptor={"coiffure": "courte"}, session="day-2",
        evidence_ref="frame:maxime-day2",
    )
    assert appearance_changes and appearance_changes[0]["entity_id"] == "person:maxime"
    appearance_delivery = adapter.evaluate_situations()
    assert adapter.metrics["attribute_change_cues"] >= 1
    assert any(
        result.get("status") == "queued" for result in appearance_delivery
    )

    # BrainLive queue → canonical ContextCard → JSON contract → displayed receipt.
    queued = adapter._enqueue(
        source_key="final:conflict-warning",
        message="Attention : ce sujet a déjà mené à une escalade.",
        evidence_refs=["conversation_turning_points:tp-conflict"],
        priority=0.8, kind="conflict_warning",
    )
    assert queued["status"] == "queued"
    renderer = delivery_mod.RendererHub()
    delivery = delivery_mod.DeliveryAdapter(renderer=renderer)
    sent = asyncio.run(delivery.dispatch_once())
    conflict_intent = next(
        (
            intent for intent in sent
            if str(intent.content.get("text") or "").startswith("Attention")
        ),
        None,
    )
    assert conflict_intent is not None
    wire = conflict_intent.model_dump_json()
    UIIntent.model_validate_json(wire)
    receipt = UIReceipt(
        ui_intent_id=conflict_intent.ui_intent_id,
        delivery_id=conflict_intent.delivery_id,
        event="displayed",
        observed_at=NOW,
        source="final_all_scenarios",
    )
    assert delivery.record_receipt(receipt) is not None

    return {
        "status": "passed",
        "proof_level": "real_product_components_seeded_external_inputs",
        "simulated_boundaries": [
            "seeded_memory_history",
            "phone_datachannel_capture",
            "planning_llm_response",
            "generic_vision_focus_response",
        ],
        "not_claimed": [
            "physical_s25_camera_microphone_permissions",
            "physical_unity_render_and_receipt",
            "model_quality_from_the_seeded_llm_or_vision_responses",
        ],
        "db_path": str(db_path),
        "memory_scenarios": {
            key: {
                "component": intent["component"],
                "kind": intent["content"].get("kind"),
                "text": intent["content"].get("text"),
                "truth_level": intent["truth_level"],
                "evidence_refs": intent.get("evidence_refs"),
            }
            for key, intent in answers.items()
        },
        "ultralive": {
            "spatial_find": spatial_answer,
            "deep_vision_last_seen": deep_spatial_answer,
            "commands": {
                key: {"intent": value.get("intent"), "handled": value.get("handled")}
                for key, value in routed_live.items()
            },
            "help_flow": [row.get("intent") for row in help_flow],
            "identity": {
                "person_id": verdict.person_id,
                "relation_pack": relation_updates[0]["relation_pack"],
            },
            "hot_updates": hot_updates,
            "proactive": {
                "prediction_matches": proactive.metrics["prediction_matches"],
                "intervention_matches": proactive.metrics["intervention_matches"],
                "queued": sum(
                    result.get("status") == "queued"
                    for result in proactive_results
                ),
            },
            "change_attention": {
                "result": change_result,
                "low_quality_silenced": (
                    low_quality_attention.metrics["silenced_low_quality"]
                ),
            },
            "appearance_change": appearance_changes[0],
            "appearance_cue_queued": adapter.metrics["attribute_change_cues"],
            "delivery": json.loads(wire),
            "receipt": "displayed",
            "downlink_count": len(ingress.messages),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    if args.db.exists() and not args.reuse:
        args.db.unlink()
    if not args.db.exists():
        seed_fixture(args.db)
    report = run_gate(args.db)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
