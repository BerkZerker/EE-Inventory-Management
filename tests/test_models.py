"""Tests for database.models CRUD operations."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from database.models import (
    create_bike,
    create_bikes_bulk,
    create_invoice,
    create_invoice_item,
    create_invoice_items_bulk,
    create_product,
    create_webhook_log,
    delete_invoice_item,
    delete_product,
    get_bike,
    get_bike_by_serial,
    get_inventory_summary,
    get_invoice,
    get_invoice_items,
    get_invoice_with_items,
    get_next_serial,
    get_product,
    get_product_by_sku,
    get_profit_report,
    get_profit_summary,
    increment_serial_counter,
    is_duplicate_webhook,
    list_bikes,
    list_invoices,
    list_products,
    mark_bike_sold,
    update_bike,
    update_bike_status,
    update_invoice_item,
    update_invoice_status,
    update_product,
    update_webhook_status,
)

# =========================================================================
# Products
# =========================================================================


class TestCreateProduct:
    def test_create_returns_dict(self, db: sqlite3.Connection) -> None:
        product = create_product(db, sku="SKU-1", brand="Brand", model="Model A", retail_price=100.0)
        assert product is not None
        assert product["sku"] == "SKU-1"
        assert product["brand"] == "Brand"
        assert product["model"] == "Model A"
        assert product["retail_price"] == 100.0

    def test_create_with_optional_fields(self, db: sqlite3.Connection) -> None:
        product = create_product(
            db,
            sku="SKU-2",
            brand="Brand",
            model="Model B",
            retail_price=200.0,
            color="Red",
            size="Large",
            shopify_product_id="sp-123",
        )
        assert product is not None
        assert product["color"] == "Red"
        assert product["size"] == "Large"
        assert product["shopify_product_id"] == "sp-123"

    def test_create_duplicate_sku_returns_none(self, db: sqlite3.Connection) -> None:
        create_product(db, sku="DUP-SKU", brand="Dup", model="First", retail_price=100.0)
        result = create_product(db, sku="DUP-SKU", brand="Dup", model="Second", retail_price=200.0)
        assert result is None

    def test_create_has_timestamps(self, db: sqlite3.Connection) -> None:
        product = create_product(db, sku="TS-1", brand="Time", model="Stamped", retail_price=50.0)
        assert product is not None
        assert product["created_at"] is not None
        assert product["updated_at"] is not None


class TestGetProduct:
    def test_get_existing(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        result = get_product(db, sample_product["id"])
        assert result is not None
        assert result["sku"] == sample_product["sku"]

    def test_get_nonexistent(self, db: sqlite3.Connection) -> None:
        assert get_product(db, 99999) is None

    def test_get_by_sku(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        result = get_product_by_sku(db, "TREK-VERVE-3-BLUE-MEDIUM")
        assert result is not None
        assert result["id"] == sample_product["id"]

    def test_get_by_sku_nonexistent(self, db: sqlite3.Connection) -> None:
        assert get_product_by_sku(db, "NO-SUCH-SKU") is None


class TestListProducts:
    def test_list_empty(self, db: sqlite3.Connection) -> None:
        assert list_products(db) == []

    def test_list_returns_all(self, db: sqlite3.Connection) -> None:
        create_product(db, sku="A-SKU", brand="Alpha", model="Bike", retail_price=100.0)
        create_product(db, sku="B-SKU", brand="Beta", model="Bike", retail_price=200.0)
        products = list_products(db)
        assert len(products) == 2
        assert products[0]["brand"] == "Alpha"
        assert products[1]["brand"] == "Beta"


class TestUpdateProduct:
    def test_update_fields(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        updated = update_product(db, sample_product["id"], color="Green", retail_price=1399.99)
        assert updated is not None
        assert updated["color"] == "Green"
        assert updated["retail_price"] == 1399.99

    def test_update_sets_updated_at(
        self, db: sqlite3.Connection, sample_product: dict[str, Any]
    ) -> None:
        # Manually set updated_at to a past time so we can detect the change.
        db.execute(
            "UPDATE products SET updated_at = '2020-01-01 00:00:00' WHERE id = ?",
            (sample_product["id"],),
        )
        db.commit()
        updated = update_product(db, sample_product["id"], color="Red")
        assert updated is not None
        assert updated["updated_at"] != "2020-01-01 00:00:00"

    def test_update_preserves_other_fields(
        self, db: sqlite3.Connection, sample_product: dict[str, Any]
    ) -> None:
        updated = update_product(db, sample_product["id"], color="Red")
        assert updated is not None
        assert updated["brand"] == sample_product["brand"]
        assert updated["model"] == sample_product["model"]
        assert updated["retail_price"] == sample_product["retail_price"]


class TestDeleteProduct:
    def test_delete_existing(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        assert delete_product(db, sample_product["id"]) is True
        assert get_product(db, sample_product["id"]) is None

    def test_delete_nonexistent(self, db: sqlite3.Connection) -> None:
        assert delete_product(db, 99999) is False

    def test_delete_with_bikes_raises_fk(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            delete_product(db, sample_bike["product_id"])


# =========================================================================
# Invoices
# =========================================================================


class TestCreateInvoice:
    def test_create_basic(self, db: sqlite3.Connection) -> None:
        inv = create_invoice(
            db,
            invoice_ref="INV-001",
            supplier="Supplier A",
            invoice_date="2024-02-01",
        )
        assert inv["invoice_ref"] == "INV-001"
        assert inv["status"] == "pending"
        assert inv["shipping_cost"] == 0
        assert inv["discount"] == 0

    def test_create_with_all_fields(self, db: sqlite3.Connection) -> None:
        inv = create_invoice(
            db,
            invoice_ref="INV-002",
            supplier="Supplier B",
            invoice_date="2024-03-01",
            total_amount=5000.0,
            shipping_cost=100.0,
            discount=50.0,
            file_path="/invoices/inv.pdf",
            parsed_data='{"raw": "data"}',
        )
        assert inv["total_amount"] == 5000.0
        assert inv["file_path"] == "/invoices/inv.pdf"
        assert inv["parsed_data"] == '{"raw": "data"}'

    def test_create_duplicate_ref_raises(self, db: sqlite3.Connection) -> None:
        create_invoice(db, invoice_ref="DUP-INV", supplier="S", invoice_date="2024-01-01")
        with pytest.raises(sqlite3.IntegrityError):
            create_invoice(db, invoice_ref="DUP-INV", supplier="S", invoice_date="2024-01-01")


class TestGetInvoice:
    def test_get_existing(self, db: sqlite3.Connection, sample_invoice: dict[str, Any]) -> None:
        result = get_invoice(db, sample_invoice["id"])
        assert result is not None
        assert result["invoice_ref"] == sample_invoice["invoice_ref"]

    def test_get_nonexistent(self, db: sqlite3.Connection) -> None:
        assert get_invoice(db, 99999) is None


class TestGetInvoiceWithItems:
    def test_with_items(
        self,
        db: sqlite3.Connection,
        sample_invoice_with_items: dict[str, Any],
    ) -> None:
        result = get_invoice_with_items(db, sample_invoice_with_items["id"])
        assert result is not None
        assert "items" in result
        assert len(result["items"]) == 2

    def test_without_items(self, db: sqlite3.Connection, sample_invoice: dict[str, Any]) -> None:
        result = get_invoice_with_items(db, sample_invoice["id"])
        assert result is not None
        assert result["items"] == []

    def test_nonexistent_invoice(self, db: sqlite3.Connection) -> None:
        assert get_invoice_with_items(db, 99999) is None


class TestListInvoices:
    def test_list_all(self, db: sqlite3.Connection, sample_invoice: dict[str, Any]) -> None:
        create_invoice(db, invoice_ref="INV-OTHER", supplier="S", invoice_date="2024-02-01")
        invoices = list_invoices(db)
        assert len(invoices) == 2

    def test_filter_by_status(
        self, db: sqlite3.Connection, sample_invoice: dict[str, Any]
    ) -> None:
        pending = list_invoices(db, status="pending")
        assert len(pending) == 1
        approved = list_invoices(db, status="approved")
        assert len(approved) == 0


class TestUpdateInvoiceStatus:
    def test_approve(self, db: sqlite3.Connection, sample_invoice: dict[str, Any]) -> None:
        result = update_invoice_status(db, sample_invoice["id"], "approved", approved_by="admin")
        assert result is not None
        assert result["status"] == "approved"
        assert result["approved_by"] == "admin"
        assert result["approved_at"] is not None

    def test_reject(self, db: sqlite3.Connection, sample_invoice: dict[str, Any]) -> None:
        result = update_invoice_status(db, sample_invoice["id"], "rejected")
        assert result is not None
        assert result["status"] == "rejected"

    def test_invalid_status_raises(
        self, db: sqlite3.Connection, sample_invoice: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="Invalid invoice status"):
            update_invoice_status(db, sample_invoice["id"], "invalid")


# =========================================================================
# Invoice Items
# =========================================================================


class TestInvoiceItems:
    def test_create_single(self, db: sqlite3.Connection, sample_invoice: dict[str, Any]) -> None:
        item = create_invoice_item(
            db,
            invoice_id=sample_invoice["id"],
            description="Test Bike",
            quantity=1,
            unit_cost=500.0,
            total_cost=500.0,
        )
        assert item["description"] == "Test Bike"
        assert item["invoice_id"] == sample_invoice["id"]

    def test_create_with_product(
        self,
        db: sqlite3.Connection,
        sample_invoice: dict[str, Any],
        sample_product: dict[str, Any],
    ) -> None:
        item = create_invoice_item(
            db,
            invoice_id=sample_invoice["id"],
            description="Linked item",
            quantity=1,
            unit_cost=800.0,
            total_cost=800.0,
            product_id=sample_product["id"],
            allocated_cost=820.0,
        )
        assert item["product_id"] == sample_product["id"]
        assert item["allocated_cost"] == 820.0

    def test_bulk_insert(
        self,
        db: sqlite3.Connection,
        sample_invoice_with_items: dict[str, Any],
    ) -> None:
        items = get_invoice_items(db, sample_invoice_with_items["id"])
        assert len(items) == 2

    def test_update_item(
        self,
        db: sqlite3.Connection,
        sample_invoice_with_items: dict[str, Any],
    ) -> None:
        item_id = sample_invoice_with_items["items"][0]["id"]
        updated = update_invoice_item(db, item_id, quantity=5, unit_cost=750.0)
        assert updated is not None
        assert updated["quantity"] == 5
        assert updated["unit_cost"] == 750.0

    def test_delete_item(
        self,
        db: sqlite3.Connection,
        sample_invoice_with_items: dict[str, Any],
    ) -> None:
        item_id = sample_invoice_with_items["items"][0]["id"]
        assert delete_invoice_item(db, item_id) is True
        items = get_invoice_items(db, sample_invoice_with_items["id"])
        assert len(items) == 1

    def test_delete_nonexistent_item(self, db: sqlite3.Connection) -> None:
        assert delete_invoice_item(db, 99999) is False

    def test_fk_constraint_invalid_invoice(self, db: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            create_invoice_item(
                db,
                invoice_id=99999,
                description="Orphan",
                quantity=1,
                unit_cost=100.0,
                total_cost=100.0,
            )


# =========================================================================
# Bikes
# =========================================================================


class TestCreateBike:
    def test_create_basic(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        bike = create_bike(
            db,
            serial_number="BIKE-00010",
            product_id=sample_product["id"],
            actual_cost=750.0,
        )
        assert bike["serial_number"] == "BIKE-00010"
        assert bike["status"] == "available"
        assert bike["actual_cost"] == 750.0

    def test_create_with_optional_fields(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
        sample_invoice: dict[str, Any],
    ) -> None:
        bike = create_bike(
            db,
            serial_number="BIKE-00011",
            product_id=sample_product["id"],
            actual_cost=750.0,
            invoice_id=sample_invoice["id"],
            shopify_variant_id="sv-123",
            date_received="2024-02-01",
            notes="Test note",
        )
        assert bike["invoice_id"] == sample_invoice["id"]
        assert bike["shopify_variant_id"] == "sv-123"
        assert bike["notes"] == "Test note"

    def test_duplicate_serial_raises(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            create_bike(
                db,
                serial_number="BIKE-00001",
                product_id=sample_bike["product_id"],
                actual_cost=800.0,
            )

    def test_fk_constraint_invalid_product(self, db: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            create_bike(
                db,
                serial_number="BIKE-ORPHAN",
                product_id=99999,
                actual_cost=500.0,
            )


class TestCreateBikesBulk:
    def test_bulk_insert(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        bikes_data = [
            {
                "serial_number": "BULK-001",
                "product_id": sample_product["id"],
                "actual_cost": 700.0,
            },
            {
                "serial_number": "BULK-002",
                "product_id": sample_product["id"],
                "actual_cost": 710.0,
            },
            {
                "serial_number": "BULK-003",
                "product_id": sample_product["id"],
                "actual_cost": 720.0,
            },
        ]
        result = create_bikes_bulk(db, bikes_data)
        assert len(result) == 3
        serials = {b["serial_number"] for b in result}
        assert serials == {"BULK-001", "BULK-002", "BULK-003"}


class TestGetBike:
    def test_get_existing(self, db: sqlite3.Connection, sample_bike: dict[str, Any]) -> None:
        result = get_bike(db, sample_bike["id"])
        assert result is not None
        assert result["serial_number"] == "BIKE-00001"

    def test_get_nonexistent(self, db: sqlite3.Connection) -> None:
        assert get_bike(db, 99999) is None

    def test_get_by_serial(self, db: sqlite3.Connection, sample_bike: dict[str, Any]) -> None:
        result = get_bike_by_serial(db, "BIKE-00001")
        assert result is not None
        assert result["id"] == sample_bike["id"]

    def test_get_by_serial_nonexistent(self, db: sqlite3.Connection) -> None:
        assert get_bike_by_serial(db, "NO-SUCH-SERIAL") is None


class TestListBikes:
    def test_list_with_join_fields(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        bikes = list_bikes(db)
        assert len(bikes) == 1
        assert "sku" in bikes[0]
        assert "brand" in bikes[0]
        assert "model" in bikes[0]
        assert "color" in bikes[0]
        assert "size" in bikes[0]
        assert "retail_price" in bikes[0]

    def test_filter_by_product(
        self, db: sqlite3.Connection, sample_product: dict[str, Any]
    ) -> None:
        create_bike(db, serial_number="FB-001", product_id=sample_product["id"], actual_cost=500.0)
        p2 = create_product(db, sku="OTHER-SKU", brand="Other", model="Bike", retail_price=999.0)
        assert p2 is not None
        create_bike(db, serial_number="FB-002", product_id=p2["id"], actual_cost=600.0)
        bikes = list_bikes(db, product_id=sample_product["id"])
        assert len(bikes) == 1
        assert bikes[0]["serial_number"] == "FB-001"

    def test_filter_by_status(self, db: sqlite3.Connection, sample_bike: dict[str, Any]) -> None:
        available = list_bikes(db, status="available")
        assert len(available) == 1
        sold = list_bikes(db, status="sold")
        assert len(sold) == 0

    def test_pagination(self, db: sqlite3.Connection, sample_product: dict[str, Any]) -> None:
        for i in range(5):
            create_bike(
                db,
                serial_number=f"PG-{i:03d}",
                product_id=sample_product["id"],
                actual_cost=500.0,
            )
        page1 = list_bikes(db, limit=2)
        assert len(page1) == 2
        page2 = list_bikes(db, limit=2, offset=2)
        assert len(page2) == 2
        page3 = list_bikes(db, limit=2, offset=4)
        assert len(page3) == 1


class TestUpdateBikeStatus:
    def test_mark_sold(self, db: sqlite3.Connection, sample_bike: dict[str, Any]) -> None:
        result = update_bike_status(db, sample_bike["id"], "sold", sale_price=1299.99)
        assert result is not None
        assert result["status"] == "sold"
        assert result["sale_price"] == 1299.99
        assert result["date_sold"] is not None

    def test_mark_damaged(self, db: sqlite3.Connection, sample_bike: dict[str, Any]) -> None:
        result = update_bike_status(db, sample_bike["id"], "damaged")
        assert result is not None
        assert result["status"] == "damaged"

    def test_invalid_status_raises(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="Invalid bike status"):
            update_bike_status(db, sample_bike["id"], "broken")

    def test_sold_auto_sets_date_sold(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        result = update_bike_status(db, sample_bike["id"], "sold")
        assert result is not None
        assert result["date_sold"] is not None

    def test_sold_with_explicit_date(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        result = update_bike_status(db, sample_bike["id"], "sold", date_sold="2024-06-15 10:00:00")
        assert result is not None
        assert result["date_sold"] == "2024-06-15 10:00:00"


class TestMarkBikeSold:
    def test_mark_sold_by_serial(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        result = mark_bike_sold(db, "BIKE-00001", sale_price=1200.0, shopify_order_id="ORD-001")
        assert result is not None
        assert result["status"] == "sold"
        assert result["sale_price"] == 1200.0
        assert result["shopify_order_id"] == "ORD-001"

    def test_mark_sold_nonexistent(self, db: sqlite3.Connection) -> None:
        assert mark_bike_sold(db, "NO-SUCH-SERIAL") is None


class TestUpdateBike:
    def test_generic_update(self, db: sqlite3.Connection, sample_bike: dict[str, Any]) -> None:
        result = update_bike(db, sample_bike["id"], notes="Updated note", actual_cost=850.0)
        assert result is not None
        assert result["notes"] == "Updated note"
        assert result["actual_cost"] == 850.0

    def test_invalid_field_raises(
        self, db: sqlite3.Connection, sample_bike: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="No valid fields"):
            update_bike(db, sample_bike["id"], nonexistent_field="bad")


# =========================================================================
# Serial Counter
# =========================================================================


class TestSerialCounter:
    def test_initial_value(self, db: sqlite3.Connection) -> None:
        assert get_next_serial(db) == 1

    def test_increment_by_one(self, db: sqlite3.Connection) -> None:
        start = increment_serial_counter(db, 1)
        assert start == 1
        assert get_next_serial(db) == 2

    def test_increment_by_many(self, db: sqlite3.Connection) -> None:
        start = increment_serial_counter(db, 5)
        assert start == 1
        assert get_next_serial(db) == 6

    def test_sequential_non_overlapping(self, db: sqlite3.Connection) -> None:
        start1 = increment_serial_counter(db, 3)
        start2 = increment_serial_counter(db, 4)
        assert start1 == 1
        assert start2 == 4
        assert get_next_serial(db) == 8

    def test_peek_does_not_increment(self, db: sqlite3.Connection) -> None:
        val1 = get_next_serial(db)
        val2 = get_next_serial(db)
        assert val1 == val2 == 1


# =========================================================================
# Webhook Log
# =========================================================================


class TestWebhookLog:
    def test_create(self, db: sqlite3.Connection) -> None:
        log = create_webhook_log(db, "wh-001", "orders/create", payload='{"order": 1}')
        assert log["webhook_id"] == "wh-001"
        assert log["topic"] == "orders/create"
        assert log["status"] == "received"
        assert log["payload"] == '{"order": 1}'

    def test_duplicate_raises(self, db: sqlite3.Connection) -> None:
        create_webhook_log(db, "wh-dup", "orders/create")
        with pytest.raises(sqlite3.IntegrityError):
            create_webhook_log(db, "wh-dup", "orders/create")

    def test_is_duplicate(self, db: sqlite3.Connection) -> None:
        assert is_duplicate_webhook(db, "wh-check") is False
        create_webhook_log(db, "wh-check", "orders/create")
        assert is_duplicate_webhook(db, "wh-check") is True

    def test_update_status_processed(self, db: sqlite3.Connection) -> None:
        create_webhook_log(db, "wh-upd", "orders/create")
        assert update_webhook_status(db, "wh-upd", "processed") is True

    def test_update_status_failed(self, db: sqlite3.Connection) -> None:
        create_webhook_log(db, "wh-fail", "orders/create")
        assert update_webhook_status(db, "wh-fail", "failed", error="timeout") is True

    def test_update_nonexistent(self, db: sqlite3.Connection) -> None:
        assert update_webhook_status(db, "no-such-wh", "processed") is False


# =========================================================================
# Reporting
# =========================================================================


class TestInventorySummary:
    def test_summary_with_bikes(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        create_bike(db, serial_number="SUM-001", product_id=sample_product["id"], actual_cost=700)
        create_bike(db, serial_number="SUM-002", product_id=sample_product["id"], actual_cost=800)
        summary = get_inventory_summary(db)
        assert len(summary) == 1
        row = summary[0]
        assert row["total_bikes"] == 2
        assert row["available"] == 2
        assert row["sold"] == 0
        assert row["avg_cost"] == 750.0

    def test_summary_empty_product(
        self, db: sqlite3.Connection, sample_product: dict[str, Any]
    ) -> None:
        summary = get_inventory_summary(db)
        assert len(summary) == 1
        assert summary[0]["total_bikes"] == 0

    def test_summary_multiple_statuses(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        b1 = create_bike(
            db, serial_number="MS-001", product_id=sample_product["id"], actual_cost=700
        )
        create_bike(db, serial_number="MS-002", product_id=sample_product["id"], actual_cost=800)
        update_bike_status(db, b1["id"], "sold", sale_price=1200)
        summary = get_inventory_summary(db)
        assert summary[0]["available"] == 1
        assert summary[0]["sold"] == 1


class TestProfitReport:
    def _create_sold_bike(
        self,
        db: sqlite3.Connection,
        product_id: int,
        serial: str,
        cost: float,
        sale_price: float,
        date_sold: str,
    ) -> dict[str, Any]:
        bike = create_bike(db, serial_number=serial, product_id=product_id, actual_cost=cost)
        result = update_bike_status(
            db, bike["id"], "sold", sale_price=sale_price, date_sold=date_sold
        )
        assert result is not None
        return result

    def test_profit_report(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        self._create_sold_bike(db, sample_product["id"], "PR-001", 700.0, 1200.0, "2024-03-15")
        self._create_sold_bike(db, sample_product["id"], "PR-002", 750.0, 1300.0, "2024-03-20")
        report = get_profit_report(db, "2024-03-01", "2024-03-31")
        assert len(report) == 1
        row = report[0]
        assert row["units_sold"] == 2
        assert row["total_revenue"] == 2500.0
        assert row["total_cost"] == 1450.0
        assert row["total_profit"] == 1050.0

    def test_profit_report_date_filtering(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        self._create_sold_bike(db, sample_product["id"], "DF-001", 700.0, 1200.0, "2024-03-15")
        self._create_sold_bike(db, sample_product["id"], "DF-002", 750.0, 1300.0, "2024-04-05")
        march = get_profit_report(db, "2024-03-01", "2024-03-31")
        assert len(march) == 1
        assert march[0]["units_sold"] == 1

    def test_profit_report_empty_range(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        report = get_profit_report(db, "2024-01-01", "2024-01-31")
        assert report == []

    def test_profit_report_end_date_inclusive(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        self._create_sold_bike(db, sample_product["id"], "EI-001", 700.0, 1200.0, "2024-03-31")
        report = get_profit_report(db, "2024-03-01", "2024-03-31")
        assert len(report) == 1

    def test_profit_summary(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        self._create_sold_bike(db, sample_product["id"], "PS-001", 700.0, 1200.0, "2024-03-15")
        self._create_sold_bike(db, sample_product["id"], "PS-002", 750.0, 1300.0, "2024-03-20")
        summary = get_profit_summary(db, "2024-03-01", "2024-03-31")
        assert summary["units_sold"] == 2
        assert summary["total_revenue"] == 2500.0
        assert summary["total_cost"] == 1450.0
        assert summary["total_profit"] == 1050.0
        assert summary["margin_pct"] == 42.0

    def test_profit_summary_empty_range(self, db: sqlite3.Connection) -> None:
        summary = get_profit_summary(db, "2024-01-01", "2024-01-31")
        assert summary["units_sold"] == 0
        assert summary["total_revenue"] == 0
        assert summary["total_cost"] == 0


# =========================================================================
# Integration
# =========================================================================


class TestIntegration:
    def test_invoice_to_bikes_flow(self, db: sqlite3.Connection) -> None:
        """Full flow: create product, invoice, items, then bikes."""
        product = create_product(
            db, sku="INT-SKU-1", brand="Integration", model="Bike", retail_price=1500.0
        )
        assert product is not None

        invoice = create_invoice(
            db,
            invoice_ref="INT-INV-001",
            supplier="Integration Supplier",
            invoice_date="2024-05-01",
            total_amount=3000.0,
        )

        create_invoice_items_bulk(
            db,
            invoice["id"],
            [
                {
                    "description": "Integration Bike x2",
                    "quantity": 2,
                    "unit_cost": 1000.0,
                    "total_cost": 2000.0,
                    "product_id": product["id"],
                },
            ],
        )

        update_invoice_status(db, invoice["id"], "approved", approved_by="test")

        serial_start = increment_serial_counter(db, 2)
        bikes_data = [
            {
                "serial_number": f"BIKE-{serial_start + i:05d}",
                "product_id": product["id"],
                "actual_cost": 1000.0,
                "invoice_id": invoice["id"],
            }
            for i in range(2)
        ]
        created_bikes = create_bikes_bulk(db, bikes_data)
        assert len(created_bikes) == 2

        inv_with_items = get_invoice_with_items(db, invoice["id"])
        assert inv_with_items is not None
        assert inv_with_items["status"] == "approved"
        assert len(inv_with_items["items"]) == 1

        inv_bikes = list_bikes(db, invoice_id=invoice["id"])
        assert len(inv_bikes) == 2

    def test_sell_bike_and_check_profit(
        self,
        db: sqlite3.Connection,
        sample_product: dict[str, Any],
    ) -> None:
        """Create a bike, sell it, and verify profit reporting."""
        create_bike(
            db,
            serial_number="SELL-001",
            product_id=sample_product["id"],
            actual_cost=800.0,
        )

        sold = mark_bike_sold(
            db,
            "SELL-001",
            sale_price=1299.99,
            shopify_order_id="ORD-SELL-001",
        )
        assert sold is not None
        assert sold["status"] == "sold"

        summary = get_inventory_summary(db)
        product_summary = [s for s in summary if s["product_id"] == sample_product["id"]]
        assert len(product_summary) == 1
        assert product_summary[0]["sold"] == 1
        assert product_summary[0]["available"] == 0

        profit = get_profit_summary(db, "2020-01-01", "2030-12-31")
        assert profit["units_sold"] == 1
        assert profit["total_revenue"] == 1299.99
        assert profit["total_cost"] == 800.0
