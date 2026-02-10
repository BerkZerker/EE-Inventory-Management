"""API endpoints for the EE Inventory Management system."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

import database.models as models
from api.errors import error_response, handle_errors
from config import settings
from database.connection import get_db
from services.invoice_parser import (
    ParsedInvoiceItem,
    ParseError,
    allocate_costs,
    match_to_catalog,
    parse_invoice_with_retry,
)
from services.serial_generator import generate_serial_numbers, peek_next_serials

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# DB lifecycle
# ---------------------------------------------------------------------------


@api_bp.before_request
def _open_db() -> None:
    """Open a database connection and store it on flask.g."""
    g.db = get_db(settings.database_path)


@api_bp.teardown_request
def _close_db(exc: BaseException | None = None) -> None:
    """Close the per-request database connection."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ===========================================================================
# Invoice endpoints
# ===========================================================================


@api_bp.route("/invoices", methods=["GET"])
@handle_errors
def list_invoices() -> tuple:
    """List invoices with optional status filter."""
    status = request.args.get("status")
    invoices = models.list_invoices(g.db, status=status)
    return jsonify(invoices), 200


@api_bp.route("/invoices/upload", methods=["POST"])
@handle_errors
def upload_invoice() -> tuple:
    """Upload and parse an invoice PDF."""
    if "file" not in request.files:
        return error_response("No file provided", 400)

    file = request.files["file"]
    if not file.filename:
        return error_response("No file provided", 400)

    if not file.filename.lower().endswith(".pdf"):
        return error_response("Only PDF files are accepted", 400)

    # Save uploaded file
    upload_dir = settings.invoice_upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(file.filename)
    save_path = os.path.join(upload_dir, filename)
    file.save(save_path)

    # Parse the PDF
    try:
        parsed = parse_invoice_with_retry(save_path)
    except ParseError as exc:
        return error_response(str(exc), 422)

    # Create invoice record
    invoice = models.create_invoice(
        g.db,
        invoice_ref=parsed.invoice_number,
        supplier=parsed.supplier,
        invoice_date=parsed.invoice_date,
        total_amount=parsed.total,
        shipping_cost=parsed.shipping_cost,
        discount=parsed.discount,
        file_path=save_path,
        parsed_data=parsed.model_dump_json(),
    )

    # Match items to catalog and create invoice items
    catalog = models.list_products(g.db)
    item_dicts: list[dict[str, Any]] = []
    for item in parsed.items:
        product_id = match_to_catalog(item, catalog)
        item_dicts.append(
            {
                "description": item.model,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "total_cost": item.total_cost,
                "product_id": product_id,
            }
        )

    items = models.create_invoice_items_bulk(g.db, invoice["id"], item_dicts)
    invoice["items"] = items

    return jsonify(invoice), 201


@api_bp.route("/invoices/<int:invoice_id>", methods=["GET"])
@handle_errors
def get_invoice(invoice_id: int) -> tuple:
    """Get a single invoice with its items."""
    invoice = models.get_invoice_with_items(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)

    # If pending, include preview serials
    if invoice["status"] == "pending":
        total_quantity = sum(item["quantity"] for item in invoice["items"])
        if total_quantity > 0:
            invoice["preview_serials"] = peek_next_serials(total_quantity)

    return jsonify(invoice), 200


@api_bp.route("/invoices/<int:invoice_id>/items/<int:item_id>", methods=["PUT"])
@handle_errors
def edit_invoice_item(invoice_id: int, item_id: int) -> tuple:
    """Edit a line item on a pending invoice."""
    invoice = models.get_invoice(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)

    if invoice["status"] != "pending":
        return error_response("Can only edit items on pending invoices", 400)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # Build update fields from allowed keys
    update_fields: dict[str, Any] = {}
    for key in ("product_id", "description", "quantity", "unit_cost", "total_cost"):
        if key in data:
            update_fields[key] = data[key]

    if not update_fields:
        return error_response("No valid fields to update", 400)

    updated = models.update_invoice_item(g.db, item_id, **update_fields)
    if updated is None:
        return error_response("Invoice item not found", 404)

    return jsonify(updated), 200


