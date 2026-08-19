from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import connect, run_migrations


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    connection = connect(str(db_path))
    run_migrations(connection)
    yield connection
    connection.close()
