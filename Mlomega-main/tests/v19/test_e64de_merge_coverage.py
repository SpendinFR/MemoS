"""E64-D + E64-E tests: hierarchical merge, overlap dedup, anti-loss manifest.

Proves the guarantees Codex required BEFORE wiring real Brain2 (E64-F): a merge
can neither lose nor duplicate evidence, dedup is by evidence/semantic-key never
by text, and the coverage manifest re-reads the persisted outputs (not returned
ids) and blocks on any missing evidence.
"""

from __future__ import annotations

import sqlite3

import pytest

from mlomega_audio_elite.night_orchestrator import (
    MergeItem,
    build_coverage_report,
    covered_refs_from_outputs_table,
    hierarchical_merge,
    resolve_overlap,
    stage_stats,
)
from mlomega_audio_elite.night_orchestrator import checkpoint_store as cp

pytestmark = pytest.mark.memory


def _item(iid, key, refs, ts="", te="", **payload):
    return MergeItem(item_id=iid, semantic_key=key, evidence_refs=frozenset(refs),
                     time_start=ts, time_end=te, payload=payload)


# ----------------------------------------------------------------- overlap D
def test_overlap_dedup_by_shared_evidence_merges_and_unions_refs():
    # Same episode seen in two overlapping windows: same key, overlapping evidence.
    a = _item("w1_ep", "episode:cook", {"e1", "e2", "e3"}, ts="t01", te="t05")
    b = _item("w2_ep", "episode:cook", {"e3", "e4"}, ts="t04", te="t07")
    res = resolve_overlap([a, b])
    assert len(res.survivors) == 1
    surv = res.survivors[0]
    assert surv.evidence_refs == {"e1", "e2", "e3", "e4"}  # unioned, nothing lost
    assert res.dropped_to_survivor == {"w2_ep": "w1_ep"}


def test_overlap_not_deduped_by_text_only():
    # Identical text/payload but DIFFERENT evidence and no time overlap => distinct.
    a = _item("a", "episode:cook", {"e1"}, ts="t01", te="t02", text="stir the pot")
    b = _item("b", "episode:cook", {"e9"}, ts="t50", te="t51", text="stir the pot")
    res = resolve_overlap([a, b])
    assert len(res.survivors) == 2  # same text is NOT enough to merge


def test_different_semantic_key_never_merges():
    a = _item("a", "episode:cook", {"e1"}, ts="t01", te="t02")
    b = _item("b", "episode:clean", {"e1"}, ts="t01", te="t02")  # same evidence, diff key
    res = resolve_overlap([a, b])
    assert len(res.survivors) == 2


# ------------------------------------------------------- hierarchical merge D
def test_hierarchical_merge_folds_by_scene_then_conversation_lossless():
    items = [
        _item("i1", "ep:a", {"e1"}, ts="t01"),
        _item("i2", "ep:b", {"e2"}, ts="t02"),
        _item("i3", "ep:c", {"e3"}, ts="t03"),
    ]
    # level 1: scene (i1,i2 -> s1 ; i3 -> s2); level 2: day (everything -> d)
    scene_of = {"i1": "s1", "i2": "s1", "i3": "s2"}
    day_of = "d"
    merged = hierarchical_merge(
        items,
        level_key_fns=[lambda it: scene_of[it.item_id], lambda it: day_of],
        resolve_first=True,
    )
    assert len(merged) == 1  # one day root
    # every source evidence survives to the top
    assert merged[0].evidence_refs == {"e1", "e2", "e3"}


def test_merge_preserves_transitive_refs_after_overlap_resolution():
    items = [
        _item("w1", "ep:x", {"e1", "e2"}, ts="t01", te="t03"),
        _item("w2", "ep:x", {"e2", "e3"}, ts="t02", te="t04"),  # overlap dup
        _item("w3", "ep:y", {"e4"}, ts="t05", te="t06"),
    ]
    merged = hierarchical_merge(items, level_key_fns=[lambda it: "day"])
    assert merged[0].evidence_refs == {"e1", "e2", "e3", "e4"}


