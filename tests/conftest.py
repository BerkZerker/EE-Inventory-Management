"""Shared test fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """In-memory SQLite database with the full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    schema = _SCHEMA_PATH.read_text()
    conn.executescript(schema)
    yield conn
    conn.close()


@pytest.fixture
def sample_product(db: sqlite3.Connection) -> dict[str, object]:
    """Insert and return a Trek Verve 3 test product."""
    db.execute(
        """
        INSERT INTO products (sku, model_name, color, size, retail_price)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("TREK-VERVE-3-BLU-M", "Trek Verve 3", "Blue", "Medium", 1299.99),
    )
    db.commit()
    row = db.execute("SELECT * FROM products WHERE sku = ?", ("TREK-VERVE-3-BLU-M",)).fetchone()
    assert row is not None
    return dict(row)
