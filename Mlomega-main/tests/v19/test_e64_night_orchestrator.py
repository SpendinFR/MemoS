"""E64-A + E64-B tests: common contract + lossless deterministic reduction.

These prove the invariants that make the nightly orchestrator safe to build on:
no evidence loss, deterministic ids independent of any LLM attempt, real state
changes open atoms while confidence jitter does not, and a faithful multimodal
timeline. Nothing here touches a business prompt or the close-day path.
"""

from __future__ import annotations

import pytest

from mlomega_audio_elite.night_orchestrator import (
    build_audio_atoms,
    build_timeline,
    compute_coverage,
    content_digest,
    estimate_tokens_for_text,
    make_ref,
    reduce_vision_observations,
)
from mlomega_audio_elite.night_orchestrator.evidence_ref import refs_cover
from mlomega_audio_elite.night_orchestrator.loaders import (
    audio_segment_refs,
    vision_observation_refs,
)

pytestmark = pytest.mark.memory


# --------------------------------------------------------------- helpers/fixtures
def _obs(oid, ts, *, label="person", track="t1", conf=0.9, people=1, frame=None, text=None):
    """A vision_scene_observations-shaped row."""
    import json

    return {
        "observation_id": oid,
        "frame_id": frame or f"frame_{oid}",
        "live_session_id": "blsess_x",
        "objects_json": json.dumps([{"label": label, "track_id": track, "confidence": conf}]),
        "people_count": people,
        "visible_text_json": json.dumps(text or []),
        "scene_summary": None,
        "location_hint": None,
        "confidence": conf,
        "created_at": ts,
    }


# ------------------------------------------------------------------ EvidenceRef A
def test_evidence_id_is_deterministic_and_payload_independent():
    a = make_ref(source_table="t", source_pk="pk1", modality="vision",
                 payload_kind="scene_observation", payload={"x": 1})
    # Same table+pk, DIFFERENT payload (as if a later LLM run enriched it):
    b = make_ref(source_table="t", source_pk="pk1", modality="vision",
                 payload_kind="scene_observation", payload={"x": 999, "y": "z"})
    assert a.evidence_id == b.evidence_id  # id never depends on payload/LLM
    assert a.digest != b.digest  # but the content digest tracks the change
    c = make_ref(source_table="t", source_pk="pk2", modality="vision",
                 payload_kind="scene_observation", payload={"x": 1})
    assert c.evidence_id != a.evidence_id


def test_content_digest_is_order_insensitive():
    assert content_digest({"a": 1, "b": 2}) == content_digest({"b": 2, "a": 1})
    assert content_digest([1, 2]) != content_digest([2, 1])


# -------------------------------------------------------------- coverage manifest
def test_compute_coverage_blocks_on_missing():
    m = compute_coverage(stage_name="s", expected=["e1", "e2", "e3"],
                         covered=["e1"], quarantined=["e2"])
    assert m.missing == ("e3",)
    assert m.ok is False
    m2 = compute_coverage(stage_name="s", expected=["e1", "e2"],
                          covered=["e1"], quarantined=["e2"])
    assert m2.ok is True and m2.missing == ()


def test_refs_cover_transitive_via_parents():
    expected = [make_ref(source_table="t", source_pk=f"o{i}", modality="vision",
                         payload_kind="scene_observation", payload={"i": i}) for i in range(3)]
    parent_ids = [r.evidence_id for r in expected]
    derived = make_ref(source_table="vatom", source_pk="atom1", modality="derived",
                       payload_kind="vision_change_atom", payload={"k": 1},
                       parent_refs=parent_ids)
    covered = refs_cover(expected, [derived])
    assert covered == set(parent_ids)


# ------------------------------------------------------------ token estimate (A)
def test_estimate_tokens_rounds_up_and_honours_tokenizer():
    assert estimate_tokens_for_text("") == 0
    assert estimate_tokens_for_text("a" * 7) == 2  # ceil(7/3.5)
    assert estimate_tokens_for_text("whatever", tokenizer=lambda s: 42) == 42


# -------------------------------------------------------- vision reduction (B)
def test_identical_states_collapse_into_one_atom_lossless():
    rows = [_obs(f"o{i}", f"2026-07-12T00:00:{i:02d}+00:00", conf=0.8 + i * 0.001)
            for i in range(30)]
    atoms = reduce_vision_observations(rows)
    assert len(atoms) == 1  # 30 identical "person t1" observations -> 1 range
    atom = atoms[0]
    assert atom.count == 30
    assert atom.first_seen.endswith(":00+00:00")
    assert atom.last_seen.endswith(":29+00:00")
    # LOSSLESS: every observation id is covered exactly once.
    covered = list(atom.source_refs)
    assert sorted(covered) == sorted(f"o{i}" for i in range(30))
    assert len(covered) == len(set(covered))


def test_confidence_only_change_does_not_split():
    rows = [_obs("a", "t1", conf=0.10), _obs("b", "t2", conf=0.97)]
    atoms = reduce_vision_observations(rows)
    assert len(atoms) == 1  # confidence is jitter, not a cognitive event


