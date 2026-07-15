from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlomega_audio_elite.brain2_conversation_episode import (
    ConversationEpisodeContractError,
    build_conversation_episode_v6,
    normalize_conversation_episode,
    normalize_segmentation,
)
from mlomega_audio_elite.night_orchestrator.executor import LLMCallResult


def _turns() -> list[dict[str, object]]:
    texts = [
        "J'ai rendez-vous avec Karim le 14.",
        "Fais attention avec Karim.",
        "Il vient réparer un objet.",
        "Maxime, c'est toi ?",
        "Tu fais quoi comme métier ?",
        "Je travaille dans l'import-export.",
        "Tu as vu le documentaire Netflix ?",
        "Oui, celui de Nolan.",
    ]
    return [
        {
            "turn_id": f"t{index}",
            "idx": index,
            "speaker_label": "SPEAKER_00" if index != 5 else "SPEAKER_01",
            "person_id": "UNKNOWN_VOICE_001" if index != 5 else "UNKNOWN_VOICE_002",
            "start_s": float(index),
            "end_s": float(index) + 0.5,
            "text": text,
            "metadata_json": json.dumps({
                "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript",
                "source": {"word_alignment": {"count": 3, "mean_score": 0.8}},
            }),
        }
        for index, text in enumerate(texts)
    ]


def _model_output() -> dict[str, object]:
    return {
        "conversation_episode": {
            "title": "Échange entre proches",
            "situation_summary": (
                "La conversation aborde Karim, l'identité, le métier puis un documentaire."
            ),
            "participants": ["UNKNOWN_VOICE_001", "UNKNOWN_VOICE_002"],
            "location": None,
            "channel": "phoneonly",
            "confidence": 0.78,
            "subthemes": [
                {
                    "ordinal": 0,
                    "subtheme_type": "planning",
                    "title": "Rendez-vous avec Karim",
                    "summary": "Rendez-vous, prudence et motif de la visite de Karim.",
                    "boundary_reason": "conversation_start",
                    "participants": ["UNKNOWN_VOICE_001"],
                    "turn_ids": ["t0", "t1", "t2"],
                    "evidence_turn_ids": ["t0", "t1", "t2"],
                    "outcome": None,
                    "unresolved_tension": "Prudence lors du rendez-vous.",
                    "confidence": 0.8,
                },
                {
                    "ordinal": 1,
                    "subtheme_type": "identity",
                    "title": "Identification",
                    "summary": "Le locuteur vérifie qu'il parle à Maxime.",
                    "boundary_reason": "new_goal",
                    "participants": ["UNKNOWN_VOICE_001"],
                    "turn_ids": ["t3"],
                    "evidence_turn_ids": ["t3"],
                    "outcome": None,
                    "unresolved_tension": None,
                    "confidence": 0.65,
                },
                {
                    "ordinal": 2,
                    "subtheme_type": "work",
                    "title": "Métier import-export",
                    "summary": "Question et réponse sur le métier d'import-export.",
                    "boundary_reason": "new_question",
                    "participants": ["UNKNOWN_VOICE_001", "UNKNOWN_VOICE_002"],
                    "turn_ids": ["t4", "t5"],
                    "evidence_turn_ids": ["t4", "t5"],
                    "outcome": "Le métier est expliqué.",
                    "unresolved_tension": None,
                    "confidence": 0.9,
                },
                {
                    "ordinal": 3,
                    "subtheme_type": "media",
                    "title": "Documentaire Netflix",
                    "summary": "Les interlocuteurs évoquent un documentaire de Nolan.",
                    "boundary_reason": "explicit_transition",
                    "participants": ["UNKNOWN_VOICE_001"],
                    "turn_ids": ["t6", "t7"],
                    "evidence_turn_ids": ["t6", "t7"],
                    "outcome": "Le documentaire a été vu.",
                    "unresolved_tension": None,
                    "confidence": 0.85,
                },
            ],
        },
        "missing_context": ["Les voix ne sont pas enrôlées."],
        "confidence": 0.78,
    }


def _segmentation_output() -> dict[str, object]:
    return {
        "segments": [
            {
                "ordinal": 0, "title_hint": "Karim", "start_turn_id": "t0",
                "end_turn_id": "t2", "boundary_reason": "conversation_start",
            },
            {
                "ordinal": 1, "title_hint": "Identité", "start_turn_id": "t3",
                "end_turn_id": "t3", "boundary_reason": "new_goal",
            },
            {
                "ordinal": 2, "title_hint": "Métier", "start_turn_id": "t4",
                "end_turn_id": "t5", "boundary_reason": "new_domain",
            },
            {
                "ordinal": 3, "title_hint": "Documentaire", "start_turn_id": "t6",
                "end_turn_id": "t7", "boundary_reason": "explicit_transition",
            },
        ],
        "missing_context": [],
    }


