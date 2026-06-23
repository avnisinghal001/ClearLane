from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clearlane.phase2.runner import run_phase2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ClearLane Phase 2 spatial hotspot pipeline.")
    parser.add_argument("--config", default="configs/phase2.yaml")
    parser.add_argument("--lineage-only", action="store_true", help="Validate Phase 1 handoff and population policy only.")
    parser.add_argument("--skip-models", action="store_true", help="Generate spatial outputs but skip Poisson/NB fitting.")
    args = parser.parse_args(argv)

    result = run_phase2(args.config, lineage_only=args.lineage_only, skip_models=args.skip_models)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
