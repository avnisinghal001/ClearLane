"""
Vercel Python serverless entry point for the ClearLane API.

Vercel's @vercel/python runtime detects the module-level ASGI ``app`` and serves
it directly (same pattern as vercel-labs/ai-sdk-preview-python-streaming). All
``/api/*`` requests are routed here by vercel.json; the FastAPI routes already
carry the ``/api`` prefix, so the original path matches unchanged.

State lives in MongoDB (see backend/app/db.py) because Vercel's filesystem is
read-only — set MONGODB_URI / MONGODB_DB in the project's Environment Variables.
"""
import sys
from pathlib import Path

# make the repo root importable so ``backend.app`` resolves on Vercel
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.main import app  # noqa: E402

# Vercel looks for a module-level ``app`` (ASGI). Keep this name.
__all__ = ["app"]
