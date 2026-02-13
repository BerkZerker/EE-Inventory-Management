"""Shopify webhook listener.

Runs as a separate Flask process on the webhook port.  Handles
orders/create webhooks with HMAC-SHA256 signature verification
and deduplication via the webhook_log table.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging

from flask import Flask, Request, request

from config import settings
from database.connection import get_db
import database.models as models

logger = logging.getLogger(__name__)


def verify_shopify_webhook(data: bytes, hmac_header: str) -> bool:
    """Verify Shopify webhook HMAC-SHA256 signature.

    Args:
        data: Raw request body bytes.
        hmac_header: Value of X-Shopify-Hmac-SHA256 header.

    Returns:
        True if signature is valid.
    """
    digest = hmac.new(
        settings.shopify_webhook_secret.encode("utf-8"),
        data,
        hashlib.sha256,
    ).digest()
    computed = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(computed, hmac_header)


def _process_order(conn, payload: dict) -> None:
    """Process order line items - mark matching bikes as sold.

    All bike status updates run in a single transaction so a partial
    failure rolls back cleanly.  We use ``mark_bike_sold`` with
    ``commit=False`` and issue a single commit at the end.
    """
    order_id = str(payload.get("id", ""))
    line_items = payload.get("line_items", [])

    try:
        for item in line_items:
            sku = item.get("sku", "")
            if not sku or not sku.startswith(settings.serial_prefix + "-"):
                continue

            price = None
            price_str = item.get("price")
            if price_str:
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    pass

            result = models.mark_bike_sold(
                conn, sku, sale_price=price, shopify_order_id=order_id, commit=False,
            )
            if result:
                logger.info("Marked bike %s as sold (order %s)", sku, order_id)
            else:
                logger.warning("Bike not found for SKU %s (order %s)", sku, order_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def create_webhook_app() -> Flask:
    """Create the webhook Flask application."""
    app = Flask(__name__)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    @app.route("/webhooks/orders/create", methods=["POST"])
    def handle_order_webhook():
        """Handle Shopify orders/create webhook."""
        # 1. Read raw body
        data = request.get_data()

        # 2. Verify HMAC signature
        hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
        if not hmac_header or not verify_shopify_webhook(data, hmac_header):
            logger.warning("Invalid webhook signature")
            return {"error": "Invalid signature"}, 401

        # 3. Parse JSON payload
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook body")
            return "", 200  # Still return 200 to prevent retries

        # 4. Get webhook ID for deduplication
        webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
        if not webhook_id:
            logger.warning("Missing X-Shopify-Webhook-Id header")
            return "", 200

        # 5. Open DB connection and process
        conn = get_db(settings.database_path)
        try:
            # Check deduplication
            if models.is_duplicate_webhook(conn, webhook_id):
                logger.info("Duplicate webhook %s, skipping", webhook_id)
                return "", 200

            # Log webhook
            models.create_webhook_log(
                conn, webhook_id, "orders/create", json.dumps(payload)
            )

            # Process order
            try:
                _process_order(conn, payload)
                models.update_webhook_status(conn, webhook_id, "processed")
            except Exception as exc:
                logger.exception("Error processing webhook %s", webhook_id)
                models.update_webhook_status(
                    conn, webhook_id, "failed", error=str(exc)
                )
        finally:
            conn.close()

        # Always return 200 to Shopify
        return "", 200

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    app = create_webhook_app()
    app.run(
        host=settings.webhook_host,
        port=settings.webhook_port,
        debug=False,
    )
