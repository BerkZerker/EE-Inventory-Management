"""Tests for the invoice approval service."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from database.models import (
    create_invoice,
    create_invoice_items_bulk,
    create_product,
    get_invoice,
    list_bikes,
)
from services.invoice_service import approve_invoice, check_duplicate_invoice


@pytest.fixture
def product(db: sqlite3.Connection) -> dict[str, Any]:
    p = create_product(
        db, sku="TREK-VERVE-3-BLUE-M", brand="Trek", model="Verve 3",
        retail_price=1299.99, color="Blue", size="M",
    )
    assert p is not None
    return p


@pytest.fixture
def pending_invoice(db: sqlite3.Connection, product: dict[str, Any]) -> dict[str, Any]:
    inv = create_invoice(
        db,
        invoice_ref="INV-SVC-001",
        supplier="Trek Bikes",
        invoice_date="2024-03-01",
        total_amount=2000.00,
        shipping_cost=90.00,
        discount=0.00,
    )
    create_invoice_items_bulk(
        db,
        inv["id"],
        [
            {
                "description": "Trek Verve 3",
                "quantity": 2,
                "unit_cost": 500.00,
                "total_cost": 1000.00,
                "product_id": product["id"],
            },
            {
                "description": "Trek Verve 3 variant",
                "quantity": 1,
                "unit_cost": 800.00,
                "total_cost": 800.00,
                "product_id": product["id"],
            },
        ],
    )
    return inv


class TestApproveInvoiceService:
    def test_success(self, db, pending_invoice, product) -> None:
        result = approve_invoice(db, pending_invoice["id"], push_to_shopify=False)

        assert "invoice" in result
        assert "bikes" in result
        assert "shopify_warnings" in result
        assert result["invoice"]["status"] == "approved"
        assert len(result["bikes"]) == 3
        assert result["shopify_warnings"] == []

        # Allocated costs should be set on items
        for item in result["invoice"]["items"]:
            assert item["allocated_cost"] is not None

    def test_creates_bikes_in_db(self, db, pending_invoice, product) -> None:
        approve_invoice(db, pending_invoice["id"], push_to_shopify=False)

        bikes = list_bikes(db)
        assert len(bikes) == 3
        for bike in bikes:
            assert bike["product_id"] == product["id"]
            assert bike["invoice_id"] == pending_invoice["id"]

    def test_cost_allocation(self, db, pending_invoice, product) -> None:
        result = approve_invoice(db, pending_invoice["id"], push_to_shopify=False)

        items = result["invoice"]["items"]
        # $90 shipping / 3 bikes = $30/bike
        # Item 1 (qty 2, unit $500): allocated = 530.0
        # Item 2 (qty 1, unit $800): allocated = 830.0
        assert items[0]["allocated_cost"] == 530.0
        assert items[1]["allocated_cost"] == 830.0

    def test_invoice_not_found(self, db) -> None:
        with pytest.raises(ValueError, match="Invoice not found"):
            approve_invoice(db, 999, push_to_shopify=False)

    def test_not_pending(self, db, pending_invoice, product) -> None:
        # Approve it first
        approve_invoice(db, pending_invoice["id"], push_to_shopify=False)

        # Try to approve again
        with pytest.raises(ValueError, match="pending"):
            approve_invoice(db, pending_invoice["id"], push_to_shopify=False)

    def test_missing_product_id(self, db) -> None:
        inv = create_invoice(
            db,
            invoice_ref="INV-SVC-002",
            supplier="Test",
            invoice_date="2024-03-01",
        )
        create_invoice_items_bulk(
            db,
            inv["id"],
            [
                {
                    "description": "Unmatched item",
                    "quantity": 1,
                    "unit_cost": 100.00,
                    "total_cost": 100.00,
                    "product_id": None,
                },
            ],
        )

        with pytest.raises(ValueError, match="product_id"):
            approve_invoice(db, inv["id"], push_to_shopify=False)

    def test_approved_by(self, db, pending_invoice, product) -> None:
        approve_invoice(
            db, pending_invoice["id"], push_to_shopify=False, approved_by="cli"
        )

        inv = get_invoice(db, pending_invoice["id"])
        assert inv["approved_by"] == "cli"

    def test_with_fees(self, db, product) -> None:
        inv = create_invoice(
            db,
            invoice_ref="INV-SVC-FEES",
            supplier="Test",
            invoice_date="2024-03-01",
            total_amount=1100.00,
            shipping_cost=50.00,
            discount=10.00,
            credit_card_fees=20.00,
            tax=40.00,
            other_fees=0.00,
        )
        create_invoice_items_bulk(
            db,
            inv["id"],
            [
                {
                    "description": "Test Bike",
                    "quantity": 2,
                    "unit_cost": 500.00,
                    "total_cost": 1000.00,
                    "product_id": product["id"],
                },
            ],
        )

        result = approve_invoice(db, inv["id"], push_to_shopify=False)

        # extras = 50 + 20 + 40 + 0 - 10 = 100, per bike = 50
        # allocated = 500 + 50 = 550
        assert result["invoice"]["items"][0]["allocated_cost"] == 550.0


class TestCheckDuplicateInvoice:
    def test_no_conflict(self, db) -> None:
        result = check_duplicate_invoice(db, "INV-NEW-001", overwrite=False)
        assert result is None

    def test_pending_conflict_returns_can_overwrite(self, db) -> None:
        inv = create_invoice(
            db,
            invoice_ref="INV-DUP-001",
            supplier="Test",
            invoice_date="2024-03-01",
        )
        result = check_duplicate_invoice(db, "INV-DUP-001", overwrite=False)
        assert result is not None
        assert result["status_code"] == 409
        assert result["details"]["can_overwrite"] is True
        assert result["details"]["existing_id"] == inv["id"]

    def test_pending_conflict_overwrite_deletes(self, db) -> None:
        create_invoice(
            db,
            invoice_ref="INV-DUP-002",
            supplier="Test",
            invoice_date="2024-03-01",
        )
        result = check_duplicate_invoice(db, "INV-DUP-002", overwrite=True)
        assert result is None
        # Verify invoice was deleted
        from database.models import list_invoices
        remaining = [i for i in list_invoices(db) if i["invoice_ref"] == "INV-DUP-002"]
        assert remaining == []

    def test_approved_conflict_cannot_overwrite(self, db, product) -> None:
        inv = create_invoice(
            db,
            invoice_ref="INV-DUP-003",
            supplier="Test",
            invoice_date="2024-03-01",
            total_amount=500.00,
        )
        create_invoice_items_bulk(
            db,
            inv["id"],
            [{
                "description": "Test",
                "quantity": 1,
                "unit_cost": 500.00,
                "total_cost": 500.00,
                "product_id": product["id"],
            }],
        )
        approve_invoice(db, inv["id"], push_to_shopify=False)

        result = check_duplicate_invoice(db, "INV-DUP-003", overwrite=True)
        assert result is not None
        assert result["status_code"] == 409
        assert result["details"]["can_overwrite"] is False
