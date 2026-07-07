from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume-safe PhoneOnly CloseDay worker")
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--live-session-id", required=True)
    args = parser.parse_args()

    from mlomega_audio_elite.v18_close_day import close_brainlive_day

    result = close_brainlive_day(
        person_id=args.person_id,
        live_session_id=args.live_session_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if str(result.get("status")) == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
