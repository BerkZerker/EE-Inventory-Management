"""Schema smoke tests."""

from __future__ import annotations

import sqlite3

import pytest

EXPECTED_TABLES = [
    "products",
    "invoices",
    "invoice_items",
    "bikes",
    "serial_counter",
    "webhook_log",
]


def test_all_tables_exist(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    table_names = {row["name"] for row in rows}
    for table in EXPECTED_TABLES:
        assert table in table_names, f"Missing table: {table}"


def test_serial_counter_initialised(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT next_serial FROM serial_counter WHERE id = 1").fetchone()
    assert row is not None
    assert row["next_serial"] == 1


def test_foreign_key_enforcement(db: sqlite3.Connection) -> None:
    """Inserting a bike with a non-existent product_id should fail."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO bikes (serial_number, product_id, actual_cost)
            VALUES (?, ?, ?)
            """,
            ("BIKE-99999", 9999, 100.0),
        )


def test_product_insert_and_query(
    db: sqlite3.Connection, sample_product: dict[str, object]
) -> None:
    assert sample_product["sku"] == "TREK-VERVE-3-BLU-M"
    assert sample_product["model_name"] == "Trek Verve 3"
    assert sample_product["retail_price"] == 1299.99


def test_invoice_status_check_constraint(db: sqlite3.Connection) -> None:
    """Only pending/approved/rejected should be allowed."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO invoices (invoice_ref, supplier, invoice_date, status)
            VALUES (?, ?, ?, ?)
            """,
            ("INV-TEST", "Test Supplier", "2024-01-01", "invalid_status"),
        )


def test_bike_status_check_constraint(
    db: sqlite3.Connection, sample_product: dict[str, object]
) -> None:
    """Only available/sold/returned/damaged should be allowed."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO bikes (serial_number, product_id, actual_cost, status)
            VALUES (?, ?, ?, ?)
            """,
            ("BIKE-00001", sample_product["id"], 500.0, "broken"),
        )