# --------------------------------------------------------- coverage manifest E
def test_coverage_all_buckets_and_missing_blocks():
    expected = ["e1", "e2", "e3", "e4", "e5", "e6"]
    report = build_coverage_report(
        stage_name="brain2",
        expected_ids=expected,
        covered_refs=["e1"],  # directly cited
        atom_parent_index={"vatom1": ["e2", "e3"]},  # represented by an atom
        overlap_deduplicated_refs=["e4"],  # folded into a survivor
        quarantined_reasons={"e5": "single unit truncates"},  # quarantined w/ reason
        # e6 -> nowhere
    )
    assert report.covered == ("e1",)
    assert report.represented_by_atom == ("e2", "e3")
    assert report.overlap_deduplicated == ("e4",)
    assert report.quarantined == (("e5", "single unit truncates"),)
    assert report.missing == ("e6",)
    assert report.ok is False


def test_coverage_ok_when_everything_accounted():
    report = build_coverage_report(
        stage_name="s", expected_ids=["e1", "e2"],
        covered_refs=["e1", "e2"],
    )
    assert report.ok and report.missing == ()


def test_each_expected_id_lands_in_exactly_one_bucket():
    # An id that is both covered and in an atom index counts once (covered wins).
    report = build_coverage_report(
        stage_name="s", expected_ids=["e1"],
        covered_refs=["e1"], atom_parent_index={"a": ["e1"]},
        overlap_deduplicated_refs=["e1"],
    )
    assert report.covered == ("e1",)
    assert report.represented_by_atom == ()
    assert report.overlap_deduplicated == ()


# ------------------------------ E: coverage RE-READ from the real outputs table
def _con():
    con = sqlite3.connect(":memory:")
    cp.ensure_schema(con)
    return con


def _seed_completed_window(con, key, output):
    cp.upsert_window(
        con, key=key, person_id="me", package_date="d", stage_name="brain2",
        input_digest="x", window_index=0, adapter_version="a", prompt_version="p",
        model="m", state=cp.STATE_RUNNING,
    )
    cp.record_output(con, key, output)
    cp.mark_state(con, key, cp.STATE_COMPLETED, output_digest="dg")


def test_coverage_reread_from_outputs_table_not_returned_ids():
    con = _con()
    _seed_completed_window(con, "k1", {"episodes": [{"evidence_refs": ["e1", "e2"]}]})
    _seed_completed_window(con, "k2", {"episodes": [{"evidence_refs": ["e3"]}]})

    def extract(output):
        return [r for ep in output.get("episodes", []) for r in ep.get("evidence_refs", [])]

    refs = covered_refs_from_outputs_table(
        con, person_id="me", package_date="d", stage_name="brain2", extract_refs=extract
    )
    assert refs == {"e1", "e2", "e3"}
    report = build_coverage_report(
        stage_name="brain2", expected_ids=["e1", "e2", "e3"], covered_refs=refs
    )
    assert report.ok


def test_stage_stats_aggregate_from_windows_table():
    con = _con()
    _seed_completed_window(con, "k1", {"x": 1})
    # a quarantined window
    cp.upsert_window(con, key="k2", person_id="me", package_date="d", stage_name="brain2",
                     input_digest="y", window_index=1, adapter_version="a", prompt_version="p",
                     model="m", state=cp.STATE_RUNNING, input_tokens=100)
    cp.bump_attempt(con, "k2")
    cp.mark_state(con, "k2", cp.STATE_QUARANTINED, error_text="llm_error:length finish=length")
    stats = stage_stats(con, person_id="me", package_date="d", stage_name="brain2")
    assert stats["windows"] == 2
    assert stats["completed"] == 1
    assert stats["quarantined"] == 1
    assert stats["truncations"] == 1  # the length error counted
