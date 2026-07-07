from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_turns_never_declares_created_at_dependency():
    db_source = (ROOT / "src/mlomega_audio_elite/db.py").read_text(encoding="utf-8")
    life_source = (ROOT / "src/mlomega_audio_elite/v18_life_model.py").read_text(encoding="utf-8")

    turns_schema = db_source.split("CREATE TABLE IF NOT EXISTS turns (", 1)[1].split(");", 1)[0]
    assert "created_at" not in turns_schema
    assert '"turns": ("turn_id", "conversation_id", ("start_s",))' in life_source
    assert '"turns": ("turn_id", "conversation_id", ("absolute_start", "created_at"))' not in life_source
