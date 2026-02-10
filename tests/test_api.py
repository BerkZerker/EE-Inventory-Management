"""Tests for the Flask API endpoints."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from database.models import (
    create_bike,
    create_invoice,
    create_invoice_items_bulk,
    create_product,
    update_invoice_status,
)
from services.invoice_parser import ParsedInvoice, ParsedInvoiceItem


# ===========================================================================
# Health check
# ===========================================================================


class TestHealthCheck:
    def test_health(self, client) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


# ===========================================================================
# Product endpoints
# ===========================================================================


class TestListProducts:
    def test_empty(self, client) -> None:
        resp = client.get("/api/products")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_with_data(self, client, sample_product) -> None:
        resp = client.get("/api/products")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["sku"] == "TREK-VERVE-3-BLU-M"


class TestCreateProduct:
    def test_success(self, client) -> None:
        resp = client.post(
            "/api/products",
            json={
                "sku": "TEST-SKU-001",
                "model_name": "Test Bike",
                "retail_price": 999.99,
                "color": "Red",
                "size": "Large",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["sku"] == "TEST-SKU-001"
        assert data["model_name"] == "Test Bike"
        assert data["retail_price"] == 999.99
        assert data["color"] == "Red"
        assert data["size"] == "Large"

    def test_duplicate_sku(self, client, sample_product) -> None:
        resp = client.post(
            "/api/products",
            json={
                "sku": "TREK-VERVE-3-BLU-M",
                "model_name": "Duplicate",
                "retail_price": 500.00,
            },
        )
        assert resp.status_code == 409
        data = resp.get_json()
        assert "Duplicate SKU" in data["error"]

    def test_missing_fields(self, client) -> None:
        resp = client.post(
            "/api/products",
            json={"sku": "INCOMPLETE"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Missing required field" in data["error"]


class TestUpdateProduct:
    def test_success(self, client, sample_product) -> None:
        resp = client.put(
            f"/api/products/{sample_product['id']}",
            json={"retail_price": 1399.99},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["retail_price"] == 1399.99

    def test_not_found(self, client) -> None:
        resp = client.put(
            "/api/products/9999",
            json={"retail_price": 1399.99},
        )
        assert resp.status_code == 404


class TestDeleteProduct:
    def test_success(self, client, db) -> None:
        # Create a product directly in the db for deletion
        product = create_product(
            db,
            sku="DELETE-ME",
            model_name="Deletable Bike",
            retail_price=500.00,
        )
        resp = client.delete(f"/api/products/{product['id']}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["message"] == "Product deleted"

    def test_not_found(self, client) -> None:
        resp = client.delete("/api/products/9999")
        assert resp.status_code == 404


# ===========================================================================
# Invoice endpoints
# ===========================================================================


class TestListInvoices:
    def test_empty(self, client) -> None:
        resp = client.get("/api/invoices")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_with_data(self, client, sample_invoice) -> None:
        resp = client.get("/api/invoices")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["invoice_ref"] == "INV-2024-01-15-001"

    def test_status_filter(self, client, db, sample_invoice) -> None:
        # The sample_invoice is pending by default
        resp = client.get("/api/invoices?status=pending")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

        resp = client.get("/api/invoices?status=approved")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 0


class TestUploadInvoice:
    def test_success(self, client, tmp_path) -> None:
        parsed = ParsedInvoice(
            supplier="Test Supplier",
            invoice_number="INV-TEST-001",
            invoice_date="2024-03-15",
            items=[
                ParsedInvoiceItem(
                    model="Test Bike Model",
                    color="Blue",
                    size="Medium",
                    quantity=2,
                    unit_cost=500.00,
                    total_cost=1000.00,
                ),
            ],
            shipping_cost=50.00,
            discount=10.00,
            total=1040.00,
        )

        with patch("api.routes.parse_invoice_with_retry", return_value=parsed):
            data = {
                "file": (io.BytesIO(b"fake pdf content"), "invoice.pdf"),
            }
            resp = client.post(
                "/api/invoices/upload",
                data=data,
                content_type="multipart/form-data",
            )

        assert resp.status_code == 201
        result = resp.get_json()
        assert result["supplier"] == "Test Supplier"
        assert result["invoice_ref"] == "INV-TEST-001"
        assert len(result["items"]) == 1
        assert result["items"][0]["description"] == "Test Bike Model"

    def test_missing_file(self, client) -> None:
        resp = client.post(
            "/api/invoices/upload",
            data={},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "No file" in data["error"]

    def test_non_pdf(self, client) -> None:
        data = {
            "file": (io.BytesIO(b"not a pdf"), "invoice.txt"),
        }
        resp = client.post(
            "/api/invoices/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "PDF" in resp.get_json()["error"]


class TestGetInvoice:
    def test_found(self, client, sample_invoice) -> None:
        resp = client.get(f"/api/invoices/{sample_invoice['id']}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["invoice_ref"] == "INV-2024-01-15-001"
        assert "items" in data

    def test_not_found(self, client) -> None:
        resp = client.get("/api/invoices/9999")
        assert resp.status_code == 404

    def test_pending_shows_preview_serials(self, client, sample_invoice_with_items) -> None:
        invoice_id = sample_invoice_with_items["id"]
        resp = client.get(f"/api/invoices/{invoice_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "pending"
        # Total quantity is 2 + 1 = 3
        assert "preview_serials" in data
        assert len(data["preview_serials"]) == 3
        assert data["preview_serials"][0] == "BIKE-00001"


class TestEditInvoiceItem:
    def test_success(self, client, db, sample_invoice_with_items, sample_product) -> None:
        invoice_id = sample_invoice_with_items["id"]
        item_id = sample_invoice_with_items["items"][0]["id"]

        resp = client.put(
            f"/api/invoices/{invoice_id}/items/{item_id}",
            json={"quantity": 5, "unit_cost": 750.00},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["quantity"] == 5
        assert data["unit_cost"] == 750.00

    def test_not_pending(self, client, db, sample_invoice_with_items, sample_product) -> None:
        invoice_id = sample_invoice_with_items["id"]
        item_id = sample_invoice_with_items["items"][0]["id"]

        # Reject the invoice to change status
        update_invoice_status(db, invoice_id, "rejected")

        resp = client.put(
            f"/api/invoices/{invoice_id}/items/{item_id}",
            json={"quantity": 5},
        )
        assert resp.status_code == 400
        assert "pending" in resp.get_json()["error"].lower()


class TestApproveInvoice:
    def test_success(self, client, db, sample_product) -> None:
        # Create an invoice with all items having product_id set
        invoice = create_invoice(
            db,
            invoice_ref="INV-APPROVE-001",
            supplier="Test Supplier",
            invoice_date="2024-02-01",
            total_amount=2000.00,
            shipping_cost=100.00,
            discount=20.00,
        )
        create_invoice_items_bulk(
            db,
            invoice["id"],
            [
                {
                    "description": "Trek Verve 3",
                    "quantity": 2,
                    "unit_cost": 500.00,
                    "total_cost": 1000.00,
                    "product_id": sample_product["id"],
                },
                {
                    "description": "Trek Verve 3 variant",
                    "quantity": 1,
                    "unit_cost": 800.00,
                    "total_cost": 800.00,
                    "product_id": sample_product["id"],
                },
            ],
        )

        resp = client.post(f"/api/invoices/{invoice['id']}/approve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "approved"
        assert "bikes" in data
        # 2 + 1 = 3 bikes
        assert len(data["bikes"]) == 3
        # All items should have allocated_cost set
        for item in data["items"]:
            assert item["allocated_cost"] is not None

    def test_missing_product_id(self, client, db, sample_invoice_with_items) -> None:
        # The second item in sample_invoice_with_items has no product_id
        invoice_id = sample_invoice_with_items["id"]

        resp = client.post(f"/api/invoices/{invoice_id}/approve")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "product_id" in data["error"]
        assert "details" in data

    def test_not_pending(self, client, db, sample_product) -> None:
        invoice = create_invoice(
            db,
            invoice_ref="INV-ALREADY-REJECTED",
            supplier="Test",
            invoice_date="2024-02-01",
        )
        update_invoice_status(db, invoice["id"], "rejected")

        resp = client.post(f"/api/invoices/{invoice['id']}/approve")
        assert resp.status_code == 400
        assert "pending" in resp.get_json()["error"].lower()


class TestRejectInvoice:
    def test_success(self, client, sample_invoice) -> None:
        resp = client.post(f"/api/invoices/{sample_invoice['id']}/reject")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "rejected"

    def test_not_pending(self, client, db, sample_invoice) -> None:
        update_invoice_status(db, sample_invoice["id"], "rejected")

        resp = client.post(f"/api/invoices/{sample_invoice['id']}/reject")
        assert resp.status_code == 400
        assert "pending" in resp.get_json()["error"].lower()


# ===========================================================================
# Bike / report endpoints
# ===========================================================================


class TestListBikes:
    def test_empty(self, client) -> None:
        resp = client.get("/api/bikes")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_with_data(self, client, sample_bike) -> None:
        resp = client.get("/api/bikes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["serial_number"] == "BIKE-00001"

    def test_filter_by_status(self, client, sample_bike) -> None:
        resp = client.get("/api/bikes?status=available")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

        resp = client.get("/api/bikes?status=sold")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 0

    def test_filter_by_product_id(self, client, sample_bike, sample_product) -> None:
        resp = client.get(f"/api/bikes?product_id={sample_product['id']}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

    def test_search_found(self, client, sample_bike) -> None:
        resp = client.get("/api/bikes?search=BIKE-00001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["serial_number"] == "BIKE-00001"

    def test_search_not_found(self, client) -> None:
        resp = client.get("/api/bikes?search=BIKE-99999")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []


class TestInventorySummary:
    def test_summary(self, client, sample_bike) -> None:
        resp = client.get("/api/inventory/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        # Find the product with our bike
        found = False
        for entry in data:
            if entry["sku"] == "TREK-VERVE-3-BLU-M":
                assert entry["total_bikes"] == 1
                assert entry["available"] == 1
                found = True
        assert found

    def test_empty_summary(self, client) -> None:
        resp = client.get("/api/inventory/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestProfitReport:
    def test_success(self, client) -> None:
        resp = client.get("/api/reports/profit?start=2024-01-01&end=2024-12-31")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "summary" in data
        assert "by_product" in data
        assert isinstance(data["by_product"], list)

    def test_missing_params(self, client) -> None:
        resp = client.get("/api/reports/profit")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "start" in data["error"]

        resp = client.get("/api/reports/profit?start=2024-01-01")
        assert resp.status_code == 400


# ===========================================================================
# Stub endpoints
# ===========================================================================


class TestGenerateLabels:
    def test_success(self, client, sample_bike) -> None:
        with patch("services.barcode_generator.create_label_sheet") as mock_labels:
            mock_labels.return_value = "/tmp/labels.pdf"
            resp = client.post(
                "/api/labels/generate",
                json={"serials": ["BIKE-00001", "BIKE-00002"]},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["count"] == 2
            assert "path" in data
            mock_labels.assert_called_once()

    def test_missing_serials(self, client) -> None:
        resp = client.post(
            "/api/labels/generate",
            json={},
        )
        assert resp.status_code == 400

    def test_empty_serials(self, client) -> None:
        resp = client.post(
            "/api/labels/generate",
            json={"serials": []},
        )
        assert resp.status_code == 400


class TestReconcile:
    def test_success_no_mismatches(self, client) -> None:
        resp = client.post("/api/reconcile")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "mismatches" in data
        assert "total_mismatches" in data
        assert data["total_mismatches"] == 0
