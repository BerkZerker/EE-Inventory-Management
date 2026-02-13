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


def _migrate_invoice_fee_columns(conn: sqlite3.Connection) -> None:
    """Add credit_card_fees, tax, other_fees columns if they don't exist."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()
    }
    for col in ("credit_card_fees", "tax", "other_fees"):
        if col not in existing:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {col} REAL DEFAULT 0")
    conn.commit()


def _migrate_brand_model(conn: sqlite3.Connection) -> None:
    """Split model_name into brand + model columns if they don't exist yet."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()
    }
    if "brand" in existing:
        return  # Already migrated

    conn.execute("ALTER TABLE products ADD COLUMN brand TEXT DEFAULT ''")
    conn.execute("ALTER TABLE products ADD COLUMN model TEXT DEFAULT ''")

    # Populate from existing model_name: first word = brand, rest = model
    if "model_name" in existing:
        rows = conn.execute("SELECT id, model_name FROM products").fetchall()
        for row in rows:
            parts = (row[1] or "").split(None, 1)
            brand = parts[0] if parts else ""
            model = parts[1] if len(parts) > 1 else ""
            # Regenerate SKU as BRAND-MODEL-COLOR-SIZE
            product = conn.execute(
                "SELECT color, size FROM products WHERE id = ?", (row[0],)
            ).fetchone()
            color = product[0] or ""
            size = product[1] or ""
            from utils.sku import generate_sku
            sku = generate_sku(brand, model, color, size)
            conn.execute(
                "UPDATE products SET brand = ?, model = ?, sku = ? WHERE id = ?",
                (brand, model, sku, row[0]),
            )
    conn.commit()


def _migrate_invoice_item_parsed_fields(conn: sqlite3.Connection) -> None:
    """Add parsed_brand, parsed_model, parsed_color, parsed_size columns if missing."""
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(invoice_items)").fetchall()
    }
    for col in ("parsed_brand", "parsed_model", "parsed_color", "parsed_size"):
        if col not in existing:
            conn.execute(f"ALTER TABLE invoice_items ADD COLUMN {col} TEXT")
    conn.commit()


def init_database(db_path: str) -> None:
    """Create all tables by executing schema.sql.

    Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS.
    Also runs lightweight migrations for schema additions.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(db_path)
    schema_sql = _SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    _migrate_invoice_fee_columns(conn)
    _migrate_brand_model(conn)
    _migrate_invoice_item_parsed_fields(conn)
    conn.close()