def test_real_change_opens_new_atom_with_transitions():
    rows = [
        _obs("a", "t1", label="person", track="t1"),
        _obs("b", "t2", label="person", track="t1"),
        _obs("c", "t3", label="cup", track="t2"),  # real object change
        _obs("d", "t4", label="cup", track="t2"),
    ]
    atoms = reduce_vision_observations(rows)
    assert len(atoms) == 2
    assert atoms[0].source_refs == ("a", "b")
    assert atoms[1].source_refs == ("c", "d")
    # transitions vs previous atom
    assert "cup:t2" in atoms[1].entered
    assert "person:t1" in atoms[1].left


def test_people_count_and_text_changes_split():
    rows = [
        _obs("a", "t1", people=1),
        _obs("b", "t2", people=2),  # people count change
        _obs("c", "t3", people=2, text=["EXIT"]),  # OCR appears
    ]
    atoms = reduce_vision_observations(rows)
    assert len(atoms) == 3


def test_full_coverage_no_evidence_lost_across_changes():
    rows = (
        [_obs(f"p{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(400)]
        + [_obs(f"c{i}", f"2026-07-12T00:07:{i:02d}+00:00", label="cup", track="t9")
           for i in range(45)]
    )
    atoms = reduce_vision_observations(rows)
    all_refs = [r for atom in atoms for r in atom.source_refs]
    assert len(all_refs) == 445  # 400 + 45, nothing dropped
    assert len(set(all_refs)) == 445  # nothing duplicated
    # 445 raw observations collapsed to a tiny number of atoms.
    assert len(atoms) == 2
    # coverage manifest is green
    expected = vision_observation_refs(rows, person_id="me")
    parent_ids = {r.evidence_id for r in expected}
    # map atom source_refs (observation_ids) back to evidence ids
    from mlomega_audio_elite.night_orchestrator.evidence_ref import make_ref as mk
    produced = [
        mk(source_table="vatom", source_pk=atom.atom_id, modality="derived",
           payload_kind="vision_change_atom", payload=atom.to_dict(),
           parent_refs=[
               mk(source_table="vision_scene_observations", source_pk=oid,
                  modality="vision", payload_kind="scene_observation", payload={}).evidence_id
               for oid in atom.source_refs
           ])
        for atom in atoms
    ]
    covered = refs_cover(expected, produced)
    manifest = compute_coverage(stage_name="vision", expected=list(parent_ids),
                                covered=list(covered))
    assert manifest.ok is True


def test_reduction_is_deterministic():
    rows = [_obs(f"o{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(10)]
    a1 = reduce_vision_observations(list(rows))
    a2 = reduce_vision_observations(list(reversed(rows)))  # order shouldn't matter
    assert a1[0].atom_id == a2[0].atom_id
    assert a1[0].digest == a2[0].digest


# ------------------------------------------------------------- audio atoms (B)
def test_audio_atoms_kept_intact_and_ordered():
    segs = [
        {"segment_id": "s2", "transcript_text": "monde", "start_s": 5.0, "end_s": 7.0,
         "absolute_start": "2026-07-12T00:00:05+00:00", "person_id": "me",
         "source_path": "b.wav"},
        {"segment_id": "s1", "transcript_text": "bonjour", "start_s": 0.0, "end_s": 2.0,
         "absolute_start": "2026-07-12T00:00:00+00:00", "person_id": "me",
         "source_path": "a.wav"},
    ]
    atoms = build_audio_atoms(segs)
    assert [a.source_refs[0] for a in atoms] == ["s1", "s2"]  # time-ordered
    assert atoms[0].text == "bonjour"
    assert atoms[0].wav_refs == ("a.wav",)
    # one atom per segment, nothing merged
    assert len(atoms) == 2


# --------------------------------------------------------------- timeline (B)
def test_timeline_interleaves_by_time_without_flattening():
    audio = build_audio_atoms([
        {"segment_id": "s1", "text": "hi", "absolute_start": "2026-07-12T00:00:03+00:00"},
    ])
    vision = reduce_vision_observations([
        _obs("v1", "2026-07-12T00:00:01+00:00"),
        _obs("v2", "2026-07-12T00:00:02+00:00"),
    ])
    tl = build_timeline(audio, vision)
    assert [e.modality for e in tl] == ["vision", "audio"]  # vision at :01 before audio :03
    # vision entry is still an atom, NOT a conversation turn
    assert tl[0].atom.__class__.__name__ == "VisionChangeAtom"
    assert tl[1].atom.__class__.__name__ == "AudioTurnAtom"


def test_audio_segment_refs_shape():
    refs = audio_segment_refs(
        [{"segment_id": "s1", "person_id": "me", "absolute_start": "t"}], person_id="me"
    )
    assert refs[0].source_table == "brainlive_audio_segments_v154"
    assert refs[0].modality == "audio"
    assert refs[0].person_id == "me"
