"""API endpoints for the EE Inventory Management system."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, g, jsonify, request, send_file
from werkzeug.utils import secure_filename

import database.models as models
from api.errors import error_response, handle_errors
from config import settings
from database.connection import get_db
from services.invoice_parser import (
    ParseError,
    match_to_catalog,
    parse_invoice_with_retry,
)
from services.invoice_service import approve_invoice as _approve_invoice
from services.invoice_service import check_duplicate_invoice
from services.serial_generator import peek_next_serials
from utils.sku import generate_sku

logger = logging.getLogger(__name__)

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
# Shopify sync
# ===========================================================================


@api_bp.route("/sync/products", methods=["POST"])
@handle_errors
def sync_products() -> tuple:
    """No-op — product sync is now push-based."""
    return jsonify({"synced": 0, "message": "Sync is now push-based. Products are pushed to Shopify on creation."}), 200


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

    # Check for duplicate invoice_ref and handle overwrite
    overwrite = request.form.get("overwrite", "").lower() == "true"
    conflict = check_duplicate_invoice(g.db, parsed.invoice_number, overwrite)
    if conflict is not None:
        return error_response(
            conflict["error"],
            conflict["status_code"],
            details=conflict["details"],
        )

    # Create invoice record
    invoice = models.create_invoice(
        g.db,
        invoice_ref=parsed.invoice_number,
        supplier=parsed.supplier,
        invoice_date=parsed.invoice_date,
        total_amount=parsed.total,
        shipping_cost=parsed.shipping_cost,
        discount=parsed.discount,
        credit_card_fees=parsed.credit_card_fees,
        tax=parsed.tax,
        other_fees=parsed.other_fees,
        file_path=save_path,
        parsed_data=parsed.model_dump_json(),
    )

    # Match items to catalog and create invoice items
    catalog = models.list_products(g.db)
    item_dicts: list[dict[str, Any]] = []
    for item in parsed.items:
        product_id = match_to_catalog(item, catalog)
        desc = f"{item.brand} {item.model}".strip() if item.brand else item.model
        item_dicts.append(
            {
                "description": desc,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "total_cost": item.total_cost,
                "product_id": product_id,
                "parsed_brand": item.brand,
                "parsed_model": item.model,
                "parsed_color": item.color,
                "parsed_size": item.size,
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
            invoice["preview_serials"] = peek_next_serials(total_quantity, conn=g.db)

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

    # Validate numeric constraints
    if "quantity" in data:
        try:
            if int(data["quantity"]) < 1:
                return error_response("quantity must be at least 1", 400)
        except (TypeError, ValueError):
            return error_response("quantity must be an integer", 400)

    if "unit_cost" in data:
        try:
            if float(data["unit_cost"]) < 0:
                return error_response("unit_cost must not be negative", 400)
        except (TypeError, ValueError):
            return error_response("unit_cost must be a number", 400)

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
    # Pre-check for detailed error responses the API needs
    invoice = models.get_invoice_with_items(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)
    if invoice["status"] != "pending":
        return error_response("Can only approve pending invoices", 400)
    unmatched = [item for item in invoice["items"] if item["product_id"] is None]
    if unmatched:
        return error_response(
            "All items must have a product_id before approval",
            400,
            details=[item["id"] for item in unmatched],
        )

    result = _approve_invoice(g.db, invoice_id, push_to_shopify=True)

    final_invoice = result["invoice"]
    final_invoice["bikes"] = result["bikes"]
    if result["shopify_warnings"]:
        final_invoice["shopify_warnings"] = result["shopify_warnings"]

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


@api_bp.route("/invoices/<int:invoice_id>/pdf", methods=["GET"])
@handle_errors
def get_invoice_pdf(invoice_id: int) -> tuple:
    """Serve the original invoice PDF file."""
    invoice = models.get_invoice(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)

    file_path = invoice.get("file_path")
    if not file_path:
        return error_response("PDF file not found", 404)

    # Resolve relative paths against the project root
    resolved = Path(file_path)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parent.parent / resolved

    # Path traversal guard
    allowed = Path(settings.invoice_upload_dir).resolve()
    if not str(resolved.resolve()).startswith(str(allowed)):
        return error_response("Access denied", 403)

    if not resolved.is_file():
        return error_response("PDF file not found", 404)

    return send_file(str(resolved), mimetype="application/pdf")


@api_bp.route("/invoices/<int:invoice_id>", methods=["PUT"])
@handle_errors
def update_invoice(invoice_id: int) -> tuple:
    """Update invoice-level cost fields on a pending invoice."""
    invoice = models.get_invoice(g.db, invoice_id)
    if invoice is None:
        return error_response("Invoice not found", 404)

    if invoice["status"] != "pending":
        return error_response("Can only edit pending invoices", 400)

    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    update_fields: dict[str, Any] = {}
    for key in ("shipping_cost", "discount", "credit_card_fees", "tax", "other_fees"):
        if key in data:
            update_fields[key] = data[key]

    if not update_fields:
        return error_response("No valid fields to update", 400)

    updated = models.update_invoice(g.db, invoice_id, **update_fields)
    if updated is None:
        return error_response("Invoice not found", 404)

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
    """Create a new product. SKU is auto-generated from brand/model/color/size."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # Validate required fields
    for field in ("brand", "model", "retail_price"):
        if field not in data:
            return error_response(f"Missing required field: {field}", 400)

    try:
        if float(data["retail_price"]) < 0:
            return error_response("retail_price must not be negative", 400)
    except (TypeError, ValueError):
        return error_response("retail_price must be a number", 400)

    # Auto-generate SKU as BRAND-MODEL-COLOR-SIZE
    sku = generate_sku(data["brand"], data["model"], data.get("color", ""), data.get("size", ""))

    product = models.create_product(
        g.db,
        sku=sku,
        brand=data["brand"],
        model=data["model"],
        retail_price=data["retail_price"],
        color=data.get("color"),
        size=data.get("size"),
    )

    if product is None:
        return error_response("Duplicate SKU", 409)

    # Push to Shopify
    shopify_warning = None
    try:
        from services.shopify_sync import ensure_shopify_product

        ensure_shopify_product(g.db, product)
    except Exception:
        logger.warning("Shopify push failed for product %s", sku, exc_info=True)
        shopify_warning = f"Product created locally but Shopify sync failed for {sku}"

    resp: dict[str, Any] = dict(product)
    if shopify_warning:
        resp["shopify_warning"] = shopify_warning
    return jsonify(resp), 201


