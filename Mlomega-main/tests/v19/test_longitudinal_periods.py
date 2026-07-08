"""E54: the close-day longitudinal stage runs week/month rollups on complete periods.

Unit-level check of `_due_longitudinal_periods` — the pure date logic that decides
which periodic rollups a given closed day triggers, without running the (heavy)
consolidation itself.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mlomega_audio_elite.v18_close_day import _due_longitudinal_periods as DUE  # noqa: E402


def test_midweek_day_runs_day_only():
    # 2026-07-08 is a Wednesday, not a month end.
    assert DUE("2026-07-08") == []


def test_sunday_triggers_week():
    # 2026-07-12 is a Sunday (ISO end of week), mid-month.
    assert DUE("2026-07-12") == ["week"]


def test_last_day_of_month_triggers_month():
    # 2026-04-30 is a Thursday and the last day of April.
    assert DUE("2026-04-30") == ["month"]


def test_sunday_that_is_also_month_end_triggers_both():
    # 2026-05-31 is a Sunday AND the last day of May.
    assert DUE("2026-05-31") == ["week", "month"]


def test_december_31_month_rollover():
    # Year boundary still counts as a month end (Dec -> Jan).
    assert "month" in DUE("2026-12-31")


def test_bad_input_is_day_only():
    assert DUE("") == []
    assert DUE("not-a-date") == []
    assert DUE(None) == []  # type: ignore[arg-type]
