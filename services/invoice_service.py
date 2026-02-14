"""Invoice approval service.

Consolidates the approve-invoice logic shared between the API route and the
CLI command into a single reusable function.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import database.models as models
from services.invoice_parser import ParsedInvoiceItem, allocate_costs
from services.serial_generator import generate_serial_numbers

logger = logging.getLogger(__name__)


def check_duplicate_invoice(
    conn: sqlite3.Connection,
    invoice_ref: str,
    overwrite: bool,
) -> dict[str, Any] | None:
    """Check whether *invoice_ref* already exists and decide how to proceed.

    Returns ``None`` when there is no conflict (or the pending duplicate was
    deleted because *overwrite* is ``True``).

    Otherwise returns a dict with keys ``error``, ``status_code``, and
    ``details`` suitable for constructing an error response.
    """
    existing_invoices = models.list_invoices(conn)
    for inv in existing_invoices:
        if inv["invoice_ref"] == invoice_ref:
            if inv["status"] == "pending" and not overwrite:
                return {
                    "error": f"Invoice {invoice_ref} already exists",
                    "status_code": 409,
                    "details": {"existing_id": inv["id"], "can_overwrite": True},
                }
            if inv["status"] == "pending" and overwrite:
                models.delete_invoice_by_ref(conn, invoice_ref)
                return None
            # Not pending — can't overwrite
            return {
                "error": f"Invoice {invoice_ref} already exists (status: {inv['status']})",
                "status_code": 409,
                "details": {"existing_id": inv["id"], "can_overwrite": False},
            }
    return None


def approve_invoice(
    conn: sqlite3.Connection,
    invoice_id: int,
    *,
    push_to_shopify: bool = True,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Approve an invoice: validate, allocate costs, generate serials, create bikes.

    Optionally pushes new bikes to Shopify as variants.

    Returns dict with keys: invoice, bikes, shopify_warnings (list).
    Raises ValueError for validation failures.
    """
    invoice = models.get_invoice_with_items(conn, invoice_id)
    if invoice is None:
        raise ValueError("Invoice not found")

    if invoice["status"] != "pending":
        raise ValueError("Can only approve pending invoices")

    items = invoice["items"]

    # Validate all items have product_id
    unmatched = [item for item in items if item["product_id"] is None]
    if unmatched:
        raise ValueError(
            "All items must have a product_id before approval",
        )

    # Build ParsedInvoiceItem list for allocate_costs
    parsed_items = [
        ParsedInvoiceItem(
            model=item["description"],
            quantity=item["quantity"],
            unit_cost=item["unit_cost"],
            total_cost=item["total_cost"],
        )
        for item in items
    ]

    # Allocate costs (shipping + fees - discount)
    per_unit_costs = allocate_costs(
        parsed_items,
        invoice["shipping_cost"],
        invoice["discount"],
        credit_card_fees=invoice.get("credit_card_fees", 0) or 0,
        tax=invoice.get("tax", 0) or 0,
        other_fees=invoice.get("other_fees", 0) or 0,
    )

    # Update each item's allocated_cost
    for item, alloc_cost in zip(items, per_unit_costs):
        models.update_invoice_item(conn, item["id"], allocated_cost=alloc_cost)

    # Calculate total bikes needed
    total_count = sum(item["quantity"] for item in items)

    # Generate serial numbers
    serials = generate_serial_numbers(total_count, conn=conn)

    # Build bike records
    bike_dicts: list[dict[str, Any]] = []
    serial_idx = 0
    for item, alloc_cost in zip(items, per_unit_costs):
        for _ in range(item["quantity"]):
            bike_dicts.append(
                {
                    "serial_number": serials[serial_idx],
                    "product_id": item["product_id"],
                    "actual_cost": alloc_cost,
                    "invoice_id": invoice_id,
                    "status": "in_transit",
                    "date_received": None,
                }
            )
            serial_idx += 1

    bikes = models.create_bikes_bulk(conn, bike_dicts)

    # Update invoice status
    models.update_invoice_status(conn, invoice_id, "approved", approved_by=approved_by)

    # Shopify push is deferred until bikes are received (marked available)
    shopify_warnings: list[str] = []

    # Return final state
    final_invoice = models.get_invoice_with_items(conn, invoice_id)
    return {
        "invoice": final_invoice,
        "bikes": bikes,
        "shopify_warnings": shopify_warnings,
    }


def receive_bikes(
    conn: sqlite3.Connection,
    bike_ids: list[int],
) -> dict[str, Any]:
    """Mark in-transit bikes as received and push them to Shopify.

    Returns dict with keys: bikes, shopify_warnings.
    """
    bikes = models.receive_bikes(conn, bike_ids)
    shopify_warnings = _push_bikes_to_shopify(conn, bikes) if bikes else []
    return {"bikes": bikes, "shopify_warnings": shopify_warnings}


def _push_bikes_to_shopify(
    conn: sqlite3.Connection,
    bikes: list[dict[str, Any]],
) -> list[str]:
    """Push bikes to Shopify as variants, returning any warning messages."""
    errors: list[str] = []
    try:
        from services.shopify_sync import create_variants_for_bikes, ensure_shopify_product

        # Group bikes by product_id
        bikes_by_product: dict[int, list[dict]] = {}
        for bike in bikes:
            bikes_by_product.setdefault(bike["product_id"], []).append(bike)

        for pid, product_bikes in bikes_by_product.items():
            product = models.get_product(conn, pid)
            if not product:
                errors.append(f"Product {pid} not found — skipped Shopify sync")
                continue
            # Ensure Shopify product exists (push-based)
            if not product.get("shopify_product_id"):
                ensure_shopify_product(conn, product)
                product = models.get_product(conn, pid)
            if not product or not product.get("shopify_product_id"):
                errors.append(
                    f"Product {pid} has no shopify_product_id — skipped Shopify sync"
                )
                continue
            try:
                create_variants_for_bikes(product_bikes, product, conn=conn)
            except Exception as exc:
                errors.append(f"Product {pid}: {exc}")
    except Exception as exc:
        errors.append(f"Shopify sync failed: {exc}")

    if errors:
        logger.warning("Shopify sync issues: %s", errors)

    return errors
