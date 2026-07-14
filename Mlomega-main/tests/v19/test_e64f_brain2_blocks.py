"""E64-F wave 1 building blocks: bundle-shape vision reduction + Ollama WindowLLM.

These are the additive, tested pieces the real Brain2 wiring uses: collapse the
event assembler's vision_timeline (the shape that produced 945 pseudo-turns) into
change atoms, and adapt the real OllamaJsonClient to the executor's WindowLLM
policy vocabulary (length -> subdivide, transient -> retry). No business prompt
and no close-day code is touched here.
"""

from __future__ import annotations

import copy
import json
import sqlite3

import pytest

from mlomega_audio_elite.night_orchestrator import (
    LLMCallResult,
    OllamaWindowLLM,
    reduce_vision_timeline,
)

pytestmark = pytest.mark.memory


def test_pattern_payload_accepts_contract_title_without_summary(tmp_path, monkeypatch):
    """The global merge may return the documented ``title`` field only."""
    from mlomega_audio_elite.brain2_strict_v13_2 import (
        _put_engine_payload,
        ensure_strict_v13_schema,
    )
    from mlomega_audio_elite.db import connect, write_transaction

    db_path = tmp_path / "pattern-title.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    ensure_strict_v13_schema()
    with connect(db_path) as con, write_transaction(con):
        con.execute(
            """INSERT INTO episodes(
                   episode_id,episode_type,situation_summary,created_at,updated_at
               ) VALUES(?,?,?,?,?)""",
            ("episode-title", "planning", "test", "2026-07-14T00:00:00Z", "2026-07-14T00:00:00Z"),
        )
        count = _put_engine_payload(
            con,
            "pattern_miner",
            "episode-title",
            "me",
            {
                "confidence": 0.8,
                "candidate_patterns": [
                    {
                        "pattern_type": "planning_habit",
                        "pattern_key": "prepare_before_meeting",
                        "title": "Prepare before meetings",
                        "description": "The user prepares before important meetings.",
                        "evidence_count": 2,
                    }
                ],
            },
        )
        row = con.execute(
            "SELECT pattern_key,title,description FROM candidate_patterns WHERE person_id='me'"
        ).fetchone()

    assert count == 1
    assert tuple(row) == (
        "prepare_before_meeting",
        "Prepare before meetings",
        "The user prepares before important meetings.",
    )


def test_hierarchical_json_does_not_repeat_embedded_schema(tmp_path, monkeypatch):
    """A legacy payload schema is control metadata, never an evidence leaf."""
    from mlomega_audio_elite.night_orchestrator import run_hierarchical_json
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.llm import LLMResult

    db_path = tmp_path / "schema-dedup.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    seen_prompts = []

    class Client:
        model = "fake-schema-dedup"

        def generate_json(self, system, prompt, schema_hint, timeout, **kwargs):
            seen_prompts.append(prompt)
            return LLMResult(ok=True, data={"items": []}, finish_reason="stop")

    schema = {"items": []}
    with connect(db_path) as con:
        result = run_hierarchical_json(
            stage_name="schema_dedup",
            person_id="me",
            package_date="2026-07-14",
            source_ref="test",
            system="system",
            payload={"mission": "test", "schema": schema, "evidence": "hello"},
            schema=schema,
            timeout=10,
            client=Client(),
            connection=con,
        )

    assert result == {"items": []}
    assert seen_prompts
    # One explicit output schema remains in the rendered prompt; the identical
    # payload copy is absent from shared/complete input.
    import json
    rendered = json.loads(seen_prompts[0])
    assert rendered["schema"] == schema
    assert "schema" not in str(rendered["input"].get("shared_context", {}))


# ------------------------------------------------- vision_timeline reduction
def _tl(source_id, time, *, label="person", track="t1", conf=0.9, summary=None):
    """A vision_timeline_json item (event assembler shape)."""
    return {
        "time": time,
        "summary": summary,
        "location_hint": None,
        "objects": [{"label": label, "track_id": track, "confidence": conf}],
        "visible_text": [],
        "frame_id": f"frame_{source_id}",
        "source_id": source_id,
        "source_table": "vision_scene_observations",
    }


