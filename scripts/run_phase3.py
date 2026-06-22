from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clearlane.phase3.runner import run_phase3

MODES = [
    "lineage-only",
    "select-candidates",
    "capability-probe",
    "prepare-segments",
    "poll-once",
    "collect",
    "replay",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ClearLane Phase 3 (Whitefield live PIC).")
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--config", default="configs/phase3.yaml")
    parser.add_argument("--limit", type=int, default=20, help="Number of primary cells/segments to use.")
    parser.add_argument("--cycles", type=int, default=1, help="collect mode: number of poll cycles.")
    parser.add_argument("--interval-minutes", type=int, default=15, help="collect mode: minutes between cycles.")
    parser.add_argument("--fixture-dir", default=None, help="replay mode: Mappls fixture directory.")
    args = parser.parse_args(argv)

    result = run_phase3(
        args.mode,
        args.config,
        limit=args.limit,
        cycles=args.cycles,
        interval_minutes=args.interval_minutes,
        fixture_dir=args.fixture_dir,
    )
    print(json.dumps(result, indent=2, default=str))
    status = result.get("status", "FAIL")
    return 0 if status in {"PASS", "WARN", "REPLAY_PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