@api_bp.route("/invoices/<int:invoice_id>/approve", methods=["POST"])
@handle_errors
def approve_invoice(invoice_id: int) -> tuple:
    """Approve an invoice: allocate costs, generate serials, create bikes."""
    invoice = models.get_invoice_with_items(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)

    if invoice["status"] != "pending":
        return error_response("Can only approve pending invoices", 400)

    items = invoice["items"]

    # Validate all items have product_id
    unmatched = [item for item in items if item["product_id"] is None]
    if unmatched:
        return error_response(
            "All items must have a product_id before approval",
            400,
            details=[item["id"] for item in unmatched],
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

    # Allocate costs (shipping + discount)
    per_unit_costs = allocate_costs(
        parsed_items, invoice["shipping_cost"], invoice["discount"]
    )

    # Update each item's allocated_cost
    for item, alloc_cost in zip(items, per_unit_costs):
        models.update_invoice_item(g.db, item["id"], allocated_cost=alloc_cost)

    # Calculate total bikes needed
    total_count = sum(item["quantity"] for item in items)

    # Generate serial numbers
    serials = generate_serial_numbers(total_count)

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
                }
            )
            serial_idx += 1

    bikes = models.create_bikes_bulk(g.db, bike_dicts)

    # Update invoice status
    models.update_invoice_status(g.db, invoice_id, "approved")

    # Return final state
    final_invoice = models.get_invoice_with_items(g.db, invoice_id)
    final_invoice["bikes"] = bikes

    return jsonify(final_invoice), 200


@api_bp.route("/invoices/<int:invoice_id>/reject", methods=["POST"])
@handle_errors
def reject_invoice(invoice_id: int) -> tuple:
    """Reject a pending invoice."""
    invoice = models.get_invoice(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)

    if invoice["status"] != "pending":
        return error_response("Can only reject pending invoices", 400)

    updated = models.update_invoice_status(g.db, invoice_id, "rejected")
    return jsonify(updated), 200


# ===========================================================================
# Product endpoints
# ===========================================================================


@api_bp.route("/products", methods=["GET"])
@handle_errors
def list_products() -> tuple:
    """List all products."""
    products = models.list_products(g.db)
    return jsonify(products), 200


@api_bp.route("/products", methods=["POST"])
@handle_errors
def create_product() -> tuple:
    """Create a new product."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # Validate required fields
    for field in ("sku", "model_name", "retail_price"):
        if field not in data:
            return error_response(f"Missing required field: {field}", 400)

    product = models.create_product(
        g.db,
        sku=data["sku"],
        model_name=data["model_name"],
        retail_price=data["retail_price"],
        color=data.get("color"),
        size=data.get("size"),
    )

    if product is None:
        return error_response("Duplicate SKU", 409)

    return jsonify(product), 201


@api_bp.route("/products/<int:product_id>", methods=["PUT"])
@handle_errors
def update_product(product_id: int) -> tuple:
    """Update an existing product."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    updated = models.update_product(g.db, product_id, **data)
    if updated is None:
        return error_response("Product not found", 404)

    return jsonify(updated), 200


@api_bp.route("/products/<int:product_id>", methods=["DELETE"])
@handle_errors
def delete_product(product_id: int) -> tuple:
    """Delete a product."""
    deleted = models.delete_product(g.db, product_id)
    if not deleted:
        return error_response("Product not found", 404)

    return jsonify({"message": "Product deleted"}), 200


# ===========================================================================
# Bike / report endpoints
# ===========================================================================


@api_bp.route("/bikes", methods=["GET"])
@handle_errors
def list_bikes() -> tuple:
    """List bikes with optional filters."""
    search = request.args.get("search")

    # Serial number search — return single bike in list or empty
    if search:
        bike = models.get_bike_by_serial(g.db, search)
        if bike:
            return jsonify([bike]), 200
        return jsonify([]), 200

    # Filtered list
    product_id = request.args.get("product_id", type=int)
    status = request.args.get("status")
    invoice_id = request.args.get("invoice_id", type=int)
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int)

    bikes = models.list_bikes(
        g.db,
        product_id=product_id,
        status=status,
        invoice_id=invoice_id,
        limit=limit,
        offset=offset,
    )
    return jsonify(bikes), 200


@api_bp.route("/inventory/summary", methods=["GET"])
@handle_errors
def inventory_summary() -> tuple:
    """Get inventory summary by product."""
    summary = models.get_inventory_summary(g.db)
    return jsonify(summary), 200


@api_bp.route("/reports/profit", methods=["GET"])
@handle_errors
def profit_report() -> tuple:
    """Get profit report for a date range."""
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        return error_response("Missing required query params: start, end", 400)

    summary = models.get_profit_summary(g.db, start, end)
    by_product = models.get_profit_report(g.db, start, end)

    return jsonify({"summary": summary, "by_product": by_product}), 200


# ===========================================================================
# Stub endpoints (not yet implemented)
# ===========================================================================


@api_bp.route("/labels/generate", methods=["POST"])
@handle_errors
def generate_labels() -> tuple:
    """Generate shipping labels (not yet implemented)."""
    data = request.get_json()
    if not data or "serials" not in data:
        return error_response("Request body must include 'serials' list", 400)

    if not isinstance(data["serials"], list):
        return error_response("'serials' must be a list", 400)

    return error_response("Label generation not yet available", 501)


@api_bp.route("/reconcile", methods=["POST"])
@handle_errors
def reconcile() -> tuple:
    """Reconciliation (not yet implemented)."""
    return error_response("Reconciliation not yet available", 501)