def test_normalize_builds_one_parent_and_keeps_topics_separate():
    normalized = normalize_conversation_episode(_model_output(), _turns())
    assert len(normalized["episodes"]) == 1
    parent = normalized["episodes"][0]
    assert parent["evidence_turn_ids"] == [f"t{i}" for i in range(8)]
    assert len(parent["subthemes"]) == 4
    karim, _identity, _work, netflix = parent["subthemes"]
    assert karim["turn_ids"] == ["t0", "t1", "t2"]
    assert netflix["turn_ids"] == ["t6", "t7"]
    assert not set(karim["evidence_turn_ids"]) & set(netflix["evidence_turn_ids"])


@pytest.mark.parametrize("mutation,match", [
    (lambda out: (
        out["conversation_episode"]["subthemes"][0]["turn_ids"].pop(),
        out["conversation_episode"]["subthemes"][0]["evidence_turn_ids"].pop(),
    ),
     "membership_not_lossless"),
    (lambda out: out["conversation_episode"]["subthemes"][1]["turn_ids"].append("t0"),
     "non_contiguous|overlap_or_order"),
    (lambda out: out["conversation_episode"]["subthemes"][3].update(
        evidence_turn_ids=["t0"]), "invalid_evidence"),
])
def test_normalize_rejects_loss_or_cross_topic_reuse(mutation, match):
    output = _model_output()
    mutation(output)
    with pytest.raises(ConversationEpisodeContractError, match=match):
        normalize_conversation_episode(output, _turns())


def test_segmentation_canonicalizes_only_inclusive_boundary_overlap():
    turns = _turns()
    output = _segmentation_output()
    # A..B then B..C is a common inclusive-boundary convention.  End
    # boundaries remain strictly ordered, so exact membership is recoverable.
    output["segments"][1]["start_turn_id"] = output["segments"][0]["end_turn_id"]

    segments = normalize_segmentation(output, turns)

    assert segments[0]["turn_ids"] == ["t0", "t1", "t2"]
    assert segments[1]["turn_ids"] == ["t3"]
    assert [turn_id for segment in segments for turn_id in segment["turn_ids"]] == [
        f"t{i}" for i in range(8)
    ]


def test_segmentation_end_boundaries_make_partition_lossless_by_construction():
    output = _segmentation_output()
    for segment in output["segments"]:
        segment.pop("start_turn_id", None)

    segments = normalize_segmentation(output, _turns())

    assert [segment["start_turn_id"] for segment in segments] == ["t0", "t3", "t4", "t6"]
    assert [turn_id for segment in segments for turn_id in segment["turn_ids"]] == [
        f"t{i}" for i in range(8)
    ]


def test_shadow_builder_uses_one_call_and_never_assigns_sensor_turn():
    sensor = {
        "turn_id": "vision-1",
        "idx": 4,
        "text": "personne visible",
        "metadata_json": json.dumps({
            "evidence_role": "system_observation_not_user_speech",
            "source": {"vision_change_atom": True, "count": 30},
        }),
    }
    bundle = {
        "conversation": {"conversation_id": "conv1", "channel": "phoneonly"},
        "turns": [*_turns(), sensor],
        "source_spans": [],
    }

    class FakeLLM:
        model = "fake-e64i"

        def __init__(self):
            self.calls = []

        def generate(self, payload, *, output_budget):
            self.calls.append((json.loads(payload["prompt"]), output_budget))
            data = _segmentation_output() if len(self.calls) == 1 else _model_output()
            return LLMCallResult(ok=True, data=data)

    llm = FakeLLM()
    written = {}

    def materialize(_con, _conversation_id, output):
        written["output"] = output
        return len(output["episodes"])

    stats = build_conversation_episode_v6(
        object(),
        "conv1",
        bundle=bundle,
        safe_prompt=lambda payload: json.dumps(payload, ensure_ascii=False),
        materialize=materialize,
        system="strict",
        window_llm=llm,
        input_budget=50_000,
        output_budget=4096,
    )
    assert stats["calls"] == len(llm.calls) == 2
    segmentation_prompt = llm.calls[0][0]
    detail_prompt = llm.calls[1][0]
    assert segmentation_prompt["contract"]["human_turn_ids"] == [f"t{i}" for i in range(8)]
    assert [turn["turn_id"] for turn in detail_prompt["sensor_context"]] == ["vision-1"]
    assert "vision-1" not in written["output"]["episodes"][0]["evidence_turn_ids"]


