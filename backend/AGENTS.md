# AGENTS.md — `backend/` (LEGACY STUB — the app moved)

> **The FastAPI service is no longer here.** It now lives in **`api/clearlane/`** and
> is deployed through `api/index.py` (see `api/clearlane/AGENTS.md`). This directory
> is a leftover containerization shell — only `Dockerfile` and `requirements.txt`
> remain; there is no `backend/app/` package anymore.

## What's still here

| File | Status |
|---|---|
| `Dockerfile` | predates the move to `api/`. If you containerize, point it at `api/` and run `uvicorn clearlane.main:app --app-dir api`. |
| `requirements.txt` | mirror of the light API deps (`fastapi`, `pydantic`, `pymongo`, `dnspython`). The authoritative list is `api/requirements.txt`. |
| `.env` | local-dev env (read by `api/clearlane/db.py._load_dotenv()` as a fallback). |

## Where to actually work

- API code / routes / operational + force + v3 loops → **`api/clearlane/`**.
- How it deploys → `api/index.py` + `vercel.json` + `DEPLOY.md`.
- Run locally → `uvicorn clearlane.main:app --reload --port 8000 --app-dir api`.

Do not recreate `backend/app/`. If a doc or command still says
`uvicorn app.main:app`, it is stale — the entrypoint is `clearlane.main:app`.
