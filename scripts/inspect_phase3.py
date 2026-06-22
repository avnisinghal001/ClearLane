from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd  # noqa: E402

ARTIFACT_ROOT = ROOT / "artifacts" / "phase3"


def latest_run() -> Path | None:
    if not ARTIFACT_ROOT.exists():
        return None
    for cand in sorted([p for p in ARTIFACT_ROOT.iterdir() if p.is_dir()], reverse=True):
        if (cand / "reports" / "phase3_final_report.json").exists():
            return cand
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the latest Phase 3 run + outputs.")
    parser.add_argument("--run-dir", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir) if args.run_dir else latest_run()
    if run_dir is None:
        print("No Phase 3 run found.")
        return 1
    final = json.loads((run_dir / "reports" / "phase3_final_report.json").read_text())
    print("=" * 70)
    print(f"Phase 3 run: {final['run_id']}  mode={final['mode']}  status={final['status']}")
    print(f"data_mode={final['data_mode']}")
    print("CITYWIDE HISTORICAL COVERAGE: BENGALURU")
    print("LIVE TRAFFIC COVERAGE: WHITEFIELD DEMO REGION")
    print("=" * 70)
    for key in (
        "phase2_lineage", "coverage", "candidate_selection", "segments",
        "mappls", "poll_cycle", "api_usage", "mappls_request_summary",
    ):
        if key in final:
            print(f"\n[{key}]")
            print(json.dumps(final[key], indent=2, default=str))
    if final.get("data_mode") == "REPLAY":
        print("\nThis run used replay fixtures. It did not call Mappls live APIs.")
    elif final.get("mappls_request_summary", {}).get("live_mappls_api_calls_attempted", 0) > 0:
        print("\nThis run attempted live Mappls API calls.")
    pic_path = ROOT / "data/processed/phase3_whitefield_live_pic.csv"
    if pic_path.exists():
        pic = pd.read_csv(pic_path)
        computed = pic[pic.get("pic_status") == "COMPUTED"] if "pic_status" in pic else pic
        if len(computed):
            cols = [c for c in ["pic_rank", "h3_res10", "pic_score", "congestion_severity",
                                "congestion_label", "normalized_propensity"] if c in computed.columns]
            print("\n[top PIC cells]")
            print(computed.sort_values("pic_rank").head(10)[cols].to_string(index=False))
    print("\nWarnings:", final.get("warnings"))
    print("Errors:", final.get("errors"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