def test_shadow_builder_fails_before_call_when_input_is_oversized():
    class NeverCalled:
        model = "never"

        def generate(self, payload, *, output_budget):  # pragma: no cover
            raise AssertionError("LLM must not be called")

    with pytest.raises(ConversationEpisodeContractError, match="input_budget_exceeded"):
        build_conversation_episode_v6(
            object(),
            "conv1",
            bundle={"conversation": {}, "turns": _turns()},
            safe_prompt=lambda payload: json.dumps(payload, ensure_ascii=False),
            materialize=lambda *_: 0,
            system="strict",
            window_llm=NeverCalled(),
            input_budget=100,
            output_budget=512,
        )


def test_shadow_builder_rejects_reference_only_prompt_compaction():
    class NeverCalled:
        model = "never"

        def generate(self, payload, *, output_budget):  # pragma: no cover
            raise AssertionError("LLM must not be called")

    with pytest.raises(ConversationEpisodeContractError, match="prompt_compaction_rejected"):
        build_conversation_episode_v6(
            object(),
            "conv1",
            bundle={"conversation": {}, "turns": _turns()},
            safe_prompt=lambda _payload: json.dumps({"context_incomplete": True}),
            materialize=lambda *_: 0,
            system="strict",
            window_llm=NeverCalled(),
            input_budget=50_000,
            output_budget=512,
        )


def test_writer_persists_ordered_membership_and_primary_citations(tmp_path, monkeypatch):
    db_path = Path(tmp_path) / "e64i.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    from mlomega_audio_elite.brain2_strict_v13_2 import (
        _materialize_episodes_from_qwen,
        ensure_strict_v13_schema,
    )
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.utils import now_iso

    ensure_strict_v13_schema()
    now = now_iso()
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO conversations(
                conversation_id,title,started_at,channel,participants_json,
                speaker_map_json,relationship_context_json,raw_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("conv1", "fixture", now, "phoneonly", "[]", "{}", "{}", "{}", now),
        )
        for turn in _turns():
            con.execute(
                """INSERT INTO turns(
                    turn_id,conversation_id,idx,speaker_label,person_id,start_s,end_s,
                    text,previous_turn_id,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    turn["turn_id"], "conv1", turn["idx"], turn["speaker_label"],
                    turn["person_id"], turn["start_s"], turn["end_s"], turn["text"],
                    None, turn["metadata_json"],
                ),
            )
        normalized = normalize_conversation_episode(_model_output(), _turns())
        assert _materialize_episodes_from_qwen(con, "conv1", normalized) == 1
        con.commit()

        assert con.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 1
        episode_metadata = json.loads(
            con.execute("SELECT metadata_json FROM episodes").fetchone()[0]
        )
        assert episode_metadata["subtheme_types"] == [
            "planning", "identity", "work", "media"
        ]
        assert con.execute("SELECT COUNT(*) FROM episode_subthemes_v19").fetchone()[0] == 4
        assert con.execute(
            """SELECT COUNT(*) FROM episode_subtheme_evidence_v19
                 WHERE evidence_role='membership'"""
        ).fetchone()[0] == 8
        assert con.execute(
            """SELECT COUNT(DISTINCT turn_id) FROM episode_subtheme_evidence_v19
                 WHERE evidence_role='membership'"""
        ).fetchone()[0] == 8
        rows = con.execute(
            "SELECT ordinal,title,start_turn_id,end_turn_id FROM episode_subthemes_v19 ORDER BY ordinal"
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [
            (0, "Rendez-vous avec Karim"),
            (1, "Identification"),
            (2, "Métier import-export"),
            (3, "Documentaire Netflix"),
        ]
        assert rows[0][2:] == ("t0", "t2")
        assert rows[-1][2:] == ("t6", "t7")


def test_conversation_parent_keeps_conditional_v13_capabilities():
    from mlomega_audio_elite.brain2_strict_v13_2 import _engine_applies_to_episode

    episode = {
        "episode_type": "conversation",
        "metadata_json": json.dumps({
            "subtheme_types": ["planning", "relationship", "work", "media"]
        }),
    }
    profile = {"has_human_evidence": True, "sensor_only": False, "human_speaker_count": 1}
    for engine in (
        "capture_engine", "language_signature_engine", "context_resolver",
        "causality_engine", "internal_state_engine", "social_model_engine",
        "contradiction_engine", "choice_model_engine", "outcome_tracker",
    ):
        assert _engine_applies_to_episode(engine, episode, profile)[0] is True, engine
