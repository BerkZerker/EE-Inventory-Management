"""Shopify GraphQL Admin API integration.

Handles product sync, variant creation (one per serialised bike),
inventory management, and reconciliation via the 2025-10 GraphQL API.
"""

from __future__ import annotations

import logging
import time

import requests

from config import settings
from database.connection import get_db
import database.models as models

logger = logging.getLogger(__name__)

_cached_location_id: str | None = None


# ---------------------------------------------------------------------------
# Core GraphQL helper
# ---------------------------------------------------------------------------


def _graphql_request(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL request against the Shopify Admin API.

    Handles HTTP errors, GraphQL-level errors, and rate-limit back-off.
    Returns the ``data`` dict from the response.
    """
    url = (
        f"https://{settings.shopify_store_url}"
        f"/admin/api/{settings.shopify_api_version}/graphql.json"
    )
    headers = {
        "X-Shopify-Access-Token": settings.shopify_access_token,
        "Content-Type": "application/json",
    }
    body: dict = {"query": query}
    if variables is not None:
        body["variables"] = variables

    response = requests.post(url, json=body, headers=headers, timeout=30)
    response.raise_for_status()

    result = response.json()

    # GraphQL-level errors
    if "errors" in result:
        msg = f"GraphQL errors: {result['errors']}"
        raise RuntimeError(msg)

    # Rate-limit back-off
    try:
        available = result["extensions"]["cost"]["throttleStatus"]["currentlyAvailable"]
        if available < 100:
            wait = max(1.0, 100 - available) / 50
            logger.warning("Shopify rate limit low (%s available), sleeping %.1fs", available, wait)
            time.sleep(wait)
    except (KeyError, TypeError):
        pass

    return result["data"]


# ---------------------------------------------------------------------------
# Product sync
# ---------------------------------------------------------------------------

_SYNC_PRODUCTS_QUERY = """
query SyncProducts($cursor: String) {
  products(first: 50, after: $cursor) {
    edges {
      node {
        id
        title
        variants(first: 100) {
          edges {
            node {
              id
              sku
              price
              inventoryItem {
                unitCost {
                  amount
                }
              }
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def sync_products_from_shopify() -> int:
    """Import / update products from Shopify into the local database.

    Pages through all products and upserts each variant with a SKU.
    Returns the number of products synced.
    """
    conn = get_db(settings.database_path)
    try:
        cursor: str | None = None
        synced = 0

        while True:
            variables: dict = {"cursor": cursor}
            data = _graphql_request(_SYNC_PRODUCTS_QUERY, variables)

            products_data = data["products"]
            for edge in products_data["edges"]:
                node = edge["node"]
                product_gid = node["id"]
                model_name = node["title"]

                for variant_edge in node["variants"]["edges"]:
                    variant = variant_edge["node"]
                    sku = variant.get("sku")
                    if not sku:
                        continue

                    price = float(variant["price"])
                    cost = None
                    try:
                        cost = float(variant["inventoryItem"]["unitCost"]["amount"])
                    except (KeyError, TypeError):
                        pass

                    existing = models.get_product_by_sku(conn, sku)
                    if existing:
                        models.update_product(
                            conn,
                            existing["id"],
                            model_name=model_name,
                            retail_price=price,
                        )
                    else:
                        models.create_product(
                            conn,
                            sku=sku,
                            model_name=model_name,
                            retail_price=price,
                            shopify_product_id=product_gid,
                        )
                    synced += 1

            page_info = products_data["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

        return synced
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Serial option management
# ---------------------------------------------------------------------------

_GET_PRODUCT_OPTIONS_QUERY = """
query GetProductOptions($id: ID!) {
  product(id: $id) {
    options {
      id
      name
    }
  }
}
"""

_ADD_SERIAL_OPTION_MUTATION = """
mutation AddSerialOption($productId: ID!, $options: [OptionCreateInput!]!) {
  productOptionsCreate(productId: $productId, options: $options) {
    userErrors {
      field
      message
    }
    product {
      options {
        id
        name
      }
    }
  }
}
"""


def ensure_serial_option(shopify_product_id: str) -> str:
    """Ensure a 'Serial' option exists on the Shopify product.

    Returns the option ID.
    """
    data = _graphql_request(
        _GET_PRODUCT_OPTIONS_QUERY,
        {"id": shopify_product_id},
    )
    options = data["product"]["options"]

    for opt in options:
        if opt["name"] == "Serial":
            return opt["id"]

    # Create the Serial option
    data = _graphql_request(
        _ADD_SERIAL_OPTION_MUTATION,
        {
            "productId": shopify_product_id,
            "options": [{"name": "Serial", "values": [{"name": "Default"}]}],
        },
    )

    result = data["productOptionsCreate"]
    if result["userErrors"]:
        msg = f"Failed to create Serial option: {result['userErrors']}"
        raise RuntimeError(msg)

    for opt in result["product"]["options"]:
        if opt["name"] == "Serial":
            return opt["id"]

    msg = "Serial option not found after creation"
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Location ID
# ---------------------------------------------------------------------------

_LOCATIONS_QUERY = """
query { locations(first: 1) { edges { node { id } } } }
"""


def _get_location_id() -> str:
    """Return the first Shopify location ID, caching the result."""
    global _cached_location_id  # noqa: PLW0603
    if _cached_location_id is not None:
        return _cached_location_id

    data = _graphql_request(_LOCATIONS_QUERY)
    edges = data["locations"]["edges"]
    if not edges:
        msg = "No locations found in Shopify store"
        raise RuntimeError(msg)
    _cached_location_id = edges[0]["node"]["id"]
    return _cached_location_id


# ---------------------------------------------------------------------------
# Variant creation
# ---------------------------------------------------------------------------

_CREATE_VARIANTS_MUTATION = """
mutation CreateVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants) {
    userErrors {
      field
      message
    }
    productVariants {
      id
      title
      sku
    }
  }
}
"""


def create_variants_for_bikes(bikes: list[dict], product: dict) -> list[dict]:
    """Create Shopify variants for a list of bikes under a product.

    Each bike becomes a variant keyed by serial number. After creation,
    the local bike records are updated with their Shopify variant IDs.

    Returns the list of created variant dicts from Shopify.
    """
    shopify_product_id = product["shopify_product_id"]
    ensure_serial_option(shopify_product_id)
    location_id = _get_location_id()

    variants_input = []
    for bike in bikes:
        variants_input.append({
            "optionValues": [{"optionName": "Serial", "name": bike["serial_number"]}],
            "price": str(product["retail_price"]),
            "inventoryItem": {
                "cost": bike["actual_cost"],
                "sku": bike["serial_number"],
                "tracked": True,
            },
            "inventoryQuantities": [
                {
                    "locationId": location_id,
                    "name": "available",
                    "quantity": 1,
                },
            ],
        })

    data = _graphql_request(
        _CREATE_VARIANTS_MUTATION,
        {"productId": shopify_product_id, "variants": variants_input},
    )

    result = data["productVariantsBulkCreate"]

    if result["userErrors"]:
        logger.warning("Variant creation had errors: %s", result["userErrors"])

    created_variants = result["productVariants"] or []

    # Update local bike records with Shopify variant IDs
    conn = get_db(settings.database_path)
    try:
        variant_by_sku = {v["sku"]: v for v in created_variants}
        for bike in bikes:
            variant = variant_by_sku.get(bike["serial_number"])
            if variant:
                models.update_bike(conn, bike["id"], shopify_variant_id=variant["id"])
    finally:
        conn.close()

    return created_variants


# ---------------------------------------------------------------------------
# Archive sold variants
# ---------------------------------------------------------------------------

_DELETE_VARIANTS_MUTATION = """
mutation DeleteVariants($productId: ID!, $variantsIds: [ID!]!) {
  productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
    userErrors {
      field
      message
    }
  }
}
"""


def archive_sold_variants(product_id: int) -> int:
    """Delete Shopify variants for sold bikes and clear local references.

    Returns the number of variants deleted.
    """
    conn = get_db(settings.database_path)
    try:
        sold_bikes = models.list_bikes(conn, product_id=product_id, status="sold")
        to_delete = [
            b for b in sold_bikes
            if b.get("shopify_variant_id")
        ]

        if not to_delete:
            return 0

        product = models.get_product(conn, product_id)
        if not product or not product.get("shopify_product_id"):
            return 0

        variant_ids = [b["shopify_variant_id"] for b in to_delete]

        data = _graphql_request(
            _DELETE_VARIANTS_MUTATION,
            {
                "productId": product["shopify_product_id"],
                "variantsIds": variant_ids,
            },
        )

        result = data["productVariantsBulkDelete"]
        if result["userErrors"]:
            logger.warning("Variant deletion had errors: %s", result["userErrors"])

        # Clear shopify_variant_id on deleted bikes
        for bike in to_delete:
            models.update_bike(conn, bike["id"], shopify_variant_id=None)

        return len(to_delete)
    finally:
        conn.close()