@api_bp.route("/products/<int:product_id>", methods=["PUT"])
@handle_errors
def update_product(product_id: int) -> tuple:
    """Update an existing product. Regenerates SKU if brand/model/color/size change."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    # If any SKU component changed, regenerate SKU
    if any(k in data for k in ("brand", "model", "color", "size")):
        existing = models.get_product(g.db, product_id)
        if existing is None:
            return error_response("Product not found", 404)
        brand = data.get("brand", existing["brand"])
        model = data.get("model", existing["model"])
        color = data.get("color", existing.get("color", ""))
        size = data.get("size", existing.get("size", ""))
        data["sku"] = generate_sku(brand, model, color or "", size or "")

    updated = models.update_product(g.db, product_id, **data)
    if updated is None:
        return error_response("Product not found", 404)

    return jsonify(updated), 200


@api_bp.route("/products/<int:product_id>", methods=["DELETE"])
@handle_errors
def delete_product(product_id: int) -> tuple:
    """Delete a product and cascade-delete its bikes + Shopify variants."""
    product = models.get_product(g.db, product_id)
    if product is None:
        return error_response("Product not found", 404)

    bikes = models.delete_bikes_by_product(g.db, product_id)

    shopify_warning = None
    variant_ids = [b["shopify_variant_id"] for b in bikes if b.get("shopify_variant_id")]
    if variant_ids and product.get("shopify_product_id"):
        try:
            from services.shopify_sync import delete_variants
            delete_variants(product, variant_ids)
        except Exception:
            logger.warning("Shopify variant cleanup failed for product %s", product_id, exc_info=True)
            shopify_warning = "Product deleted locally but some Shopify variants may remain"

    models.delete_product(g.db, product_id)

    result: dict[str, Any] = {"message": "Product deleted", "bikes_deleted": len(bikes)}
    if shopify_warning:
        result["shopify_warning"] = shopify_warning
    return jsonify(result), 200


@api_bp.route("/products/bulk", methods=["DELETE"])
@handle_errors
def bulk_delete_products() -> tuple:
    """Delete multiple products and their bikes + Shopify variants."""
    data = request.get_json()
    if not data or "product_ids" not in data:
        return error_response("Request body must include 'product_ids' list", 400)

    product_ids = data["product_ids"]
    if not isinstance(product_ids, list) or not product_ids:
        return error_response("'product_ids' must be a non-empty list", 400)

    deleted_count = 0
    total_bikes_deleted = 0
    shopify_warnings: list[str] = []

    for pid in product_ids:
        product = models.get_product(g.db, pid)
        if product is None:
            continue

        bikes = models.delete_bikes_by_product(g.db, pid)
        total_bikes_deleted += len(bikes)

        variant_ids = [b["shopify_variant_id"] for b in bikes if b.get("shopify_variant_id")]
        if variant_ids and product.get("shopify_product_id"):
            try:
                from services.shopify_sync import delete_variants
                delete_variants(product, variant_ids)
            except Exception:
                logger.warning("Shopify variant cleanup failed for product %s", pid, exc_info=True)
                shopify_warnings.append(f"Shopify cleanup failed for {product['brand']} {product['model']}")

        models.delete_product(g.db, pid)
        deleted_count += 1

    result: dict[str, Any] = {
        "message": f"Deleted {deleted_count} product(s)",
        "deleted_count": deleted_count,
        "bikes_deleted": total_bikes_deleted,
    }
    if shopify_warnings:
        result["shopify_warnings"] = shopify_warnings
    return jsonify(result), 200


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


@api_bp.route("/bikes/<int:bike_id>", methods=["PUT"])
@handle_errors
def update_bike(bike_id: int) -> tuple:
    """Update a bike's editable fields."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    bike = models.get_bike(g.db, bike_id)
    if bike is None:
        return error_response("Bike not found", 404)

    allowed = {"actual_cost", "status", "notes", "date_received"}
    update_fields: dict[str, Any] = {}
    for key in allowed:
        if key in data:
            update_fields[key] = data[key]

    if not update_fields:
        return error_response("No valid fields to update", 400)

    updated = models.update_bike(g.db, bike_id, **update_fields)
    if updated is None:
        return error_response("Bike not found", 404)

    return jsonify(updated), 200


