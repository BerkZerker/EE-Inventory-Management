"""Reconciliation service: compare local inventory with Shopify variants."""

from __future__ import annotations

import logging
import sqlite3

import database.models as models
from config import settings
from services.shopify_queries import RECONCILE_VARIANTS_QUERY
from services.shopify_sync import _graphql_request

logger = logging.getLogger(__name__)


def reconcile_inventory(conn: sqlite3.Connection) -> list[dict]:
    """Compare local inventory with Shopify variants.

    Returns list of mismatch dicts with keys:
    product_id, sku, brand, model, in_shopify_not_local, in_local_not_shopify
    """
    products = models.list_products(conn)
    results = []

    for product in products:
        shopify_pid = product.get("shopify_product_id")
        if not shopify_pid:
            continue

        try:
            data = _graphql_request(RECONCILE_VARIANTS_QUERY, {"id": shopify_pid})
        except Exception as exc:
            logger.warning(
                "Shopify variant fetch failed for product %s (%s): %s",
                product["sku"], shopify_pid, exc,
            )
            results.append({
                "product_id": product["id"],
                "sku": product["sku"],
                "brand": product["brand"],
                "model": product["model"],
                "error": str(exc),
            })
            continue

        shopify_skus = set()
        for edge in data["product"]["variants"]["edges"]:
            sku = edge["node"].get("sku", "")
            if sku.startswith(settings.serial_prefix + "-"):
                shopify_skus.add(sku)

        local_bikes = models.list_bikes(conn, product_id=product["id"], status="available")
        local_serials = {b["serial_number"] for b in local_bikes}

        in_shopify_not_local = sorted(shopify_skus - local_serials)
        in_local_not_shopify = sorted(local_serials - shopify_skus)

        if in_shopify_not_local or in_local_not_shopify:
            results.append({
                "product_id": product["id"],
                "sku": product["sku"],
                "brand": product["brand"],
                "model": product["model"],
                "in_shopify_not_local": in_shopify_not_local,
                "in_local_not_shopify": in_local_not_shopify,
            })

    return results
