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

KNOWN_TEST_SECRETS = [
    "01c4a1c9-24bc-4712-b8a3-62eb874b24ac",  # sample access token (parent-dir fixture)
    "96dHZVzsAusnIs3erx_kNfcBVzbFlJbzFwTQAArNjL4ZN2i0vpGczfvIfEvejO9ZRWAZrHJUPwTDxI5fqtL3eWNRZJofo9Db",
]


def latest_run(artifact_root: Path) -> Path | None:
    if not artifact_root.exists():
        return None
    for cand in sorted([p for p in artifact_root.iterdir() if p.is_dir()], reverse=True):
        if (cand / "reports" / "phase3_final_report.json").exists():
            return cand
    return None


def _scan_secret_leak(run_dir: Path) -> list[str]:
    hits = []
    for p in run_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in {".json", ".csv", ".geojson", ".txt", ".log"}:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for secret in KNOWN_TEST_SECRETS:
                if secret in text:
                    hits.append(f"{p.name}: leaked secret")
    return hits


def verify(run_dir: Path) -> tuple[bool, list[str], dict]:
    problems: list[str] = []
    final = json.loads((run_dir / "reports" / "phase3_final_report.json").read_text())
    status = final.get("status")
    mode = final.get("mode")
    data_mode = final.get("data_mode")

    if status not in {"PASS", "WARN", "REPLAY_PASS"}:
        problems.append(f"status={status}")

    # required reports present for the mode
    required = ["phase2_lineage_validation.json", "input_schema_report.json", "phase3_final_report.json"]
    if mode in {"select-candidates", "prepare-segments", "poll-once", "collect", "replay"}:
        required.append("whitefield_candidate_selection_report.json")
    if mode in {"poll-once", "collect", "replay"}:
        required += ["polling_report.json", "congestion_report.json", "pic_report.json"]
    for r in required:
        if not (run_dir / "reports" / r).exists():
            problems.append(f"missing report {r}")

    # lineage: no raw phase1 access
    lin = json.loads((run_dir / "reports" / "phase2_lineage_validation.json").read_text())
    if lin.get("raw_phase1_data_used"):
        problems.append("raw Phase 1 data used")
    if not lin.get("checksum_match", True):
        problems.append("phase2 checksum mismatch")

    # PIC bounds + single poll cycle + replay labels
    pic_path = ROOT / "data/processed/phase3_whitefield_live_pic.parquet"
    if mode in {"poll-once", "collect", "replay"} and pic_path.exists():
        pic = pd.read_parquet(pic_path)
        computed = pic[pic.get("pic_status") == "COMPUTED"] if "pic_status" in pic else pic.iloc[0:0]
        if len(computed):
            if (computed["pic_score"] < 0).any() or (computed["pic_score"] > 1).any():
                problems.append("PIC out of [0,1]")
            if "poll_cycle_id" in computed and computed["poll_cycle_id"].nunique() > 1:
                problems.append("PIC ranking mixes poll cycles")
        # replay outputs must not be labelled LIVE
        pic_json = ROOT / "data/processed/phase3_whitefield_live_pic.json"
        if data_mode == "REPLAY" and pic_json.exists():
            if '"data_mode": "LIVE"' in pic_json.read_text():
                problems.append("replay output labelled LIVE")

    # secret leakage
    problems.extend(_scan_secret_leak(run_dir))

    return (len(problems) == 0), problems, final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the latest completed Phase 3 run.")
    parser.add_argument("--run-dir", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir) if args.run_dir else latest_run(ARTIFACT_ROOT)
    if run_dir is None:
        print("FAIL: no completed Phase 3 run found.")
        return 1

    ok, problems, final = verify(run_dir)
    if ok:
        mappls = final.get("mappls", {})
        print(f"PASS: Phase 3 latest completed run {final['run_id']} status={final['status']}")
        print("Region: WHITEFIELD_DEMO")
        print(f"Mode: {final.get('mode')}  Data mode: {final.get('data_mode')}")
        if mappls.get("selected_live_source"):
            print(f"Live source: {str(mappls.get('selected_live_source')).upper()}")
        cs = final.get("candidate_selection", {})
        if cs:
            print(f"Primary cells: {cs.get('primary_candidates')}  Reserve: {cs.get('reserve_candidates')}")
        pic = final.get("poll_cycle", {})
        if pic:
            print(f"Valid observations: {pic.get('valid_observations')}")
        return 0
    print(f"FAIL: Phase 3 run {final.get('run_id')} has problems:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
