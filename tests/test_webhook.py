"""Tests for webhook_server."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3

import pytest

from webhook_server import create_webhook_app, verify_shopify_webhook


class _NoCloseConnection:
    """Wrapper that ignores .close() on shared test connection."""

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)


TEST_SECRET = "test-webhook-secret"


def _sign_payload(payload_bytes: bytes, secret: str = TEST_SECRET) -> str:
    """Compute HMAC-SHA256 and base64-encode it."""
    digest = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@pytest.fixture
def webhook_client(db, monkeypatch):
    """Flask test client with mocked DB and settings."""
    wrapper = _NoCloseConnection(db)
    monkeypatch.setattr("webhook_server.get_db", lambda _path: wrapper)
    monkeypatch.setattr("webhook_server.settings.shopify_webhook_secret", TEST_SECRET)
    app = create_webhook_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# =========================================================================
# TestVerifyShopifyWebhook
# =========================================================================


class TestVerifyShopifyWebhook:
    def test_valid_signature(self, monkeypatch):
        monkeypatch.setattr("webhook_server.settings.shopify_webhook_secret", TEST_SECRET)
        payload = b'{"test": "data"}'
        signature = _sign_payload(payload, TEST_SECRET)
        assert verify_shopify_webhook(payload, signature) is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setattr("webhook_server.settings.shopify_webhook_secret", TEST_SECRET)
        payload = b'{"test": "data"}'
        signature = _sign_payload(payload, "wrong-secret")
        assert verify_shopify_webhook(payload, signature) is False

    def test_empty_signature(self, monkeypatch):
        monkeypatch.setattr("webhook_server.settings.shopify_webhook_secret", TEST_SECRET)
        payload = b'{"test": "data"}'
        assert verify_shopify_webhook(payload, "") is False


# =========================================================================
# TestWebhookHandler
# =========================================================================


class TestWebhookHandler:
    def test_missing_hmac_returns_401(self, webhook_client):
        payload = json.dumps({"id": 1}).encode()
        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_invalid_hmac_returns_401(self, webhook_client):
        payload = json.dumps({"id": 1}).encode()
        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": "bad-hmac-value",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_valid_webhook_returns_200(self, webhook_client, db):
        payload = json.dumps({
            "id": 99999,
            "line_items": [],
        }).encode()
        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(payload),
                "X-Shopify-Webhook-Id": "webhook-simple-200",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

    def test_duplicate_webhook_returns_200(self, webhook_client, db):
        payload = json.dumps({
            "id": 10001,
            "line_items": [],
        }).encode()
        headers = {
            "X-Shopify-Hmac-SHA256": _sign_payload(payload),
            "X-Shopify-Webhook-Id": "webhook-dup-test",
            "Content-Type": "application/json",
        }

        resp1 = webhook_client.post("/webhooks/orders/create", data=payload, headers=headers)
        assert resp1.status_code == 200

        resp2 = webhook_client.post("/webhooks/orders/create", data=payload, headers=headers)
        assert resp2.status_code == 200

        # Verify webhook was only logged once
        row = db.execute(
            "SELECT COUNT(*) AS cnt FROM webhook_log WHERE webhook_id = ?",
            ("webhook-dup-test",),
        ).fetchone()
        assert row["cnt"] == 1

    def test_processes_bike_sale(self, webhook_client, db, sample_product):
        from database.models import create_bike, get_bike_by_serial

        bike = create_bike(
            db,
            serial_number="BIKE-00001",
            product_id=sample_product["id"],
            actual_cost=800.0,
        )

        payload = json.dumps({
            "id": 12345,
            "line_items": [{"sku": "BIKE-00001", "price": "1299.99"}],
        }).encode()

        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(payload),
                "X-Shopify-Webhook-Id": "webhook-123",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        updated = get_bike_by_serial(db, "BIKE-00001")
        assert updated["status"] == "sold"
        assert updated["sale_price"] == 1299.99
        assert updated["shopify_order_id"] == "12345"

    def test_unknown_sku_still_succeeds(self, webhook_client, db):
        payload = json.dumps({
            "id": 20001,
            "line_items": [{"sku": "BIKE-99999", "price": "500.00"}],
        }).encode()

        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(payload),
                "X-Shopify-Webhook-Id": "webhook-unknown-sku",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

    def test_non_bike_sku_ignored(self, webhook_client, db):
        payload = json.dumps({
            "id": 30001,
            "line_items": [
                {"sku": "ACC-HELMET-RED", "price": "89.99"},
                {"sku": "GEAR-LOCK-01", "price": "29.99"},
            ],
        }).encode()

        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(payload),
                "X-Shopify-Webhook-Id": "webhook-non-bike",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        # Verify webhook was processed (no error) - status should be 'processed'
        row = db.execute(
            "SELECT status FROM webhook_log WHERE webhook_id = ?",
            ("webhook-non-bike",),
        ).fetchone()
        assert row["status"] == "processed"

    def test_invalid_json_returns_200(self, webhook_client):
        data = b"this is not valid json {{"
        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=data,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(data),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

    def test_missing_webhook_id_returns_200(self, webhook_client):
        payload = json.dumps({"id": 40001, "line_items": []}).encode()
        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

    def test_processing_error_logged(self, webhook_client, db, monkeypatch):
        payload = json.dumps({
            "id": 50001,
            "line_items": [{"sku": "BIKE-ERR01", "price": "100.00"}],
        }).encode()

        def _exploding_process(conn, payload_dict):
            raise RuntimeError("something broke")

        monkeypatch.setattr("webhook_server._process_order", _exploding_process)

        resp = webhook_client.post(
            "/webhooks/orders/create",
            data=payload,
            headers={
                "X-Shopify-Hmac-SHA256": _sign_payload(payload),
                "X-Shopify-Webhook-Id": "webhook-error-test",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        row = db.execute(
            "SELECT status, error FROM webhook_log WHERE webhook_id = ?",
            ("webhook-error-test",),
        ).fetchone()
        assert row["status"] == "failed"
        assert "something broke" in row["error"]


# =========================================================================
# TestHealthCheck
# =========================================================================


class TestHealthCheck:
    def test_health_returns_ok(self, webhook_client):
        resp = webhook_client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"status": "ok"}
