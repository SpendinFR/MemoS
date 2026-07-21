"""Two PRO robustness levers for the real close-day bottleneck:

1. ``MLOMEGA_PRO_FANOUT_COLD_CONCURRENT`` lets the DAG-level engine fan-out run
   concurrently even on a COLD cache probe (trade cache-hit rate for wall-clock);
   default OFF keeps the historic cost-optimised sequential-on-cold behaviour.
2. In PRO close-day the subtheme-evidence contract tolerates the local 9B citing
   evidence OUTSIDE a subtheme's own turns (e.g. a deep-vision addendum backing a
   visual subtheme): the out-of-membership ids are dropped (fallback to the
   subtheme's own turns) instead of hard-blocking the whole close-day.  Local
   (no flag) keeps the strict raise byte-for-byte.
"""
from __future__ import annotations

import pytest

from mlomega_audio_elite.brain2_strict_v13_2 import (
    _pro_fanout_cold_concurrent_enabled,
)
from mlomega_audio_elite.brain2_conversation_episode import (
    ConversationEpisodeContractError,
    normalize_conversation_episode,
)


# --------------------------------------------------------------------------- #
# Lever 1: cold-concurrent fan-out gate
# --------------------------------------------------------------------------- #
def test_cold_concurrent_default_off(monkeypatch):
    monkeypatch.delenv("MLOMEGA_PRO_FANOUT_COLD_CONCURRENT", raising=False)
    assert _pro_fanout_cold_concurrent_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_cold_concurrent_enabled(monkeypatch, value):
    monkeypatch.setenv("MLOMEGA_PRO_FANOUT_COLD_CONCURRENT", value)
    assert _pro_fanout_cold_concurrent_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_cold_concurrent_disabled_values(monkeypatch, value):
    monkeypatch.setenv("MLOMEGA_PRO_FANOUT_COLD_CONCURRENT", value)
    assert _pro_fanout_cold_concurrent_enabled() is False


# --------------------------------------------------------------------------- #
# Lever 2: subtheme evidence tolerance (PRO) — real Gate B failure reproduced
# --------------------------------------------------------------------------- #
_TURNS = [{"turn_id": "t1"}, {"turn_id": "t2"}]


def _output(evidence):
    return {
        "conversation_episode": {
            "title": "Silence et flou visuel",
            "situation_summary": "Une courte conversation avec une scene visuelle.",
            "participants": ["UNKNOWN_VOICE_1"],
            "confidence": 0.8,
            "subthemes": [
                {
                    "turn_ids": ["t1", "t2"],
                    "evidence_turn_ids": evidence,
                    "title": "Silence et flou visuel",
                    "summary": "Le locuteur observe un flou visuel.",
                    "subtheme_type": "other",
                }
            ],
        }
    }


def test_local_raises_on_out_of_membership_evidence(monkeypatch):
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    with pytest.raises(ConversationEpisodeContractError) as exc:
        normalize_conversation_episode(
            _output(["t1", "v18deepaddendum_8df0ea70c62f0b8a"]), _TURNS
        )
    assert "subtheme_0_invalid_evidence" in str(exc.value)


def test_pro_drops_out_of_membership_evidence_keeps_valid(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    result = normalize_conversation_episode(
        _output(["t1", "v18deepaddendum_8df0ea70c62f0b8a"]), _TURNS
    )
    sub = result["episodes"][0]["subthemes"][0]
    # The valid in-membership turn is kept; the vision addendum is dropped.
    assert sub["evidence_turn_ids"] == ["t1"]


def test_pro_falls_back_to_turns_when_all_evidence_out_of_membership(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    result = normalize_conversation_episode(
        _output(["v18deepaddendum_8df0ea70c62f0b8a"]), _TURNS
    )
    sub = result["episodes"][0]["subthemes"][0]
    # No in-membership evidence survived -> the subtheme's own turns are the evidence.
    assert sub["evidence_turn_ids"] == ["t1", "t2"]


def test_pro_leaves_fully_valid_evidence_unchanged(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    result = normalize_conversation_episode(_output(["t1", "t2"]), _TURNS)
    sub = result["episodes"][0]["subthemes"][0]
    assert sub["evidence_turn_ids"] == ["t1", "t2"]