def test_timeline_reduction_collapses_and_keeps_source_ids():
    items = [_tl(f"obs{i}", f"2026-07-12T00:00:{i:02d}+00:00", conf=0.5 + i * 0.01)
             for i in range(50)]
    atoms = reduce_vision_timeline(items)
    assert len(atoms) == 1  # 50 identical "person t1" frames -> one change atom
    assert atoms[0].count == 50
    # provenance: every source_id (observation_id) is carried, nothing dropped
    assert sorted(atoms[0].source_refs) == sorted(f"obs{i}" for i in range(50))


def test_timeline_reduction_opens_atom_on_real_change():
    items = [
        _tl("a", "t1", label="person", track="t1"),
        _tl("b", "t2", label="person", track="t1"),
        _tl("c", "t3", label="cup", track="t2"),
    ]
    atoms = reduce_vision_timeline(items)
    assert len(atoms) == 2
    assert atoms[0].source_refs == ("a", "b")
    assert atoms[1].source_refs == ("c",)


def test_timeline_reduction_lossless_across_a_session():
    items = (
        [_tl(f"p{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(200)]
        + [_tl(f"c{i}", f"2026-07-12T00:05:{i:02d}+00:00", label="cup", track="t9")
           for i in range(30)]
    )
    atoms = reduce_vision_timeline(items)
    covered = [r for a in atoms for r in a.source_refs]
    assert len(covered) == 230 and len(set(covered)) == 230  # nothing lost/duplicated
    assert len(atoms) == 2  # 230 frames -> 2 atoms


def test_raw_frame_rows_attach_to_semantic_atoms_without_splitting_state():
    semantic = [
        _tl(f"obs{i}", f"2026-07-12T00:00:0{i}.500+00:00")
        for i in range(3)
    ]
    raw = [
        {
            "source_id": f"raw{i}",
            "source_table": "vision_frames",
            "frame_id": f"raw-frame-{i}",
            "time": f"2026-07-12T00:00:0{i}.400+00:00",
            "summary": f"Raw visual frame: unique-{i}.jpg",
            "objects": None,
            "visible_text": None,
        }
        for i in range(3)
    ]
    interleaved = [x for pair in zip(raw, semantic) for x in pair]
    atoms = reduce_vision_timeline(interleaved)
    assert len(atoms) == 1
    assert set(atoms[0].source_refs) == {
        "raw0", "raw1", "raw2", "obs0", "obs1", "obs2",
    }
    assert {"raw-frame-0", "raw-frame-1", "raw-frame-2"} <= set(atoms[0].frame_refs)


def test_camera_only_timeline_is_one_evidence_range_not_filename_events():
    raw = [
        {
            "source_id": f"raw{i}", "source_table": "vision_frames",
            "frame_id": f"frame{i}", "time": f"t{i}",
            "summary": f"Raw visual frame: unique-{i}.jpg",
        }
        for i in range(20)
    ]
    atoms = reduce_vision_timeline(raw)
    assert len(atoms) == 1
    assert len(atoms[0].source_refs) == 20


# ------------------------------------------------------- OllamaWindowLLM map
class _FakeResult:
    def __init__(self, ok, data=None, error_kind=None, finish_reason=None):
        self.ok = ok
        self.data = data
        self.error_kind = error_kind
        self.finish_reason = finish_reason


class _FakeClient:
    def __init__(self, result):
        self._result = result
        self.last = None

    def generate_json(self, system, prompt, schema_hint, timeout, *, max_output_tokens, format_schema=None):
        self.last = {"system": system, "prompt": prompt, "budget": max_output_tokens,
                     "schema_hint": schema_hint, "format_schema": format_schema}
        return self._result


def _llm(result):
    return OllamaWindowLLM(system="SYS", client=_FakeClient(result))


def test_ok_result_maps_to_ok_callresult():
    out = _llm(_FakeResult(ok=True, data={"episodes": []})).generate({"prompt": "u"}, output_budget=512)
    assert out.ok and out.data == {"episodes": []}


def test_length_truncation_maps_to_length_kind():
    out = _llm(_FakeResult(ok=False, finish_reason="length")).generate("u", output_budget=512)
    assert not out.ok and out.error_kind == "length"


def test_real_client_truncated_output_kind_maps_to_length():
    out = _llm(
        _FakeResult(ok=False, error_kind="truncated_output")
    ).generate("u", output_budget=512)
    assert not out.ok and out.error_kind == "length"


def test_invalid_json_maps_to_invalid_json_kind():
    out = _llm(_FakeResult(ok=False, error_kind="invalid_json")).generate("u", output_budget=512)
    assert out.error_kind == "invalid_json"


def test_exception_maps_to_unavailable_transient():
    class _Boom:
        def generate_json(self, *a, **k):
            raise ConnectionError("down")

    out = OllamaWindowLLM(system="SYS", client=_Boom()).generate("u", output_budget=512)
    assert not out.ok and out.error_kind == "unavailable"


def test_budget_and_prompt_are_forwarded():
    client = _FakeClient(_FakeResult(ok=True, data={}))
    llm = OllamaWindowLLM(system="SYS", client=client)
    llm.generate({"prompt": "hello"}, output_budget=333)
    assert client.last["budget"] == 333
    assert client.last["prompt"] == "hello"
    assert client.last["system"] == "SYS"


def test_dynamic_window_schema_overrides_adapter_default():
    client = _FakeClient(_FakeResult(ok=True, data={}))
    llm = OllamaWindowLLM(
        system="SYS", client=client, schema_hint={"old": []}
    )
    llm.generate(
        {"prompt": "hello", "schema_hint": {"task_field": []}},
        output_budget=333,
    )
    assert client.last["schema_hint"] == {"task_field": []}


def test_sensor_turns_are_routed_without_removing_human_psychological_evidence():
    from mlomega_audio_elite.brain2_episode_windowing import (
        _partition_cognitive_and_sensor_turns,
    )

    sensor = {
        "turn_id": "vision-1", "text": "person detected",
        "metadata_json": json.dumps({
            "evidence_role": "system_observation_not_user_speech"
        }),
    }
    human = {
        "turn_id": "speech-1", "text": "je suis inquiet",
        "metadata_json": json.dumps({
            "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript"
        }),
    }
    cognitive, routed = _partition_cognitive_and_sensor_turns([sensor, human])
    assert [turn["turn_id"] for turn in cognitive] == ["speech-1"]
    assert [turn["turn_id"] for turn in routed] == ["vision-1"]


def test_whisper_word_arrays_are_projected_without_losing_alignment_proof():
    from mlomega_audio_elite.brain2_episode_windowing import _prompt_turn

    words = [
        {"word": "bonjour", "start": 1.0, "end": 1.4, "score": 0.8},
        {"word": "William", "start": 1.5, "end": 2.0, "score": 0.6},
    ]
    turn = {
        "turn_id": "speech-1", "text": "bonjour William",
        "metadata_json": json.dumps({
            "kind": "deep_audio_transcript",
            "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript",
            "source": {
                "words": words,
                "source_event_ids": ["raw-1", "raw-2"],
                "whisperx_metadata": {
                    "segmentation_level": "atomic_utterance",
                    "segmentation_version": "3.2.2",
                    "whisperx_segment": {"words": words},
                },
            },
        }),
    }
    projected = _prompt_turn(turn)
    metadata = json.loads(projected["metadata_json"])
    source = metadata["source"]
    assert "words" not in source and "whisperx_metadata" not in source
    assert source["word_alignment"]["count"] == 2
    assert source["word_alignment"]["start"] == 1.0
    assert source["word_alignment"]["end"] == 2.0
    assert source["source_event_count"] == 2
    assert "digest" not in source["word_alignment"]
    assert projected["text"] == "bonjour William"


def test_v13_engine_batches_by_local_index_and_keeps_every_episode_output():
    from mlomega_audio_elite.brain2_strict_v13_2 import _run_engine_episode_batches

    con = sqlite3.connect(":memory:")

    class BatchLLM:
        model = "fake-batch"

        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, output_budget):
            self.calls += 1
            body = json.loads(prompt["prompt"])
            schema = body["task_schema"]
            return LLMCallResult(ok=True, data={
                "results": [
                    {"task_index": task["task_index"], "output": copy.deepcopy(schema)}
                    for task in body["tasks"]
                ]
            })

    llm = BatchLLM()
    outputs = _run_engine_episode_batches(
        con,
        engine="context_resolver",
        conversation_id="conv1",
        person_id="me",
        package_date="2026-07-13",
        tasks={
            f"ep{i}": ({"episode": {"episode_id": f"ep{i}"}}, {})
            for i in range(3)
        },
        window_llm=llm,
        context_window=16000,
        output_budget=1000,
    )
    assert set(outputs) == {"ep0", "ep1", "ep2"}
    assert all("situation" in output for output in outputs.values())
    assert llm.calls == 2


def test_v13_episode_pack_serializes_bundle_once_and_keeps_all_engines():
    from mlomega_audio_elite.brain2_strict_v13_2 import _run_episode_engine_pack
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS

    con = sqlite3.connect(":memory:")

    class PackLLM:
        model = "fake-pack"

        def __init__(self):
            self.calls = 0

        def generate(self, prompt, *, output_budget):
            self.calls += 1
            body = json.loads(prompt["prompt"])
            return LLMCallResult(ok=True, data={
                "outputs": copy.deepcopy(body["output_schemas"])
            })

    llm = PackLLM()
    outputs = _run_episode_engine_pack(
        con,
        episode_id="ep1",
        conversation_id="conv1",
        person_id="me",
        package_date="2026-07-13",
        bundle={"episode": {"episode_id": "ep1"}, "turns": [{"text": "bonjour"}]},
        prior={},
        engines=["capture_engine", "language_signature_engine", "context_resolver"],
        window_llm=llm,
        context_window=16000,
        output_budget=2000,
    )
    assert set(outputs) == {
        "capture_engine", "language_signature_engine", "context_resolver"
    }
    for engine, output in outputs.items():
        assert set(ENGINE_SCHEMAS[engine]).issubset(output)
    assert llm.calls == 1


def test_v13_packed_source_bundle_never_feeds_materialized_outputs_back_in():
    from mlomega_audio_elite.brain2_strict_v13_2 import _stable_episode_source_bundle

    source = {
        "episode": {"episode_id": "ep1"},
        "conversation": {"conversation_id": "conv1"},
        "turns": [{"turn_id": "t1", "text": "preuve"}],
        "context_scope": {"episode_id": "ep1"},
        "context_addenda": {"vision": "stable"},
        "situations": [{"situation_id": "derived"}],
        "states": [{"state_id": "derived"}],
        "thoughts": [{"thought_id": "derived"}],
        "causes": [{"edge_id": "derived"}],
        "patterns": [{"pattern_id": "derived"}],
    }
    stable = _stable_episode_source_bundle(source)
    assert {"episode", "conversation", "turns", "context_scope", "context_addenda"} <= set(stable)
    assert stable["turns"][0]["turn_id"] == "t1"
    assert stable["situations"] == [] and stable["states"] == []
    assert stable["causes"] == [] and stable["patterns"] == []


def test_v13_episode_evidence_profile_is_total_and_routes_sensor_rows():
    from mlomega_audio_elite.brain2_strict_v13_2 import _episode_evidence_profile

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE turns(
            turn_id TEXT PRIMARY KEY, idx INTEGER, person_id TEXT,
            speaker_label TEXT, metadata_json TEXT
        );
        CREATE TABLE episode_evidence(episode_id TEXT, turn_id TEXT);
    """)
    con.execute(
        "INSERT INTO turns VALUES(?,?,?,?,?)",
        ("human", 0, "me", "SPEAKER_00", json.dumps({
            "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript"
        })),
    )
    con.execute(
        "INSERT INTO turns VALUES(?,?,?,?,?)",
        ("sensor", 1, None, "VISION", json.dumps({
            "evidence_role": "system_observation_not_user_speech"
        })),
    )
    con.executemany(
        "INSERT INTO episode_evidence VALUES(?,?)",
        [("ep1", "human"), ("ep1", "sensor")],
    )
    profile = _episode_evidence_profile(con, "ep1")
    assert profile["has_human_evidence"] is True
    assert profile["sensor_only"] is False
    assert profile["human_speaker_count"] == 1
    assert profile["evidence_turn_ids"] == ["human", "sensor"]


def test_v13_global_hierarchy_keeps_every_capsule_and_engine_contract():
    from mlomega_audio_elite.brain2_strict_v13_2 import _run_global_engine_hierarchy
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS

    class GlobalClient:
        model = "fake-global"

        def __init__(self):
            self.calls = 0

        def generate_json(self, system, prompt, schema_hint, timeout, *, max_output_tokens, format_schema=None):
            self.calls += 1
            return _FakeResult(ok=True, data=copy.deepcopy(schema_hint))

    con = sqlite3.connect(":memory:")
    client = GlobalClient()
    engines = ["pattern_miner", "prediction_engine"]
    outputs = _run_global_engine_hierarchy(
        con,
        conversation_id="conv1",
        person_id="me",
        package_date="2026-07-13",
        conversation={"conversation_id": "conv1"},
        episodes=[
            {"episode_id": "ep1", "episode_type": "planning", "situation_summary": "plan"},
            {"episode_id": "ep2", "episode_type": "conflict", "situation_summary": "désaccord"},
        ],
        profiles={
            "ep1": {"has_human_evidence": True, "evidence_turn_ids": ["t1"]},
            "ep2": {"has_human_evidence": True, "evidence_turn_ids": ["t2"]},
        },
        outputs_by_episode={
            "ep1": {"context_resolver": {"evidence": ["t1"]}},
            "ep2": {"context_resolver": {"evidence": ["t2"]}},
        },
        engines=engines,
        client=client,
    )
    assert set(outputs) == set(engines)
    for engine in engines:
        assert set(ENGINE_SCHEMAS[engine]).issubset(outputs[engine])
    assert client.calls == 1


def test_v13_global_hierarchy_splits_output_responsibilities_after_length():
    from mlomega_audio_elite.brain2_strict_v13_2 import _run_global_engine_hierarchy

    class SplitClient:
        model = "fake-global-split"

        def __init__(self):
            self.calls = 0

        def generate_json(self, system, prompt, schema_hint, timeout, *, max_output_tokens, format_schema=None):
            self.calls += 1
            outputs = schema_hint["outputs"]
            if len(outputs) > 1:
                return _FakeResult(ok=False, finish_reason="length")
            return _FakeResult(ok=True, data=copy.deepcopy(schema_hint))

    client = SplitClient()
    outputs = _run_global_engine_hierarchy(
        sqlite3.connect(":memory:"),
        conversation_id="conv-split", person_id="me",
        package_date="2026-07-13", conversation={},
        episodes=[{"episode_id": "ep1", "episode_type": "planning"}],
        profiles={"ep1": {"has_human_evidence": True, "evidence_turn_ids": ["t1"]}},
        outputs_by_episode={"ep1": {"context_resolver": {"evidence": ["t1"]}}},
        engines=["pattern_miner", "prediction_engine"],
        client=client,
    )
    assert set(outputs) == {"pattern_miner", "prediction_engine"}
    assert client.calls == 3  # combined attempt, then one call per responsibility


def test_hierarchical_merge_fails_fast_when_subdivision_cannot_reduce_fan_in():
    from mlomega_audio_elite.night_orchestrator import run_hierarchical_json

    class MergeClient:
        model = "fake-no-progress"

        def generate_json(self, system, prompt, schema_hint, timeout, *, max_output_tokens, format_schema=None):
            body = json.loads(prompt)
            partials = ((body.get("input") or {}).get("partial_outputs") or [])
            if body.get("level", 0) > 0 and len(partials) > 1:
                return _FakeResult(ok=False, finish_reason="length")
            return _FakeResult(ok=True, data=copy.deepcopy(schema_hint))

    payload = {
        "mission": "analyse",
        "evidence": [{"id": i, "text": "x" * 1200} for i in range(20)],
    }
    with pytest.raises(RuntimeError, match="(incomplete|merge)"):
        run_hierarchical_json(
            stage_name="no-progress", person_id="me", package_date="2026-07-13",
            source_ref="fixture", system="SYS", payload=payload,
            schema={"items": [], "confidence": 0.0}, timeout=1,
            client=MergeClient(), context_window=4096, output_budget=512,
            connection=sqlite3.connect(":memory:"),
        )


def test_hierarchical_json_windows_then_merges_with_final_source_coverage():
    from mlomega_audio_elite.night_orchestrator import run_hierarchical_json

    class SchemaClient:
        model = "fake-hierarchy"

        def __init__(self):
            self.calls = 0

        def generate_json(self, system, prompt, schema_hint, timeout, *, max_output_tokens, format_schema=None):
            self.calls += 1
            return _FakeResult(ok=True, data=copy.deepcopy(schema_hint))

    con = sqlite3.connect(":memory:")
    client = SchemaClient()
    schema = {"items": [], "missing_context": [], "confidence": 0.0}
    result = run_hierarchical_json(
        stage_name="test_hierarchy",
        person_id="me",
        package_date="2026-07-13",
        source_ref="fixture",
        system="SYS",
        payload={
            "mission": "analyse",
            "evidence": [{"id": i, "text": "x" * 900} for i in range(24)],
            "schema": schema,
        },
        schema=schema,
        timeout=1,
        client=client,
        context_window=4096,
        output_budget=512,
        connection=con,
    )
    assert set(result) == set(schema)
    assert client.calls > 1
    coverage = con.execute(
        "SELECT expected_count,missing_count,ok FROM night_llm_coverage_v19 WHERE stage_name='test_hierarchy'"
    ).fetchone()
    assert coverage and coverage[0] == 24 and coverage[1:] == (0, 1)


def test_hierarchical_json_splits_broad_output_schema_centrally_without_key_loss():
    from mlomega_audio_elite.night_orchestrator import run_hierarchical_json

    class ResponsibilityClient:
        model = "fake-responsibility-split"

        def __init__(self):
            self.schemas = []

        def generate_json(
            self, system, prompt, schema_hint, timeout, *,
            max_output_tokens, format_schema=None,
        ):
            self.schemas.append(tuple(schema_hint))
            return _FakeResult(ok=True, data=copy.deepcopy(schema_hint))

    schema = {
        f"capability_{index}": [{"description": "x" * 320, "evidence": []}]
        for index in range(10)
    }
    con = sqlite3.connect(":memory:")
    client = ResponsibilityClient()
    result = run_hierarchical_json(
        stage_name="broad_contract",
        person_id="me",
        package_date="2026-07-14",
        source_ref="fixture",
        system="SYS",
        payload={"mission": "analyse", "evidence": [{"id": "one"}]},
        schema=schema,
        timeout=1,
        client=client,
        connection=con,
    )

    assert set(result) == set(schema)
    assert len(client.schemas) > 1
    assert all(set(part) < set(schema) for part in client.schemas)
    assert set().union(*(set(part) for part in client.schemas)) == set(schema)
    coverage = con.execute(
        "SELECT expected_count,missing_count,ok FROM night_llm_coverage_v19 "
        "WHERE stage_name='broad_contract'"
    ).fetchone()
    assert coverage and coverage[0] == len(client.schemas) and coverage[1:] == (0, 1)


def test_schema_responsibilities_do_not_mix_semantic_objects_with_array_unions():
    from mlomega_audio_elite.night_orchestrator.hierarchical_json import (
        _schema_responsibility_parts,
    )

    schema = {
        "identity": {"summary": "", "confidence": 0.0},
        "routines": [],
        "places": [],
        "expressions": [],
        "needs": [],
        "warnings": [],
    }
    parts = _schema_responsibility_parts(schema)

    assert [list(part) for part in parts] == [
        ["identity"],
        ["routines", "places"],
        ["expressions", "needs"],
        ["warnings"],
    ]
    assert all(
        not (any(isinstance(value, dict) for value in part.values())
             and any(isinstance(value, list) for value in part.values()))
        for part in parts
    )


def test_output_cardinality_guard_preserves_budget_for_json_termination():
    from mlomega_audio_elite.night_orchestrator.hierarchical_json import (
        _output_cardinality_guard,
    )

    guard = _output_cardinality_guard(
        {"routines": [], "places": []}, output_budget=4096
    )
    assert guard["max_response_tokens"] == 3712
    assert 4 <= guard["max_items_per_top_level_list"] <= 16
    assert guard["max_values_per_nested_list"] == 8
    assert "source evidence remains durable" in guard["selection_rule"]


def test_live_ready_compiles_existing_canonical_model_without_another_llm(monkeypatch):
    import mlomega_audio_elite.brainlive_personal_model_v15_9 as personal_model

    raw = {
        "brain2_canonical_life_model": {
            "exports": [],
            "routines": [{
                "routine_name": "café du matin",
                "trigger_contexts_json": '["réveil"]',
                "observed_actions_json": '["prépare un café"]',
                "likely_needs_json": '["énergie"]',
                "preferred_conditions_json": "[]",
                "evidence_json": '[{"source_table":"turns","source_id":"t1"}]',
                "counter_evidence_json": "[]",
                "confidence": 0.8,
            }],
            "places": [], "needs_expectations": [],
            "expressions_states": [], "emotional_trajectories": [],
            "contextual_self": [{
                "self_state_summary": "préfère comprendre avant d'agir",
                "strengths_json": '["analyse"]', "confidence": 0.7,
            }],
            "live_prediction_hooks": [], "affordance_preferences": [],
        },
        "relationships": {"relationship_states": []},
    }

    monkeypatch.setattr(
        personal_model, "OllamaJsonClient",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not be constructed")),
    )
    result, error = personal_model.synthesize_live_ready_model(raw)

    assert error is None
    assert result["routines"][0]["name"] == "café du matin"
    assert result["routines"][0]["usual_actions"] == ["prépare un café"]
    assert result["routines"][0]["evidence"][0]["source_id"] == "t1"
    assert result["identity_model"]["stable_traits"] == ["analyse"]
    assert set(result) == set(personal_model.LIVE_READY_SCHEMA)


def test_hierarchical_json_windows_persisted_json_collections_instead_of_repeating_them():
    from mlomega_audio_elite.night_orchestrator import run_hierarchical_json

    class JsonColumnClient:
        model = "fake-json-column"

        def __init__(self):
            self.calls = 0

        def generate_json(
            self, system, prompt, schema_hint, timeout, *,
            max_output_tokens, format_schema=None,
        ):
            self.calls += 1
            return _FakeResult(ok=True, data=copy.deepcopy(schema_hint))

    con = sqlite3.connect(":memory:")
    client = JsonColumnClient()
    result = run_hierarchical_json(
        stage_name="persisted_json_evidence",
        person_id="me",
        package_date="2026-07-14",
        source_ref="fixture",
        system="SYS",
        payload={
            "mission": "analyse",
            "package": {
                "events_json": json.dumps([
                    {"id": index, "text": "x" * 700} for index in range(16)
                ])
            },
        },
        schema={"items": []},
        timeout=1,
        client=client,
        context_window=4096,
        output_budget=512,
        connection=con,
        lossless_array_merge=True,
    )

    assert result == {"items": []}
    assert client.calls > 1
    coverage = con.execute(
        "SELECT expected_count,missing_count,ok FROM night_llm_coverage_v19 "
        "WHERE stage_name='persisted_json_evidence'"
    ).fetchone()
    assert coverage == (16, 0, 1)


def test_evidence_leaf_index_resolves_short_id_and_exact_digest_alias():
    from mlomega_audio_elite.night_orchestrator import build_evidence_leaf_index

    row = {"turn_id": "turn-1", "text": "preuve"}
    index = build_evidence_leaf_index(
        {"raw_evidence": {"language": {"turns_recent": [row]}}}
    )
    short = next(key for key in index if len(key) == len("nightleaf_") + 16)
    entry = index[short]
    digest_alias = "nightleaf_" + entry["digest"]
    assert index[short]["value"] == row
    assert index[digest_alias]["ref_id"] == short
