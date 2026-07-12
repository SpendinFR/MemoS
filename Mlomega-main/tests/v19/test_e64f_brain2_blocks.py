"""E64-F wave 1 building blocks: bundle-shape vision reduction + Ollama WindowLLM.

These are the additive, tested pieces the real Brain2 wiring uses: collapse the
event assembler's vision_timeline (the shape that produced 945 pseudo-turns) into
change atoms, and adapt the real OllamaJsonClient to the executor's WindowLLM
policy vocabulary (length -> subdivide, transient -> retry). No business prompt
and no close-day code is touched here.
"""

from __future__ import annotations

import pytest

from mlomega_audio_elite.night_orchestrator import (
    LLMCallResult,
    OllamaWindowLLM,
    reduce_vision_timeline,
)

pytestmark = pytest.mark.memory


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
        self.last = {"system": system, "prompt": prompt, "budget": max_output_tokens}
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
