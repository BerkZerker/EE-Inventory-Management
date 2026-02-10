"""Shared test fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from database.models import (
    create_bike,
    create_invoice,
    create_invoice_items_bulk,
    create_product,
)

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
def sample_product(db: sqlite3.Connection) -> dict[str, Any]:
    """Insert and return a Trek Verve 3 test product."""
    product = create_product(
        db,
        sku="TREK-VERVE-3-BLU-M",
        model_name="Trek Verve 3",
        retail_price=1299.99,
        color="Blue",
        size="Medium",
    )
    assert product is not None
    return product


@pytest.fixture
def sample_invoice(db: sqlite3.Connection) -> dict[str, Any]:
    """Insert and return a pending invoice."""
    return create_invoice(
        db,
        invoice_ref="INV-2024-01-15-001",
        supplier="Trek Bikes",
        invoice_date="2024-01-15",
        total_amount=5000.00,
        shipping_cost=150.00,
        discount=50.00,
    )


@pytest.fixture
def sample_invoice_with_items(
    db: sqlite3.Connection,
    sample_invoice: dict[str, Any],
    sample_product: dict[str, Any],
) -> dict[str, Any]:
    """Insert an invoice with 2 line items and return the invoice dict with items."""
    items = create_invoice_items_bulk(
        db,
        sample_invoice["id"],
        [
            {
                "description": "Trek Verve 3 Blue Medium",
                "quantity": 2,
                "unit_cost": 800.00,
                "total_cost": 1600.00,
                "product_id": sample_product["id"],
            },
            {
                "description": "Trek Verve 3 Red Large",
                "quantity": 1,
                "unit_cost": 850.00,
                "total_cost": 850.00,
            },
        ],
    )
    sample_invoice["items"] = items
    return sample_invoice


@pytest.fixture
def sample_bike(
    db: sqlite3.Connection,
    sample_product: dict[str, Any],
) -> dict[str, Any]:
    """Insert and return one available bike."""
    return create_bike(
        db,
        serial_number="BIKE-00001",
        product_id=sample_product["id"],
        actual_cost=800.00,
        date_received="2024-01-20",
    )
