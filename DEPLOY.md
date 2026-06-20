# Deploying ClearLane to Vercel (monorepo)

One repo → one Vercel project. The Vite frontend is built to static files and the
FastAPI backend runs as a single Python serverless function. All mutable state and
the precomputed ML artifacts live in **MongoDB** (Vercel's filesystem is
read-only), so nothing is written to disk at runtime.

```
ClearLane/
├── api/index.py            # Vercel Python serverless entry (exposes FastAPI `app`)
├── backend/app/            # main.py (reads) · operational.py · force.py · db.py (Mongo)
├── frontend/               # Vite + React → built to frontend/dist (static)
├── scripts/migrate_to_mongo.py
├── requirements.txt        # LIGHT deps for the serverless function (fastapi, pymongo…)
├── requirements-ml.txt     # heavy ML pipeline deps (NOT deployed)
├── vercel.json             # build + routing (/api → function)
└── package.json            # root build orchestration
```

## How requests flow

- The frontend calls **same-origin** `/api/*` (no hard-coded host — `VITE_API_BASE`
  is empty). On Vercel, `vercel.json` rewrites `/api/(.*)` → the Python function.
- Every read endpoint loads its JSON artifact from MongoDB (`artifacts`
  collection), falling back to the bundled `frontend/public/demo/*.json` if Mongo
  is unreachable, then to the offline demo in the browser. The dashboard always
  renders.
- Writes (complaints, dispatches, officer feedback, RBAC auth, rosters) persist to
  MongoDB collections. If `MONGODB_URI` is missing they return `503` and the
  frontend transparently falls back to its in-browser offline engine.

## 1. Provision MongoDB

Create a free **MongoDB Atlas** cluster and a database user. Allow network access
from anywhere (`0.0.0.0/0`) so Vercel's serverless IPs can connect. Grab the SRV
connection string:

```
mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

## 2. Seed MongoDB (run once, locally)

```bash
pip install -r requirements.txt          # fastapi + pymongo + dnspython
export MONGODB_URI="mongodb+srv://...."   # or put it in .env / backend/.env
export MONGODB_DB="clearlane"
python scripts/migrate_to_mongo.py        # uploads ~19 artifacts + seeds rosters
# re-seed force rosters from scratch:  python scripts/migrate_to_mongo.py --reseed-force
```

Env var names are flexible — `MONGODB_URI`, `MONGO_URL`, `MONGOURI` and
`MONGO_URI` all work; `MONGODB_DB` or `MONGO_DB` for the database name.

## 3. Configure the Vercel project

Import the repo in Vercel. The settings come from `vercel.json` automatically:

- **Build Command:** `npm run build --prefix frontend`
- **Output Directory:** `frontend/dist`
- **Install Command:** `npm install --prefix frontend`

Add **Environment Variables** (Production + Preview):

| Key | Value |
|-----|-------|
| `MONGODB_URI` | your Atlas SRV string |
| `MONGODB_DB`  | `clearlane` |
| `CLEARLANE_LLM` | `1` *(optional — enables the LLM copilot)* |
| `ANTHROPIC_API_KEY` | `sk-ant-…` *(optional, with the above)* |

Deploy. Verify the API with `GET https://<your-app>.vercel.app/api/health` —
it should report `"source": "mongodb"`.

## Local development

```bash
# backend (terminal 1)
pip install -r backend/requirements.txt
export MONGODB_URI="mongodb+srv://..."          # optional; without it writes 503
uvicorn app.main:app --reload --port 8000       # from backend/

# frontend (terminal 2) — Vite proxies /api → http://localhost:8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

Regenerating the ML artifacts (only when the pipeline changes), then re-uploading:

```bash
pip install -r requirements-ml.txt
cd ml/pipeline && python run_all.py
python scripts/migrate_to_mongo.py               # push refreshed artifacts to Mongo
```

## Demo logins (Force Command RBAC)

- Government super-admin: `govt` / `govt`
- Per-station command: `<station-slug>` / `<station-slug>` (slug == username == password)
