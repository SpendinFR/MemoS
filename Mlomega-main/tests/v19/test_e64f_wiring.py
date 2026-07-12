"""E64-F wave 1 wiring: producer vision reduction + windowed EpisodeBuilder.

Exercises the three pieces without hitting Ollama or the full close-day:
- the event assembler now emits ONE pseudo-turn per VisionChangeAtom (flag on),
  the legacy one-per-observation when rolled back;
- ``build_episodes_windowed`` runs the (fake) V13 call per autonomous window,
  merges episodes, and persists a coverage proof that blocks on any gap.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from mlomega_audio_elite.night_orchestrator import LLMCallResult

pytestmark = pytest.mark.memory


# ------------------------------------------------- piece 1: producer reduction
def _vitem(source_id, time, *, label="person", track="t1", summary=None):
    return {
        "time": time,
        "summary": summary,
        "location_hint": None,
        "objects": [{"label": label, "track_id": track}],
        "visible_text": [],
        "frame_id": f"frame_{source_id}",
        "source_id": source_id,
    }


def test_vision_pseudo_turns_collapse_when_flag_on(monkeypatch):
    from mlomega_audio_elite.brainlive_event_assembler_v15_14 import _vision_pseudo_turns

    monkeypatch.setenv("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "1")
    items = [_vitem(f"o{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(40)]
    turns = _vision_pseudo_turns(items)
    assert len(turns) == 1  # 40 identical frames -> one atom pseudo-turn
    t = turns[0]
    assert t["speaker_label"] == "context_vision_raw"  # shape unchanged for Brain2
    assert t["kind"] == "vision_context"
    assert t["metadata"]["count"] == 40
    assert sorted(t["metadata"]["source_refs"]) == sorted(f"o{i}" for i in range(40))
    assert "40x" in t["text"]


def test_vision_pseudo_turns_legacy_when_flag_off(monkeypatch):
    from mlomega_audio_elite.brainlive_event_assembler_v15_14 import _vision_pseudo_turns

    monkeypatch.setenv("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "0")
    items = [_vitem(f"o{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(10)]
    turns = _vision_pseudo_turns(items)
    assert len(turns) == 10  # rollback: one pseudo-turn per observation
    assert all(t["speaker_label"] == "context_vision_raw" for t in turns)


def test_vision_pseudo_turns_split_on_real_change(monkeypatch):
    from mlomega_audio_elite.brainlive_event_assembler_v15_14 import _vision_pseudo_turns

    monkeypatch.setenv("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "1")
    items = [
        _vitem("a", "t1", label="person"),
        _vitem("b", "t2", label="person"),
        _vitem("c", "t3", label="cup", track="t2"),
    ]
    turns = _vision_pseudo_turns(items)
    assert len(turns) == 2


# ------------------------------------------- piece 2: windowed EpisodeBuilder
def _turns(n):
    # each turn ~ 400 chars so a small token budget forces several windows
    return [
        {"turn_id": f"t{i}", "idx": i, "speaker_label": "speaker",
         "text": "parole " + "x" * 380}
        for i in range(n)
    ]


def test_should_window_only_for_oversized():
    from mlomega_audio_elite.brain2_episode_windowing import should_window

    assert should_window(_turns(200), budget_tokens=1000) is True
    assert should_window(_turns(2), budget_tokens=100000) is False


def test_should_window_counts_metadata_not_only_transcript_text():
    from mlomega_audio_elite.brain2_episode_windowing import should_window

    turns = [{
        "turn_id": "tiny-text-heavy-proof",
        "text": "ok",
        "metadata_json": json.dumps({"source_refs": [f"obs{i}" for i in range(500)]}),
    }]
    assert should_window(turns, budget_tokens=500) is True


def test_source_coverage_expands_atoms_to_all_985_raw_proofs():
    from mlomega_audio_elite.brain2_episode_windowing import _source_coverage

    turns = _turns(40)
    raw_refs = [f"obs{i}" for i in range(945)]
    for atom_index in range(120):
        refs = raw_refs[atom_index::120]
        turns.append({
            "turn_id": f"vision_atom_{atom_index}",
            "idx": 40 + atom_index,
            "text": "vision",
            "metadata_json": json.dumps({
                "source": {
                    "vision_change_atom": True,
                    "source_refs": refs,
                }
            }),
        })
    expected, atom_index = _source_coverage(turns)
    assert len(expected) == 985
    assert set(expected) == {f"t{i}" for i in range(40)} | set(raw_refs)
    assert len(atom_index) == 120


def test_prompt_projection_keeps_semantics_but_not_opaque_raw_id_lists():
    from mlomega_audio_elite.brain2_episode_windowing import _prompt_turn

    original = {
        "turn_id": "vision_atom_1",
        "text": "personne puis clés sur la table",
        "metadata_json": json.dumps({
            "source": {
                "vision_change_atom": True,
                "state": {"labels": ["person", "keys"]},
                "representative": {
                    "objects": [{"label": "keys"}],
                    "visible_text": ["CAFÉ"],
                    "personal_relevance": "objet personnel",
                    "image_path": "opaque/frame.jpg",
                },
                "source_refs": [f"obs{i}" for i in range(207)],
                "frame_refs": [f"frame{i}" for i in range(207)],
            }
        }),
    }
    projected = _prompt_turn(original)
    metadata = json.loads(projected["metadata_json"])
    source = metadata["source"]
    assert projected["turn_id"] == "vision_atom_1"
    assert projected["text"] == original["text"]
    assert source["state"] == {"labels": ["person", "keys"]}
    assert source["representative_extras"] == {
        "visible_text": ["CAFÉ"], "personal_relevance": "objet personnel"
    }
    assert "representative" not in source
    assert source["source_refs_manifest"]["count"] == 207
    assert source["frame_refs_manifest"]["count"] == 207
    assert "source_refs" not in source and "frame_refs" not in source
    # The durable source object is not mutated and remains available to coverage.
    assert len(json.loads(original["metadata_json"])["source"]["source_refs"]) == 207


def test_audio_prompt_projection_keeps_alignment_quality_without_duplicate_words():
    from mlomega_audio_elite.brain2_episode_windowing import _prompt_turn

    words = [
        {"word": "rendez-vous", "start": 1.0, "end": 1.5, "score": 0.9},
        {"word": "demain", "start": 1.6, "end": 2.0, "score": 0.7},
    ]
    original = {
        "turn_id": "t1", "text": "rendez-vous demain", "start_s": 1.0, "end_s": 2.0,
        "metadata_json": json.dumps({
            "kind": "deep_audio_transcript",
            "source": {
                "words": words,
                "whisperx_metadata": {
                    "original_text": "rendez-vous demain",
                    "segmentation_level": "atomic_utterance",
                    "segmentation_version": "3.2.2",
                    "whisperx_segment": {"words": words},
                },
                "offline_speaker_resolution": {"person_id": "UNKNOWN_VOICE_2"},
            },
        }),
    }
    projected = _prompt_turn(original)
    source = json.loads(projected["metadata_json"])["source"]
    assert projected["text"] == "rendez-vous demain"
    assert source["offline_speaker_resolution"]["person_id"] == "UNKNOWN_VOICE_2"
    assert source["word_alignment"]["count"] == 2
    assert source["word_alignment"]["start"] == 1.0
    assert source["word_alignment"]["end"] == 2.0
    assert source["word_alignment"]["mean_score"] == 0.8
    assert source["segmentation"] == {"level": "atomic_utterance", "version": "3.2.2"}
    assert "words" not in source and "whisperx_metadata" not in source


def test_episode_output_normalizer_extracts_ids_and_drops_uncited_meta_episode():
    from mlomega_audio_elite.brain2_episode_windowing import _normalise_episode_output
    from mlomega_audio_elite.night_orchestrator import PlanUnit

    output = {
        "episodes": [
            {
                "episode_type": "planning",
                "situation_summary": "Rendez-vous avec Karim le 14",
                "location": {},
                "evidence_turn_ids": [
                    {"turn_id": "t1", "text": "rendez-vous le 14"},
                    {"turn_id": "outside", "text": "hors fenêtre"},
                ],
            },
            {
                "episode_type": "technical_validation",
                "situation_summary": "commentaire du modèle",
                "evidence_turn_ids": [],
            },
        ],
        "missing_context": [],
    }
    normalized = _normalise_episode_output(output, [PlanUnit("t1", 10)])
    assert normalized is not None
    assert len(normalized["episodes"]) == 1
    episode = normalized["episodes"][0]
    assert episode["evidence_turn_ids"] == ["t1"]
    assert episode["start_turn_id"] == episode["end_turn_id"] == "t1"
    assert episode["location"] is None


def test_episode_ollama_schema_forbids_verbose_evidence_objects():
    from mlomega_audio_elite.brain2_episode_windowing import EPISODE_FORMAT_SCHEMA

    episode = EPISODE_FORMAT_SCHEMA["properties"]["episodes"]["items"]
    assert episode["additionalProperties"] is False
    assert episode["properties"]["evidence_turn_ids"] == {
        "type": "array", "items": {"type": "string"}
    }
    assert EPISODE_FORMAT_SCHEMA["additionalProperties"] is False


def test_v13_large_engine_schema_is_partitioned_and_merged_without_field_loss():
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_strict_v13_2 import _run_engine_partitioned

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE episodes(episode_id TEXT PRIMARY KEY,start_time TEXT)")
    con.execute("INSERT INTO episodes VALUES('ep1','2026-07-12T10:00:00+00:00')")

    class FieldLLM:
        model = "fake-field-llm"

        def __init__(self):
            self.calls = []

        def generate(self, prompt, *, output_budget):
            fields = list(prompt["schema_hint"])
            self.calls.append(fields)
            data = {}
            for field in fields:
                if field == "confidence":
                    data[field] = 0.8
                elif field in {"evidence", "counter_evidence", "secondary_emotions",
                               "thought_hypotheses", "state_transitions"}:
                    data[field] = [field]
                else:
                    data[field] = {"field": field}
            return LLMCallResult(ok=True, data=data)

    llm = FieldLLM()
    output = _run_engine_partitioned(
        con,
        engine="internal_state_engine",
        episode_id="ep1",
        person_id="me",
        bundle={"episode": {"episode_id": "ep1"}},
        prior={},
        window_llm=llm,
        context_window=16000,
        output_budget=1000,
    )
    schema_fields = set(ENGINE_SCHEMAS["internal_state_engine"])
    assert set(output) == schema_fields
    # Seven business fields, proactively split 2+2+2+1; common proof fields are
    # available in every call but merged once.
    assert len(llm.calls) == 4
    assert all(len(set(call) - {"evidence", "counter_evidence", "confidence"}) <= 2
               for call in llm.calls)


def test_build_episodes_windowed_runs_per_window_merges_and_covers():
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    turns = _turns(120)
    bundle = {"conversation": {"started_at": "2026-07-12T00:00:00+00:00"},
              "turns": turns, "source_spans": []}

    calls: list[list[str]] = []

    def safe_prompt(payload):
        return json.dumps(payload, default=str)

    class FakeWindowLLM:
        model = "fake-e64f"

        def generate(self, payload, *, output_budget):
            p = json.loads(payload["prompt"])
            ids = [t["turn_id"] for t in p["conversation_bundle"]["turns"]]
            calls.append(ids)
            return LLMCallResult(ok=True, data={
                "episodes": [{"episode_type": "other", "situation_summary": "s",
                              "evidence_turn_ids": ids, "start_turn_id": ids[0],
                              "end_turn_id": ids[-1], "confidence": 0.9}],
                "missing_context": [],
            })

    materialized = {}

    def materialize(c, cid, out):
        materialized["out"] = out
        return len(out["episodes"])

    stats = build_episodes_windowed(
        con, "conv1", bundle=bundle, person_id="me", package_date="2026-07-12",
        safe_prompt=safe_prompt, materialize=materialize,
        mission="M", schema={"episodes": [], "missing_context": []}, system="S",
        window_llm=FakeWindowLLM(), output_budget=256,
        budget_tokens=1200, target_turns=45, overlap=3,
    )
    assert stats["windows"] > 1  # 120 big turns -> several windows
    assert len(calls) == stats["windows"]  # V13 prompt run once per window
    assert stats["coverage_ok"] is True
    # Every turn is covered by evidence manifests attached to VALIDATED outputs
    # and persisted in the real E64-C output table.
    row = con.execute(
        "SELECT expected_count, covered_count, missing_count, ok FROM night_llm_coverage_v19"
    ).fetchone()
    assert row == (120, 120, 0, 1)
    assert con.execute("SELECT COUNT(*) FROM night_llm_window_outputs_v19").fetchone()[0] == stats["windows"]
    # episodes were materialised
    assert materialized["out"]["episodes"]


def test_windowed_coverage_accepts_valid_persisted_empty_result():
    # Zero episodes is a legitimate semantic result. Coverage is still real
    # because the validated empty result + its processed evidence manifest are
    # persisted atomically in night_llm_window_outputs_v19.
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    bundle = {"conversation": {}, "turns": _turns(60), "source_spans": []}

    class EmptyWindowLLM:
        model = "fake-empty"

        def generate(self, payload, *, output_budget):
            return LLMCallResult(
                ok=True, data={"episodes": [], "missing_context": ["nothing"]}
            )

    stats = build_episodes_windowed(
        con, "conv2", bundle=bundle, person_id="me", package_date="d",
        safe_prompt=lambda p: json.dumps(p, default=str),
        materialize=lambda c, cid, out: 0, mission="M",
        schema={"episodes": [], "missing_context": []}, system="S",
        window_llm=EmptyWindowLLM(), output_budget=256, budget_tokens=1200,
    )
    assert stats["coverage_ok"] is True
    assert stats["episodes"] == 0


def test_windowed_failure_is_not_credited_or_materialized():
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    bundle = {"conversation": {}, "turns": _turns(12), "source_spans": []}
    materialized = []

    class DownWindowLLM:
        model = "fake-down"

        def generate(self, payload, *, output_budget):
            return LLMCallResult(ok=False, error_kind="unavailable")

    with pytest.raises(RuntimeError, match="incomplete"):
        build_episodes_windowed(
            con, "conv-down", bundle=bundle, person_id="me", package_date="d",
            safe_prompt=lambda p: json.dumps(p, default=str),
            materialize=lambda *args: materialized.append(args), mission="M",
            schema={"episodes": [], "missing_context": []}, system="S",
            window_llm=DownWindowLLM(), output_budget=256, budget_tokens=1200,
        )
    assert materialized == []
    assert con.execute("SELECT COUNT(*) FROM night_llm_window_outputs_v19").fetchone()[0] == 0
    expected, covered, missing, ok = con.execute(
        "SELECT expected_count, covered_count, missing_count, ok FROM night_llm_coverage_v19"
    ).fetchone()
    assert expected == missing == 12
    assert covered == ok == 0


def test_dedupe_merges_identical_evidence_episodes():
    from mlomega_audio_elite.brain2_episode_windowing import _dedupe_episodes

    eps = [
        {"situation_summary": "a", "evidence_turn_ids": ["t1", "t2"], "start_time": "x"},
        {"situation_summary": "a-dup", "evidence_turn_ids": ["t2", "t1"], "start_time": "x"},
        {"situation_summary": "b", "evidence_turn_ids": ["t3"], "start_time": "y"},
    ]
    merged = _dedupe_episodes(eps)
    assert len(merged) == 2  # the two identical-evidence episodes collapse


def test_dedupe_merges_partial_boundary_episode_by_shared_evidence():
    from mlomega_audio_elite.brain2_episode_windowing import _dedupe_episodes

    eps = [
        {"episode_type": "planning", "participants": ["me"],
         "situation_summary": "début", "evidence_turn_ids": ["t40", "t41", "t42"]},
        {"episode_type": "planning", "participants": ["me"],
         "situation_summary": "suite", "evidence_turn_ids": ["t42", "t43", "t44"]},
    ]
    merged = _dedupe_episodes(eps)
    assert len(merged) == 1
    assert set(merged[0]["evidence_turn_ids"]) == {"t40", "t41", "t42", "t43", "t44"}
