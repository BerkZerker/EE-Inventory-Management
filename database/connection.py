"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_db(db_path: str) -> sqlite3.Connection:
    """Return a configured SQLite connection.

    Enables WAL mode, foreign keys, and sqlite3.Row factory.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database(db_path: str) -> None:
    """Create all tables by executing schema.sql.

    Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(db_path)
    schema_sql = _SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    conn.close()
