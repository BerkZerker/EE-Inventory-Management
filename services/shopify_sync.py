"""Shopify GraphQL Admin API integration.

Handles product sync, variant creation (one per serialised bike),
inventory management, and reconciliation via the 2025-10 GraphQL API.

Supports both legacy static access tokens (``SHOPIFY_ACCESS_TOKEN``) and
the new client-credentials grant flow (``SHOPIFY_CLIENT_ID`` +
``SHOPIFY_CLIENT_SECRET``).  When client credentials are configured the
module automatically obtains and refreshes 24-hour access tokens.
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
# Token management (client-credentials grant)
# ---------------------------------------------------------------------------

_token_cache: dict[str, object] = {"access_token": None, "expires_at": 0.0}


def _obtain_access_token() -> str:
    """Return a valid Shopify access token.

    If ``SHOPIFY_CLIENT_ID`` and ``SHOPIFY_CLIENT_SECRET`` are set, uses the
    OAuth 2.0 client-credentials grant to obtain (or refresh) a short-lived
    token.  Falls back to the static ``SHOPIFY_ACCESS_TOKEN`` if client
    credentials are not configured.
    """
    # Legacy static token path
    if not settings.shopify_client_id or not settings.shopify_client_secret:
        if not settings.shopify_access_token:
            msg = (
                "Shopify credentials not configured. "
                "Set SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET, "
                "or the legacy SHOPIFY_ACCESS_TOKEN."
            )
            raise RuntimeError(msg)
        return settings.shopify_access_token

    # Return cached token if still valid (with 60 s margin)
    if _token_cache["access_token"] and time.time() < (_token_cache["expires_at"] - 60):  # type: ignore[operator]
        return _token_cache["access_token"]  # type: ignore[return-value]

    url = f"https://{settings.shopify_store_url}/admin/oauth/access_token"
    resp = requests.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.shopify_client_id,
            "client_secret": settings.shopify_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    token = data["access_token"]
    expires_in = data.get("expires_in", 86399)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = time.time() + expires_in

    logger.info("Obtained Shopify access token (expires in %ds)", expires_in)
    return token


# ---------------------------------------------------------------------------
# Core GraphQL helper
# ---------------------------------------------------------------------------


def _graphql_request(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL request against the Shopify Admin API.

    Handles HTTP errors, GraphQL-level errors, and rate-limit back-off.
    Returns the ``data`` dict from the response.
    """
    access_token = _obtain_access_token()

    url = (
        f"https://{settings.shopify_store_url}"
        f"/admin/api/{settings.shopify_api_version}/graphql.json"
    )
    headers = {
        "X-Shopify-Access-Token": access_token,
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
# Ensure Shopify product exists (push-based sync)
# ---------------------------------------------------------------------------

_SEARCH_PRODUCTS_QUERY = """
query SearchProducts($query: String!) {
  products(first: 5, query: $query) {
    edges {
      node {
        id
        title
      }
    }
  }
}
"""

_CREATE_PRODUCT_MUTATION = """
mutation CreateProduct($input: ProductInput!) {
  productCreate(input: $input) {
    userErrors {
      field
      message
    }
    product {
      id
      title
    }
  }
}
"""


def ensure_shopify_product(conn, product: dict) -> str | None:
    """Ensure a Shopify product exists for this brand+model.

    1. Check if sibling products (same brand+model) already have a shopify_product_id.
    2. If not, search Shopify by title "Brand Model".
    3. If not found, create a new Shopify product with 3 options (Color, Size, Serial).
    4. Save shopify_product_id on all sibling products.

    Returns the shopify_product_id or None on failure.
    """
    brand = product.get("brand", "")
    model = product.get("model", "")
    title = f"{brand} {model}".strip()

    if not title:
        return None

    # 1. Check siblings for existing shopify_product_id
    siblings = models.get_products_by_brand_model(conn, brand, model)
    for sib in siblings:
        if sib.get("shopify_product_id"):
            # Propagate to all siblings that don't have it yet
            for s in siblings:
                if not s.get("shopify_product_id"):
                    models.update_product(
                        conn, s["id"],
                        shopify_product_id=sib["shopify_product_id"],
                    )
            return sib["shopify_product_id"]

    # 2. Search Shopify by title
    try:
        data = _graphql_request(
            _SEARCH_PRODUCTS_QUERY,
            {"query": f"title:'{title}'"},
        )
        for edge in data["products"]["edges"]:
            if edge["node"]["title"].lower() == title.lower():
                shopify_pid = edge["node"]["id"]
                for s in siblings:
                    models.update_product(
                        conn, s["id"], shopify_product_id=shopify_pid,
                    )
                return shopify_pid
    except Exception:
        logger.warning("Shopify product search failed for '%s'", title)

    # 3. Create new Shopify product with 3 options
    try:
        data = _graphql_request(
            _CREATE_PRODUCT_MUTATION,
            {
                "input": {
                    "title": title,
                    "productOptions": [
                        {"name": "Color", "values": [{"name": "Default"}]},
                        {"name": "Size", "values": [{"name": "Default"}]},
                        {"name": "Serial", "values": [{"name": "Default"}]},
                    ],
                }
            },
        )
        result = data["productCreate"]
        if result["userErrors"]:
            logger.warning("Shopify product creation errors: %s", result["userErrors"])
            return None

        shopify_pid = result["product"]["id"]
        for s in siblings:
            models.update_product(conn, s["id"], shopify_product_id=shopify_pid)
        return shopify_pid
    except Exception:
        logger.exception("Failed to create Shopify product '%s'", title)
        return None


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

    Each bike becomes a variant with 3 option values: Color, Size, Serial.
    After creation, the local bike records are updated with their Shopify
    variant IDs.

    Returns the list of created variant dicts from Shopify.
    """
    shopify_product_id = product["shopify_product_id"]
    location_id = _get_location_id()

    color = product.get("color") or "Default"
    size = product.get("size") or "Default"

    variants_input = []
    for bike in bikes:
        variants_input.append({
            "optionValues": [
                {"optionName": "Color", "name": color},
                {"optionName": "Size", "name": size},
                {"optionName": "Serial", "name": bike["serial_number"]},
            ],
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
