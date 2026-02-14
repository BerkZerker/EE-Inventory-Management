"""Tests for the Flask API endpoints."""

from __future__ import annotations

import io
from unittest.mock import patch

from database.models import (
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
        assert data[0]["sku"] == "TREK-VERVE-3-BLUE-MEDIUM"


class TestCreateProduct:
    def test_success(self, client) -> None:
        resp = client.post(
            "/api/products",
            json={
                "brand": "Test",
                "model": "Bike",
                "retail_price": 999.99,
                "color": "Red",
                "size": "Large",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["sku"] == "TEST-BIKE-RED-LARGE"
        assert data["brand"] == "Test"
        assert data["model"] == "Bike"
        assert data["retail_price"] == 999.99
        assert data["color"] == "Red"
        assert data["size"] == "Large"

    def test_duplicate_sku(self, client, sample_product) -> None:
        resp = client.post(
            "/api/products",
            json={
                "brand": "Trek",
                "model": "Verve 3",
                "retail_price": 500.00,
                "color": "Blue",
                "size": "Medium",
            },
        )
        assert resp.status_code == 409
        data = resp.get_json()
        assert "Duplicate SKU" in data["error"]

    def test_missing_fields(self, client) -> None:
        resp = client.post(
            "/api/products",
            json={"brand": "INCOMPLETE"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Missing required field" in data["error"]

    def test_negative_retail_price(self, client) -> None:
        resp = client.post(
            "/api/products",
            json={"brand": "Test", "model": "Bike", "retail_price": -100},
        )
        assert resp.status_code == 400
        assert "negative" in resp.get_json()["error"].lower()

    def test_shopify_warning_on_sync_failure(self, client) -> None:
        """When Shopify sync fails, the response includes shopify_warning."""
        with patch(
            "services.shopify_sync.ensure_shopify_product",
            side_effect=RuntimeError("Shopify down"),
        ):
            resp = client.post(
                "/api/products",
                json={
                    "brand": "Warn",
                    "model": "Bike",
                    "retail_price": 999.99,
                    "color": "Red",
                    "size": "Large",
                },
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "shopify_warning" in data
        assert "Shopify sync failed" in data["shopify_warning"]

    def test_integrity_error_returns_409(self, client, db) -> None:
        """IntegrityError from the database returns 409."""
        import sqlite3

        with patch(
            "api.routes.models.create_product",
            side_effect=sqlite3.IntegrityError("UNIQUE constraint failed"),
        ):
            resp = client.post(
                "/api/products",
                json={
                    "brand": "Dup",
                    "model": "Bike",
                    "retail_price": 500.00,
                },
            )
        assert resp.status_code == 409


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
            brand="Delete",
            model="Me",
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
                    brand="Test",
                    model="Bike Model",
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

    def test_duplicate_returns_409_with_can_overwrite(self, client, db) -> None:
        """Uploading a duplicate pending invoice returns 409 with can_overwrite."""
        parsed = ParsedInvoice(
            supplier="Test Supplier",
            invoice_number="INV-DUP-001",
            invoice_date="2024-03-15",
            items=[
                ParsedInvoiceItem(
                    model="Bike", quantity=1, unit_cost=500, total_cost=500,
                ),
            ],
            total=500.00,
        )

        with patch("api.routes.parse_invoice_with_retry", return_value=parsed):
            data = {"file": (io.BytesIO(b"fake pdf"), "invoice.pdf")}
            resp = client.post("/api/invoices/upload", data=data, content_type="multipart/form-data")
            assert resp.status_code == 201

            # Upload again — should get 409 with can_overwrite
            data = {"file": (io.BytesIO(b"fake pdf"), "invoice.pdf")}
            resp = client.post("/api/invoices/upload", data=data, content_type="multipart/form-data")
            assert resp.status_code == 409
            result = resp.get_json()
            assert result["details"]["can_overwrite"] is True

    def test_overwrite_replaces_pending(self, client, db) -> None:
        """Uploading with overwrite=true replaces a pending invoice."""
        parsed = ParsedInvoice(
            supplier="Test Supplier",
            invoice_number="INV-OVER-001",
            invoice_date="2024-03-15",
            items=[
                ParsedInvoiceItem(
                    model="Bike", quantity=1, unit_cost=500, total_cost=500,
                ),
            ],
            total=500.00,
        )

        with patch("api.routes.parse_invoice_with_retry", return_value=parsed):
            data = {"file": (io.BytesIO(b"fake pdf"), "invoice.pdf")}
            resp = client.post("/api/invoices/upload", data=data, content_type="multipart/form-data")
            assert resp.status_code == 201
            old_id = resp.get_json()["id"]

            # Re-upload with overwrite
            data = {
                "file": (io.BytesIO(b"fake pdf"), "invoice.pdf"),
                "overwrite": "true",
            }
            resp = client.post("/api/invoices/upload", data=data, content_type="multipart/form-data")
            assert resp.status_code == 201
            new_id = resp.get_json()["id"]
            assert new_id != old_id


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

    def test_quantity_less_than_one(self, client, db, sample_invoice_with_items, sample_product) -> None:
        invoice_id = sample_invoice_with_items["id"]
        item_id = sample_invoice_with_items["items"][0]["id"]

        resp = client.put(
            f"/api/invoices/{invoice_id}/items/{item_id}",
            json={"quantity": 0},
        )
        assert resp.status_code == 400
        assert "quantity" in resp.get_json()["error"].lower()

    def test_negative_unit_cost(self, client, db, sample_invoice_with_items, sample_product) -> None:
        invoice_id = sample_invoice_with_items["id"]
        item_id = sample_invoice_with_items["items"][0]["id"]

        resp = client.put(
            f"/api/invoices/{invoice_id}/items/{item_id}",
            json={"unit_cost": -50.0},
        )
        assert resp.status_code == 400
        assert "unit_cost" in resp.get_json()["error"].lower()


class TestApproveInvoice:
    def test_success(self, client, db, sample_product) -> None:
        # Create an invoice with all items having product_id set
        invoice = create_invoice(
            db,
            invoice_ref="INV-APPROVE-001",
            supplier="Test Supplier",
            invoice_date="2024-02-01",
            total_amount=2000.00,
            shipping_cost=90.00,
            discount=0.00,
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
        # Even allocation: $90 shipping / 3 bikes = $30/bike
        # Item 1 (qty 2, unit $500): allocated = 530.0
        # Item 2 (qty 1, unit $800): allocated = 830.0
        assert data["items"][0]["allocated_cost"] == 530.0
        assert data["items"][1]["allocated_cost"] == 830.0

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


class TestUpdateInvoice:
    def test_update_cost_fields(self, client, sample_invoice) -> None:
        resp = client.put(
            f"/api/invoices/{sample_invoice['id']}",
            json={
                "shipping_cost": 200.0,
                "discount": 25.0,
                "credit_card_fees": 15.0,
                "tax": 50.0,
                "other_fees": 5.0,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["shipping_cost"] == 200.0
        assert data["discount"] == 25.0
        assert data["credit_card_fees"] == 15.0
        assert data["tax"] == 50.0
        assert data["other_fees"] == 5.0

    def test_partial_update(self, client, sample_invoice) -> None:
        resp = client.put(
            f"/api/invoices/{sample_invoice['id']}",
            json={"shipping_cost": 99.0},
        )
        assert resp.status_code == 200
        assert resp.get_json()["shipping_cost"] == 99.0

    def test_not_pending(self, client, db, sample_invoice) -> None:
        update_invoice_status(db, sample_invoice["id"], "rejected")
        resp = client.put(
            f"/api/invoices/{sample_invoice['id']}",
            json={"shipping_cost": 99.0},
        )
        assert resp.status_code == 400
        assert "pending" in resp.get_json()["error"].lower()

    def test_not_found(self, client) -> None:
        resp = client.put("/api/invoices/9999", json={"shipping_cost": 1.0})
        assert resp.status_code == 404

    def test_no_valid_fields(self, client, sample_invoice) -> None:
        resp = client.put(
            f"/api/invoices/{sample_invoice['id']}",
            json={"status": "approved"},
        )
        assert resp.status_code == 400


class TestGetInvoicePdf:
    def test_not_found_invoice(self, client) -> None:
        resp = client.get("/api/invoices/9999/pdf")
        assert resp.status_code == 404

    def test_no_file_path(self, client, sample_invoice) -> None:
        # sample_invoice has no file_path
        resp = client.get(f"/api/invoices/{sample_invoice['id']}/pdf")
        assert resp.status_code == 404

    def test_success(self, client, db, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("config.settings.invoice_upload_dir", str(tmp_path))
        # Create a fake PDF file
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        invoice = create_invoice(
            db,
            invoice_ref="INV-PDF-TEST",
            supplier="Test",
            invoice_date="2024-01-01",
            file_path=str(pdf_file),
        )
        resp = client.get(f"/api/invoices/{invoice['id']}/pdf")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"


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
            if entry["sku"] == "TREK-VERVE-3-BLUE-MEDIUM":
                assert entry["total_bikes"] == 1
                assert entry["available"] == 1
                found = True
        assert found

    def test_empty_summary(self, client) -> None:
        resp = client.get("/api/inventory/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestManualBikeCreation:
    def test_success(self, client, sample_product) -> None:
        resp = client.post(
            "/api/bikes/manual",
            json={
                "product_id": sample_product["id"],
                "quantity": 3,
                "cost_per_bike": 750.00,
                "notes": "Floor models",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["count"] == 3
        assert len(data["bikes"]) == 3
        # Verify serial numbers are sequential
        serials = [b["serial_number"] for b in data["bikes"]]
        assert serials == ["BIKE-00001", "BIKE-00002", "BIKE-00003"]
        # Verify cost
        for bike in data["bikes"]:
            assert bike["actual_cost"] == 750.00

    def test_missing_product_id(self, client) -> None:
        resp = client.post(
            "/api/bikes/manual",
            json={"quantity": 1},
        )
        assert resp.status_code == 400
        assert "product_id" in resp.get_json()["error"]

    def test_invalid_quantity(self, client, sample_product) -> None:
        resp = client.post(
            "/api/bikes/manual",
            json={"product_id": sample_product["id"], "quantity": 0},
        )
        assert resp.status_code == 400
        assert "quantity" in resp.get_json()["error"]

    def test_product_not_found(self, client) -> None:
        resp = client.post(
            "/api/bikes/manual",
            json={"product_id": 9999, "quantity": 1},
        )
        assert resp.status_code == 404

    def test_shopify_warning_on_failure(self, client, sample_product) -> None:
        with patch(
            "services.shopify_sync.ensure_shopify_product",
            side_effect=RuntimeError("Shopify down"),
        ):
            resp = client.post(
                "/api/bikes/manual",
                json={
                    "product_id": sample_product["id"],
                    "quantity": 1,
                    "cost_per_bike": 500.00,
                },
            )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["count"] == 1
        assert "shopify_warnings" in data


class TestSerialCounter:
    def test_get_counter(self, client) -> None:
        resp = client.get("/api/serial-counter")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "next_serial" in data
        assert "formatted" in data
        assert data["next_serial"] == 1
        assert data["formatted"] == "BIKE-00001"

    def test_set_counter(self, client) -> None:
        resp = client.put(
            "/api/serial-counter",
            json={"next_serial": 100},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["next_serial"] == 100
        assert data["formatted"] == "BIKE-00100"

        # Verify it persisted
        resp = client.get("/api/serial-counter")
        assert resp.get_json()["next_serial"] == 100

    def test_set_counter_invalid(self, client) -> None:
        resp = client.put(
            "/api/serial-counter",
            json={"next_serial": 0},
        )
        assert resp.status_code == 400

    def test_set_counter_missing(self, client) -> None:
        resp = client.put(
            "/api/serial-counter",
            json={},
        )
        assert resp.status_code == 400


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
