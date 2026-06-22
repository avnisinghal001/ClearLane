from __future__ import annotations

from pathlib import Path

import pytest

from clearlane.phase3.common import load_config, repo_root

ROOT = repo_root(Path(__file__).resolve())
FIXTURE_DIR = ROOT / "tests" / "phase3" / "fixtures" / "mappls"


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture()
def config() -> dict:
    return load_config("configs/phase3.yaml", ROOT)


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def hotspots():
    import pandas as pd

    from clearlane.phase3 import schema

    df = pd.read_parquet(ROOT / "data/processed/phase2_h3_hotspots.parquet")
    return schema.canonicalize(df)


def read_fixture(name: str):
    import json

    return json.loads((FIXTURE_DIR / name).read_text())
