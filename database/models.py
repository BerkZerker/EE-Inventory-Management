"""Database CRUD operations.

Implements all data-access functions for products, invoices, invoice items,
bikes, serial counter, and webhook log.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Convert a sqlite3.Row to a plain dict, or return None."""
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert a list of sqlite3.Row to a list of dicts."""
    return [dict(r) for r in rows]


def _now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _build_update(
    table: str,
    row_id: int,
    fields: dict[str, Any],
    allowed: set[str],
) -> tuple[str, list[Any]]:
    """Build a dynamic UPDATE statement from validated field names.

    Only columns in *allowed* are accepted — this whitelist check prevents
    SQL injection even though column names are interpolated into the query.

    Returns (sql, params) ready for ``conn.execute()``.
    """
    to_set: dict[str, Any] = {}
    for key, value in fields.items():
        if key in allowed:
            to_set[key] = value
    if not to_set:
        msg = "No valid fields to update"
        raise ValueError(msg)

    clauses = [f"{col} = ?" for col in to_set]
    params = list(to_set.values())
    params.append(row_id)
    sql = f"UPDATE {table} SET {', '.join(clauses)} WHERE id = ?"  # noqa: S608
    return sql, params


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

_PRODUCT_UPDATE_ALLOWED = {
    "sku",
    "brand",
    "model",
    "color",
    "size",
    "retail_price",
    "shopify_product_id",
}


def create_product(
    conn: sqlite3.Connection,
    sku: str,
    brand: str,
    model: str,
    retail_price: float,
    color: str | None = None,
    size: str | None = None,
    shopify_product_id: str | None = None,
) -> dict[str, Any] | None:
    """Insert a new product and return it, or None on duplicate SKU."""
    try:
        cur = conn.execute(
            """
            INSERT INTO products
                (sku, brand, model, retail_price, color, size,
                 shopify_product_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sku, brand, model, retail_price, color, size, shopify_product_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return None
    return _row_to_dict(
        conn.execute("SELECT * FROM products WHERE id = ?", (cur.lastrowid,)).fetchone()
    )


def get_product(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    """Return a single product by ID."""
    return _row_to_dict(
        conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    )


def get_product_by_sku(conn: sqlite3.Connection, sku: str) -> dict[str, Any] | None:
    """Return a single product by SKU."""
    return _row_to_dict(conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone())


def list_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all products ordered by brand, model."""
    return _rows_to_list(conn.execute("SELECT * FROM products ORDER BY brand, model").fetchall())


def get_products_by_brand_model(
    conn: sqlite3.Connection,
    brand: str,
    model: str,
) -> list[dict[str, Any]]:
    """Return all products sharing the same brand+model (sibling variants)."""
    return _rows_to_list(
        conn.execute(
            "SELECT * FROM products WHERE brand = ? AND model = ?",
            (brand, model),
        ).fetchall()
    )


def update_product(
    conn: sqlite3.Connection,
    product_id: int,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update a product's fields and return the updated row."""
    fields["updated_at"] = _now()
    allowed = _PRODUCT_UPDATE_ALLOWED | {"updated_at"}
    sql, params = _build_update("products", product_id, fields, allowed)
    conn.execute(sql, params)
    conn.commit()
    return get_product(conn, product_id)


def delete_product(conn: sqlite3.Connection, product_id: int) -> bool:
    """Delete a product by ID. Returns True if a row was deleted."""
    cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

_VALID_INVOICE_STATUSES = {"pending", "approved", "rejected"}


_INVOICE_UPDATE_ALLOWED = {
    "shipping_cost",
    "discount",
    "credit_card_fees",
    "tax",
    "other_fees",
}


def create_invoice(
    conn: sqlite3.Connection,
    invoice_ref: str,
    supplier: str,
    invoice_date: str,
    total_amount: float | None = None,
    shipping_cost: float = 0,
    discount: float = 0,
    credit_card_fees: float = 0,
    tax: float = 0,
    other_fees: float = 0,
    file_path: str | None = None,
    parsed_data: str | None = None,
) -> dict[str, Any]:
    """Insert a new invoice and return it."""
    cur = conn.execute(
        """
        INSERT INTO invoices
            (invoice_ref, supplier, invoice_date, total_amount,
             shipping_cost, discount, credit_card_fees, tax, other_fees,
             file_path, parsed_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_ref,
            supplier,
            invoice_date,
            total_amount,
            shipping_cost,
            discount,
            credit_card_fees,
            tax,
            other_fees,
            file_path,
            parsed_data,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_invoice(
    conn: sqlite3.Connection,
    invoice_id: int,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update an invoice's editable cost fields and return the updated row."""
    sql, params = _build_update("invoices", invoice_id, fields, _INVOICE_UPDATE_ALLOWED)
    conn.execute(sql, params)
    conn.commit()
    return get_invoice(conn, invoice_id)


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> dict[str, Any] | None:
    """Return a single invoice by ID."""
    return _row_to_dict(
        conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    )


def get_invoice_with_items(
    conn: sqlite3.Connection,
    invoice_id: int,
) -> dict[str, Any] | None:
    """Return an invoice with its line items nested under an 'items' key."""
    invoice = get_invoice(conn, invoice_id)
    if invoice is None:
        return None
    items = _rows_to_list(
        conn.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id",
            (invoice_id,),
        ).fetchall()
    )
    invoice["items"] = items
    return invoice


def list_invoices(
    conn: sqlite3.Connection,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return invoices ordered by created_at DESC, optionally filtered by status."""
    if status is not None:
        return _rows_to_list(
            conn.execute(
                "SELECT * FROM invoices WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        )
    return _rows_to_list(
        conn.execute("SELECT * FROM invoices ORDER BY created_at DESC").fetchall()
    )


def update_invoice_status(
    conn: sqlite3.Connection,
    invoice_id: int,
    status: str,
    approved_by: str | None = None,
) -> dict[str, Any] | None:
    """Update an invoice's status. Sets approved_at on approval."""
    if status not in _VALID_INVOICE_STATUSES:
        msg = f"Invalid invoice status: {status!r}"
        raise ValueError(msg)

    if status == "approved":
        conn.execute(
            """
            UPDATE invoices
            SET status = ?, approved_by = ?, approved_at = datetime('now')
            WHERE id = ?
            """,
            (status, approved_by, invoice_id),
        )
    else:
        conn.execute(
            "UPDATE invoices SET status = ? WHERE id = ?",
            (status, invoice_id),
        )
    conn.commit()
    return get_invoice(conn, invoice_id)


def delete_invoice_by_ref(conn: sqlite3.Connection, ref: str) -> bool:
    """Delete a pending invoice by its invoice_ref. Returns True if deleted."""
    row = conn.execute(
        "SELECT id, status FROM invoices WHERE invoice_ref = ?", (ref,)
    ).fetchone()
    if row is None:
        return False
    if row["status"] != "pending":
        return False
    conn.execute("DELETE FROM invoices WHERE id = ?", (row["id"],))
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Invoice Items
# ---------------------------------------------------------------------------

_INVOICE_ITEM_UPDATE_ALLOWED = {
    "product_id",
    "description",
    "quantity",
    "unit_cost",
    "total_cost",
    "allocated_cost",
    "parsed_brand",
    "parsed_model",
    "parsed_color",
    "parsed_size",
}


def create_invoice_item(
    conn: sqlite3.Connection,
    invoice_id: int,
    description: str,
    quantity: int,
    unit_cost: float,
    total_cost: float,
    product_id: int | None = None,
    allocated_cost: float | None = None,
    parsed_brand: str | None = None,
    parsed_model: str | None = None,
    parsed_color: str | None = None,
    parsed_size: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Insert a single invoice line item and return it."""
    cur = conn.execute(
        """
        INSERT INTO invoice_items
            (invoice_id, product_id, description, quantity, unit_cost,
             total_cost, allocated_cost, parsed_brand, parsed_model,
             parsed_color, parsed_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_id, product_id, description, quantity, unit_cost,
            total_cost, allocated_cost, parsed_brand, parsed_model,
            parsed_color, parsed_size,
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute("SELECT * FROM invoice_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def create_invoice_items_bulk(
    conn: sqlite3.Connection,
    invoice_id: int,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Insert multiple invoice line items in one batch and return them."""
    rows_data = [
        (
            invoice_id,
            item.get("product_id"),
            item["description"],
            item["quantity"],
            item["unit_cost"],
            item["total_cost"],
            item.get("allocated_cost"),
            item.get("parsed_brand"),
            item.get("parsed_model"),
            item.get("parsed_color"),
            item.get("parsed_size"),
        )
        for item in items
    ]
    conn.executemany(
        """
        INSERT INTO invoice_items
            (invoice_id, product_id, description, quantity, unit_cost,
             total_cost, allocated_cost, parsed_brand, parsed_model,
             parsed_color, parsed_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows_data,
    )
    conn.commit()
    return _rows_to_list(
        conn.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id",
            (invoice_id,),
        ).fetchall()
    )


def update_invoice_item(
    conn: sqlite3.Connection,
    item_id: int,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update an invoice item's fields and return the updated row."""
    sql, params = _build_update("invoice_items", item_id, fields, _INVOICE_ITEM_UPDATE_ALLOWED)
    conn.execute(sql, params)
    conn.commit()
    return _row_to_dict(
        conn.execute("SELECT * FROM invoice_items WHERE id = ?", (item_id,)).fetchone()
    )


def delete_invoice_item(conn: sqlite3.Connection, item_id: int) -> bool:
    """Delete an invoice item by ID. Returns True if a row was deleted."""
    cur = conn.execute("DELETE FROM invoice_items WHERE id = ?", (item_id,))
    conn.commit()
    return cur.rowcount > 0


def get_invoice_items(
    conn: sqlite3.Connection,
    invoice_id: int,
) -> list[dict[str, Any]]:
    """Return all line items for an invoice, ordered by id."""
    return _rows_to_list(
        conn.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id",
            (invoice_id,),
        ).fetchall()
    )


# ---------------------------------------------------------------------------
# Bikes
# ---------------------------------------------------------------------------

_VALID_BIKE_STATUSES = {"available", "sold", "returned", "damaged"}

_BIKE_UPDATE_ALLOWED = {
    "serial_number",
    "product_id",
    "invoice_id",
    "shopify_variant_id",
    "actual_cost",
    "date_received",
    "status",
    "date_sold",
    "sale_price",
    "shopify_order_id",
    "notes",
}


def create_bike(
    conn: sqlite3.Connection,
    serial_number: str,
    product_id: int,
    actual_cost: float,
    invoice_id: int | None = None,
    shopify_variant_id: str | None = None,
    date_received: str | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Insert a new bike record and return it."""
    cur = conn.execute(
        """
        INSERT INTO bikes
            (serial_number, product_id, actual_cost, invoice_id,
             shopify_variant_id, date_received, notes)
        VALUES (?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)
        """,
        (
            serial_number,
            product_id,
            actual_cost,
            invoice_id,
            shopify_variant_id,
            date_received,
            notes,
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute("SELECT * FROM bikes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def create_bikes_bulk(
    conn: sqlite3.Connection,
    bikes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Insert multiple bikes in one batch and return them."""
    if not bikes:
        return []
    max_id_before = conn.execute("SELECT COALESCE(MAX(id), 0) FROM bikes").fetchone()[0]
    rows_data = [
        (
            b["serial_number"],
            b["product_id"],
            b["actual_cost"],
            b.get("invoice_id"),
            b.get("shopify_variant_id"),
            b.get("date_received"),
            b.get("notes"),
        )
        for b in bikes
    ]
    conn.executemany(
        """
        INSERT INTO bikes
            (serial_number, product_id, actual_cost, invoice_id,
             shopify_variant_id, date_received, notes)
        VALUES (?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)
        """,
        rows_data,
    )
    conn.commit()
    return _rows_to_list(
        conn.execute(
            "SELECT * FROM bikes WHERE id > ? ORDER BY id",
            (max_id_before,),
        ).fetchall()
    )


def get_bike(conn: sqlite3.Connection, bike_id: int) -> dict[str, Any] | None:
    """Return a single bike by ID."""
    return _row_to_dict(conn.execute("SELECT * FROM bikes WHERE id = ?", (bike_id,)).fetchone())


def get_bike_by_serial(
    conn: sqlite3.Connection,
    serial_number: str,
) -> dict[str, Any] | None:
    """Return a single bike by serial number."""
    return _row_to_dict(
        conn.execute("SELECT * FROM bikes WHERE serial_number = ?", (serial_number,)).fetchone()
    )


def list_bikes(
    conn: sqlite3.Connection,
    product_id: int | None = None,
    status: str | None = None,
    invoice_id: int | None = None,
    limit: int | None = 500,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Return bikes with product info, optionally filtered and paginated."""
    sql = """
        SELECT b.*, p.sku, p.brand, p.model, p.color, p.size, p.retail_price
        FROM bikes b
        JOIN products p ON b.product_id = p.id
    """
    conditions: list[str] = []
    params: list[Any] = []

    if product_id is not None:
        conditions.append("b.product_id = ?")
        params.append(product_id)
    if status is not None:
        conditions.append("b.status = ?")
        params.append(status)
    if invoice_id is not None:
        conditions.append("b.invoice_id = ?")
        params.append(invoice_id)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY b.id"

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    if offset is not None:
        sql += " OFFSET ?"
        params.append(offset)

    return _rows_to_list(conn.execute(sql, params).fetchall())


def update_bike_status(
    conn: sqlite3.Connection,
    bike_id: int,
    status: str,
    sale_price: float | None = None,
    shopify_order_id: str | None = None,
    date_sold: str | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    """Update a bike's status with optional sale info."""
    if status not in _VALID_BIKE_STATUSES:
        msg = f"Invalid bike status: {status!r}"
        raise ValueError(msg)

    if status == "sold":
        sold_date = date_sold or _now()
        conn.execute(
            """
            UPDATE bikes
            SET status = ?, sale_price = ?, shopify_order_id = ?, date_sold = ?
            WHERE id = ?
            """,
            (status, sale_price, shopify_order_id, sold_date, bike_id),
        )
    else:
        conn.execute(
            "UPDATE bikes SET status = ? WHERE id = ?",
            (status, bike_id),
        )
    if commit:
        conn.commit()
    return get_bike(conn, bike_id)


def mark_bike_sold(
    conn: sqlite3.Connection,
    serial_number: str,
    sale_price: float | None = None,
    shopify_order_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any] | None:
    """Find a bike by serial number and mark it as sold."""
    bike = get_bike_by_serial(conn, serial_number)
    if bike is None:
        return None
    return update_bike_status(
        conn,
        bike["id"],
        "sold",
        sale_price=sale_price,
        shopify_order_id=shopify_order_id,
        commit=commit,
    )


def update_bike(
    conn: sqlite3.Connection,
    bike_id: int,
    **fields: Any,
) -> dict[str, Any] | None:
    """Generic update for bike corrections/reconciliation."""
    sql, params = _build_update("bikes", bike_id, fields, _BIKE_UPDATE_ALLOWED)
    conn.execute(sql, params)
    conn.commit()
    return get_bike(conn, bike_id)


def delete_bike(conn: sqlite3.Connection, bike_id: int) -> bool:
    """Delete a bike by ID. Returns True if a row was deleted."""
    cur = conn.execute("DELETE FROM bikes WHERE id = ?", (bike_id,))
    conn.commit()
    return cur.rowcount > 0


def delete_bikes_by_product(conn: sqlite3.Connection, product_id: int) -> list[dict[str, Any]]:
    """Delete all bikes for a product. Returns the deleted bikes (for Shopify cleanup)."""
    bikes = _rows_to_list(
        conn.execute("SELECT * FROM bikes WHERE product_id = ?", (product_id,)).fetchall()
    )
    if bikes:
        conn.execute("DELETE FROM bikes WHERE product_id = ?", (product_id,))
        conn.commit()
    return bikes


# ---------------------------------------------------------------------------
# Serial Counter
# ---------------------------------------------------------------------------


def get_next_serial(conn: sqlite3.Connection) -> int:
    """Peek at the next serial number without incrementing."""
    row = conn.execute("SELECT next_serial FROM serial_counter WHERE id = 1").fetchone()
    if row is None:
        msg = "serial_counter table is not initialised"
        raise RuntimeError(msg)
    return int(row["next_serial"])


def increment_serial_counter(conn: sqlite3.Connection, count: int = 1) -> int:
    """Atomically reserve *count* serial numbers and return the starting value.

    Uses BEGIN IMMEDIATE for a write-lock. Temporarily switches to autocommit
    (isolation_level = None) to avoid conflict with Python's implicit
    transaction management, then restores the original isolation_level.
    """
    original_isolation = conn.isolation_level
    try:
        conn.isolation_level = None  # autocommit mode
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT next_serial FROM serial_counter WHERE id = 1").fetchone()
        if row is None:
            msg = "serial_counter table is not initialised"
            raise RuntimeError(msg)
        start = int(row["next_serial"])
        conn.execute(
            "UPDATE serial_counter SET next_serial = ? WHERE id = 1",
            (start + count,),
        )
        conn.execute("COMMIT")
    finally:
        conn.isolation_level = original_isolation
    return start


def set_serial_counter(conn: sqlite3.Connection, value: int) -> int:
    """Set the serial counter to a specific value. Returns the new value."""
    conn.execute(
        "UPDATE serial_counter SET next_serial = ? WHERE id = 1",
        (value,),
    )
    conn.commit()
    return value


# ---------------------------------------------------------------------------
# Webhook Log
# ---------------------------------------------------------------------------


def create_webhook_log(
    conn: sqlite3.Connection,
    webhook_id: str,
    topic: str,
    payload: str | None = None,
) -> dict[str, Any]:
    """Insert a webhook log entry. Raises IntegrityError on duplicate webhook_id."""
    cur = conn.execute(
        """
        INSERT INTO webhook_log (webhook_id, topic, payload)
        VALUES (?, ?, ?)
        """,
        (webhook_id, topic, payload),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM webhook_log WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def is_duplicate_webhook(conn: sqlite3.Connection, webhook_id: str) -> bool:
    """Check if a webhook_id already exists."""
    row = conn.execute("SELECT 1 FROM webhook_log WHERE webhook_id = ?", (webhook_id,)).fetchone()
    return row is not None


def update_webhook_status(
    conn: sqlite3.Connection,
    webhook_id: str,
    status: str,
    error: str | None = None,
) -> bool:
    """Update a webhook log entry's status. Returns True if found."""
    cur = conn.execute(
        "UPDATE webhook_log SET status = ?, error = ? WHERE webhook_id = ?",
        (status, error, webhook_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Reporting Queries
# ---------------------------------------------------------------------------


def get_inventory_summary(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Product-level inventory summary with counts per status and avg cost."""
    return _rows_to_list(
        conn.execute(
            """
            SELECT
                p.id            AS product_id,
                p.sku,
                p.brand,
                p.model,
                p.color,
                p.size,
                p.retail_price,
                COUNT(b.id)                                     AS total_bikes,
                SUM(CASE WHEN b.status = 'available' THEN 1 ELSE 0 END)
                                                                AS available,
                SUM(CASE WHEN b.status = 'sold' THEN 1 ELSE 0 END)
                                                                AS sold,
                SUM(CASE WHEN b.status = 'returned' THEN 1 ELSE 0 END)
                                                                AS returned,
                SUM(CASE WHEN b.status = 'damaged' THEN 1 ELSE 0 END)
                                                                AS damaged,
                ROUND(AVG(b.actual_cost), 2)                    AS avg_cost
            FROM products p
            LEFT JOIN bikes b ON b.product_id = p.id
            GROUP BY p.id
            ORDER BY p.brand, p.model
            """
        ).fetchall()
    )


def get_profit_report(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Per-product profit report for sold bikes in a date range."""
    return _rows_to_list(
        conn.execute(
            """
            SELECT
                p.id            AS product_id,
                p.sku,
                p.brand,
                p.model,
                COUNT(b.id)                             AS units_sold,
                ROUND(SUM(b.sale_price), 2)             AS total_revenue,
                ROUND(SUM(b.actual_cost), 2)            AS total_cost,
                ROUND(SUM(b.sale_price - b.actual_cost), 2)
                                                        AS total_profit,
                ROUND(
                    CASE
                        WHEN SUM(b.sale_price) > 0
                        THEN SUM(b.sale_price - b.actual_cost) * 100.0
                             / SUM(b.sale_price)
                        ELSE 0
                    END,
                2)                                      AS margin_pct
            FROM bikes b
            JOIN products p ON b.product_id = p.id
            WHERE b.status = 'sold'
              AND b.date_sold >= ?
              AND b.date_sold < date(?, '+1 day')
            GROUP BY p.id
            ORDER BY total_profit DESC
            """,
            (start_date, end_date),
        ).fetchall()
    )


def get_profit_summary(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Aggregate profit totals across all products for a date range."""
    row = conn.execute(
        """
        SELECT
            COUNT(b.id)                                 AS units_sold,
            COALESCE(ROUND(SUM(b.sale_price), 2), 0)   AS total_revenue,
            COALESCE(ROUND(SUM(b.actual_cost), 2), 0)  AS total_cost,
            COALESCE(ROUND(SUM(b.sale_price - b.actual_cost), 2), 0)
                                                        AS total_profit,
            ROUND(
                CASE
                    WHEN SUM(b.sale_price) > 0
                    THEN SUM(b.sale_price - b.actual_cost) * 100.0
                         / SUM(b.sale_price)
                    ELSE 0
                END,
            2)                                          AS margin_pct
        FROM bikes b
        WHERE b.status = 'sold'
          AND b.date_sold >= ?
          AND b.date_sold < date(?, '+1 day')
        """,
        (start_date, end_date),
    ).fetchone()
    if row is None:
        return {
            "units_sold": 0,
            "total_revenue": 0,
            "total_cost": 0,
            "total_profit": 0,
            "margin_pct": 0,
        }
    return dict(row)
