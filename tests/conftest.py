"""Shared pytest fixtures for the StockKeep test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stockkeep.db import Database  # noqa: E402
from stockkeep.paths import ensure_dirs  # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKKEEP_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def paths(home):
    return ensure_dirs(home)


@pytest.fixture()
def db(paths):
    database = Database(paths.db_path)
    try:
        yield database
    finally:
        database.dispose()
