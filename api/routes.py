"""API endpoint stubs.

All endpoints return 501 until implemented in Phase 5.
"""

from __future__ import annotations

from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

_NOT_IMPLEMENTED: tuple[dict[str, str], int] = (
    {"message": "Not yet implemented"},
    501,
)


@api_bp.route("/invoices", methods=["GET"])
def list_invoices() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/invoices/upload", methods=["POST"])
def upload_invoice() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/products", methods=["GET"])
def list_products() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/bikes", methods=["GET"])
def list_bikes() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/inventory/summary", methods=["GET"])
def inventory_summary() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/reports/profit", methods=["GET"])
def profit_report() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/labels/generate", methods=["POST"])
def generate_labels() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED


@api_bp.route("/reconcile", methods=["POST"])
def reconcile() -> tuple[dict[str, str], int]:
    return _NOT_IMPLEMENTED
