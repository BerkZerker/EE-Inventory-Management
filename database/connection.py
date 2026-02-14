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


def _migrate_bike_in_transit_status(conn: sqlite3.Connection) -> None:
    """Rebuild bikes table to add 'in_transit' status and make date_received nullable."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bikes'"
    ).fetchone()
    if row is None or "in_transit" in row[0]:
        return  # Table missing or already migrated

    conn.executescript("""
        CREATE TABLE bikes_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_number   TEXT NOT NULL UNIQUE,
            product_id      INTEGER NOT NULL REFERENCES products(id),
            invoice_id      INTEGER REFERENCES invoices(id),
            shopify_variant_id TEXT,
            actual_cost     REAL NOT NULL DEFAULT 0,
            date_received   TEXT,
            status          TEXT NOT NULL DEFAULT 'available'
                            CHECK (status IN ('available', 'in_transit', 'sold', 'returned', 'damaged')),
            date_sold       TEXT,
            sale_price      REAL,
            shopify_order_id TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        INSERT INTO bikes_new
            (id, serial_number, product_id, invoice_id, shopify_variant_id,
             actual_cost, date_received, status, date_sold, sale_price,
             shopify_order_id, notes, created_at)
        SELECT
            id, serial_number, product_id, invoice_id, shopify_variant_id,
            actual_cost, date_received, status, date_sold, sale_price,
            shopify_order_id, notes, created_at
        FROM bikes;

        DROP TABLE bikes;
        ALTER TABLE bikes_new RENAME TO bikes;

        CREATE INDEX IF NOT EXISTS idx_bikes_product ON bikes(product_id);
        CREATE INDEX IF NOT EXISTS idx_bikes_status ON bikes(status);
        CREATE INDEX IF NOT EXISTS idx_bikes_invoice ON bikes(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_bikes_serial ON bikes(serial_number);
        CREATE INDEX IF NOT EXISTS idx_bikes_shopify_variant ON bikes(shopify_variant_id);
    """)


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
    _migrate_bike_in_transit_status(conn)
    conn.close()