@api_bp.route("/bikes/<int:bike_id>", methods=["DELETE"])
@handle_errors
def delete_bike(bike_id: int) -> tuple:
    """Delete a bike and its Shopify variant."""
    bike = models.get_bike(g.db, bike_id)
    if bike is None:
        return error_response("Bike not found", 404)

    shopify_warning = None
    if bike.get("shopify_variant_id"):
        try:
            product = models.get_product(g.db, bike["product_id"])
            if product and product.get("shopify_product_id"):
                from services.shopify_sync import delete_variants
                delete_variants(product, [bike["shopify_variant_id"]])
        except Exception:
            logger.warning("Shopify variant deletion failed for bike %s", bike_id, exc_info=True)
            shopify_warning = "Bike deleted locally but Shopify variant removal failed"

    models.delete_bike(g.db, bike_id)

    result: dict[str, Any] = {"message": "Bike deleted"}
    if shopify_warning:
        result["shopify_warning"] = shopify_warning
    return jsonify(result), 200


@api_bp.route("/inventory/summary", methods=["GET"])
@handle_errors
def inventory_summary() -> tuple:
    """Get inventory summary by product."""
    summary = models.get_inventory_summary(g.db)
    return jsonify(summary), 200


@api_bp.route("/bikes/manual", methods=["POST"])
@handle_errors
def create_manual_bikes() -> tuple:
    """Create bikes outside the invoice flow."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    product_id = data.get("product_id")
    quantity = data.get("quantity")

    if not product_id:
        return error_response("Missing required field: product_id", 400)
    if not quantity or int(quantity) < 1:
        return error_response("quantity must be at least 1", 400)

    quantity = int(quantity)
    cost_per_bike = float(data.get("cost_per_bike", 0))
    notes = data.get("notes")

    product = models.get_product(g.db, product_id)
    if product is None:
        return error_response("Product not found", 404)

    # Generate serial numbers
    from services.serial_generator import generate_serial_numbers
    serials = generate_serial_numbers(quantity, conn=g.db)

    # Create bike records
    bike_dicts = [
        {
            "serial_number": serial,
            "product_id": product_id,
            "actual_cost": cost_per_bike,
            "notes": notes,
        }
        for serial in serials
    ]
    bikes = models.create_bikes_bulk(g.db, bike_dicts)

    # Push to Shopify
    shopify_warnings = []
    try:
        from services.shopify_sync import create_variants_for_bikes, ensure_shopify_product

        if not product.get("shopify_product_id"):
            ensure_shopify_product(g.db, product)
            product = models.get_product(g.db, product_id)

        if product and product.get("shopify_product_id"):
            create_variants_for_bikes(bikes, product, conn=g.db)
    except Exception as exc:
        logger.warning("Shopify sync failed for manual bikes: %s", exc, exc_info=True)
        shopify_warnings.append(f"Shopify sync failed: {exc}")

    result = {"bikes": bikes, "count": len(bikes)}
    if shopify_warnings:
        result["shopify_warnings"] = shopify_warnings
    return jsonify(result), 201


@api_bp.route("/serial-counter", methods=["GET"])
@handle_errors
def get_serial_counter() -> tuple:
    """Return the current serial counter value."""
    next_serial = models.get_next_serial(g.db)
    prefix = settings.serial_prefix
    return jsonify({
        "next_serial": next_serial,
        "formatted": f"{prefix}-{next_serial:05d}",
    }), 200


@api_bp.route("/serial-counter", methods=["PUT"])
@handle_errors
def set_serial_counter() -> tuple:
    """Set the serial counter to a specific value."""
    data = request.get_json()
    if not data or "next_serial" not in data:
        return error_response("Missing required field: next_serial", 400)

    try:
        value = int(data["next_serial"])
    except (TypeError, ValueError):
        return error_response("next_serial must be an integer", 400)

    if value < 1:
        return error_response("next_serial must be at least 1", 400)

    models.set_serial_counter(g.db, value)
    prefix = settings.serial_prefix
    return jsonify({
        "next_serial": value,
        "formatted": f"{prefix}-{value:05d}",
    }), 200


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
    """Generate barcode label sheet PDF for a list of serial numbers."""
    data = request.get_json()
    if not data or "serials" not in data:
        return error_response("Request body must include 'serials' list", 400)

    if not isinstance(data["serials"], list) or not data["serials"]:
        return error_response("'serials' must be a non-empty list", 400)

    from services.barcode_generator import create_label_sheet

    output_dir = settings.label_output_dir
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "labels.pdf")

    create_label_sheet(data["serials"], output_path, conn=g.db)

    return jsonify({"path": output_path, "count": len(data["serials"])}), 200


@api_bp.route("/reconcile", methods=["POST"])
@handle_errors
def reconcile() -> tuple:
    """Reconcile local inventory with Shopify."""
    from services.reconciliation import reconcile_inventory

    results = reconcile_inventory(g.db)
    return jsonify({"mismatches": results, "total_mismatches": len(results)}), 200


# ===========================================================================
# Brand scraper endpoints
# ===========================================================================


@api_bp.route("/scrape/brand", methods=["POST"])
@handle_errors
def scrape_brand() -> tuple:
    """Scrape a brand website for product catalog data."""
    data = request.get_json()
    if not data:
        return error_response("Request body must be JSON", 400)

    url = data.get("url")
    brand_name = data.get("brand_name")
    if not url or not brand_name:
        return error_response("Missing required fields: url, brand_name", 400)

    from services.brand_scraper import ScrapeError, scrape_brand_with_retry

    try:
        result = scrape_brand_with_retry(url, brand_name)
    except ScrapeError as exc:
        return error_response(str(exc), 422)

    return jsonify(result.model_dump()), 200


@api_bp.route("/scrape/import", methods=["POST"])
@handle_errors
def scrape_import() -> tuple:
    """Batch-import scraped products into the catalog."""
    data = request.get_json()
    if not data or "products" not in data:
        return error_response("Request body must include 'products' list", 400)

    products = data["products"]
    if not isinstance(products, list) or not products:
        return error_response("'products' must be a non-empty list", 400)

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in products:
        brand = item.get("brand")
        model_name = item.get("model")
        retail_price = item.get("retail_price")

        if not brand or not model_name or retail_price is None:
            skipped.append({
                "brand": brand or "",
                "model": model_name or "",
                "color": item.get("color"),
                "size": item.get("size"),
                "reason": "Missing required fields (brand, model, retail_price)",
            })
            continue

        try:
            price = float(retail_price)
            if price < 0:
                raise ValueError
        except (TypeError, ValueError):
            skipped.append({
                "brand": brand,
                "model": model_name,
                "color": item.get("color"),
                "size": item.get("size"),
                "reason": "Invalid retail_price",
            })
            continue

        color = item.get("color") or None
        size = item.get("size") or None

        sku = generate_sku(brand, model_name, color or "", size or "")

        product = models.create_product(
            g.db,
            sku=sku,
            brand=brand,
            model=model_name,
            retail_price=price,
            color=color,
            size=size,
        )

        if product is None:
            skipped.append({
                "brand": brand,
                "model": model_name,
                "color": color,
                "size": size,
                "reason": f"Duplicate SKU: {sku}",
            })
            continue

        # Push to Shopify (best-effort)
        try:
            from services.shopify_sync import ensure_shopify_product

            ensure_shopify_product(g.db, product)
        except Exception:
            logger.warning("Shopify push failed for scraped product %s", sku, exc_info=True)

        created.append({
            "brand": brand,
            "model": model_name,
            "color": color,
            "size": size,
        })

    return jsonify({
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "skipped_count": len(skipped),
    }), 200
