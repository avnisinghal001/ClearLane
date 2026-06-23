"""Copy the latest generated Phase 3 outputs into frontend.phase3/data/ so the
standalone dashboard can fetch them over http.server (avoids file:// CORS issues).

Usage:
    python scripts/build_phase3_dashboard.py
    cd frontend.phase3 && python -m http.server 4399
    # open http://localhost:4399
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
DEST = ROOT / "frontend.phase3" / "data"
ARTIFACTS = ROOT / "artifacts" / "phase3"

FILES = [
    "phase3_whitefield_live_pic.json",
    "phase3_whitefield_live_pic.geojson",
    "phase3_whitefield_live_pic.csv",
    "phase3_whitefield_segment_catalog.geojson",
    "phase3_whitefield_candidates.csv",
    "phase3_citywide_historical_layer_manifest.json",
]

REPORT_FILES = {
    "phase3_final_report.json": "phase3_latest_final_report.json",
    "mappls_request_summary.json": "mappls_request_summary.json",
}


def latest_run() -> Path | None:
    if not ARTIFACTS.exists():
        return None
    for cand in sorted([p for p in ARTIFACTS.iterdir() if p.is_dir()], reverse=True):
        if (cand / "reports" / "phase3_final_report.json").exists():
            return cand
    return None


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []
    for name in FILES:
        src = PROC / name
        if src.exists():
            shutil.copy2(src, DEST / name)
            copied.append(name)
        else:
            missing.append(name)
    run_dir = latest_run()
    if run_dir is not None:
        for src_name, dest_name in REPORT_FILES.items():
            src = run_dir / "reports" / src_name
            if src.exists():
                shutil.copy2(src, DEST / dest_name)
                copied.append(dest_name)
    print(f"Copied {len(copied)} file(s) into {DEST}:")
    for c in copied:
        print(f"  ✓ {c}")
    if missing:
        print("Missing (run a Phase 3 poll/replay first):")
        for m in missing:
            print(f"  – {m}")
    print("\nNext:")
    print("  cd frontend.phase3 && python -m http.server 4399")
    print("  open http://localhost:4399")
    return 0 if copied else 1


if __name__ == "__main__":
    sys.exit(main())
