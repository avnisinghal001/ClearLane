"""
Migrate ClearLane v3's precomputed artifacts into MongoDB so the Vercel serverless
API can serve them off a read-only filesystem.

It uploads every JSON artifact from data/processed/v3 (falling back to
frontend.v3/public/demo-v3 for anything missing) into the ``artifacts`` collection
as ``{_id: "v3/<name>.json", data: <parsed json>}`` (the namespaced key the v3 API
reads), then seeds the force-command rosters + v3 indexes.

Usage:
    # set the connection string first (PowerShell):  $env:MONGODB_URI = "mongodb+srv://..."
    python scripts/migrate_to_mongo.py
    python scripts/migrate_to_mongo.py --reseed-force   # also wipe + reseed rosters

Reads MONGODB_URI / MONGODB_DB from the environment (or a root .env file).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))   # the FastAPI app package lives in api/clearlane


# tiny .env loader (no python-dotenv dependency required)
def _load_env():
    for p in (ROOT / ".env", ROOT / "ml.v3" / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

from clearlane import db  # noqa: E402

PROC = ROOT / "data" / "processed" / "v3"
DEMO = ROOT / "frontend.v3" / "public" / "demo-v3"


def _artifact_names() -> list[str]:
    names: set[str] = set()
    for d in (PROC, DEMO):
        if d.exists():
            names.update(p.name for p in d.glob("*.json"))
    return sorted(names)


def _read_local(name: str):
    for d in (PROC, DEMO):
        p = d / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"  ! {name}: failed to parse ({e})")
    return None


def migrate_artifacts() -> int:
    if not db.mongo_enabled():
        print("ERROR: MONGODB_URI is not set (and pymongo must be installed).")
        print("       Set it, e.g.  export MONGODB_URI='mongodb+srv://user:pass@host/'")
        sys.exit(1)

    names = _artifact_names()
    print(f"Uploading {len(names)} v3 artifacts to "
          f"{db.MONGODB_DB}.{db.ARTIFACTS_COLLECTION} (keyed v3/<name>) ...")
    n = 0
    for name in names:
        data = _read_local(name)
        if data is None:
            print(f"  - {name}: skipped (empty/unreadable)")
            continue
        db.save_v3_artifact(name, data)        # writes _id = "v3/<name>"
        src = PROC if (PROC / name).exists() else DEMO
        print(f"  + v3/{name}  ({(src / name).stat().st_size // 1024} KB)")
        n += 1
    print(f"Done: {n} v3 artifacts in MongoDB.")
    return n


def seed_force(reseed: bool):
    from clearlane import force, v3

    if reseed:
        print("Wiping fz_stations / fz_officers / fz_sessions ...")
        for c in ("fz_stations", "fz_officers", "fz_sessions"):
            db.col(c).delete_many({})
        db.col("counters").delete_many({"_id": "fz_officers"})

    force.init_db()  # creates indexes + seeds rosters from stations.json if empty
    v3.init_db()     # v3 collection indexes + lazy-recompute lock doc
    n_st = db.col("fz_stations").estimated_document_count()
    n_off = db.col("fz_officers").estimated_document_count()
    print(f"Force command ready: {n_st} stations, {n_off} officers.")


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)  # show progress live
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Migrate ClearLane v3 artifacts to MongoDB.")
    ap.add_argument("--reseed-force", action="store_true",
                    help="wipe and reseed the force-command rosters")
    ap.add_argument("--skip-artifacts", action="store_true",
                    help="only (re)seed force command, don't re-upload artifacts")
    args = ap.parse_args()

    print(f"MongoDB: {db.MONGODB_DB}  (uri set: {bool(db.MONGODB_URI)})")
    if not args.skip_artifacts:
        migrate_artifacts()
    seed_force(args.reseed_force)
    print("\nMigration complete. Verify with:  GET /api/health")


if __name__ == "__main__":
    main()
