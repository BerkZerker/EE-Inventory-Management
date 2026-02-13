"""Tests for services.shopify_sync — Shopify GraphQL Admin API integration."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest
import responses

from api.exceptions import ShopifySyncError
from database.models import (
    create_bike,
    create_product,
    get_bike,
    get_product,
    update_bike_status,
)
from services.shopify_sync import (
    _graphql_request,
    archive_sold_variants,
    create_variants_for_bikes,
    ensure_shopify_product,
)
from tests.conftest import _NoCloseConnection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHOPIFY_GRAPHQL_URL = "https://test.myshopify.com/admin/api/2025-10/graphql.json"


class _MockSettings:
    """Minimal settings stub for Shopify tests."""

    shopify_store_url = "test.myshopify.com"
    shopify_client_id = ""
    shopify_client_secret = ""
    shopify_access_token = "shpat_test_token"
    shopify_api_version = "2025-10"
    shopify_webhook_secret = ""
    serial_prefix = "BIKE"
    database_path = ":memory:"


def _good_extensions(available: int = 1000) -> dict:
    """Return a standard extensions block for mocked responses."""
    return {
        "cost": {
            "throttleStatus": {
                "currentlyAvailable": available,
            }
        }
    }


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace settings in shopify_sync with test values."""
    monkeypatch.setattr("services.shopify_sync.settings", _MockSettings())
    # Reset token cache between tests
    from services.shopify_sync import _token_cache
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0.0


@pytest.fixture(autouse=True)
def _reset_location_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level location cache before each test."""
    monkeypatch.setattr("services.shopify_sync._cached_location_id", None)


@pytest.fixture
def _patch_db(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace get_db in shopify_sync with a no-close wrapper around db."""
    wrapper = _NoCloseConnection(db)
    monkeypatch.setattr("services.shopify_sync.get_db", lambda _path: wrapper)


# =========================================================================
# TestGraphqlRequest
# =========================================================================


class TestGraphqlRequest:
    @responses.activate
    def test_successful_request(self) -> None:
        """Verify correct URL, headers, body, and data extraction."""
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {"products": []},
                "extensions": _good_extensions(),
            },
            status=200,
        )

        result = _graphql_request("{ products { id } }")

        assert result == {"products": []}
        assert len(responses.calls) == 1

        req = responses.calls[0].request
        assert req.headers["X-Shopify-Access-Token"] == "shpat_test_token"
        assert req.headers["Content-Type"] == "application/json"

        body = json.loads(req.body)
        assert body["query"] == "{ products { id } }"

    @responses.activate
    def test_graphql_errors_raises(self) -> None:
        """GraphQL-level errors should raise ShopifySyncError."""
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "errors": [{"message": "Throttled"}],
            },
            status=200,
        )

        with pytest.raises(ShopifySyncError, match="GraphQL errors"):
            _graphql_request("{ products { id } }")

    @responses.activate
    def test_rate_limit_backoff(self) -> None:
        """When currentlyAvailable < 100, sleep and still return data."""
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {"products": []},
                "extensions": _good_extensions(available=50),
            },
            status=200,
        )

        with patch("services.shopify_sync.time.sleep") as mock_sleep:
            result = _graphql_request("{ products { id } }")

        assert result == {"products": []}
        mock_sleep.assert_called_once()
        # wait = max(1.0, 100 - 50) / 50 = 50/50 = 1.0
        assert mock_sleep.call_args[0][0] == 1.0


# =========================================================================
# TestEnsureShopifyProduct
# =========================================================================


class TestEnsureShopifyProduct:
    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_sibling_has_product_id(self, db: sqlite3.Connection) -> None:
        """If a sibling already has a shopify_product_id, use it."""
        create_product(
            db, sku="TREK-VERVE3-BLU-M", brand="Trek", model="Verve 3",
            retail_price=1299.99, color="Blue", size="Medium",
            shopify_product_id="gid://shopify/Product/1",
        )
        product = create_product(
            db, sku="TREK-VERVE3-RED-L", brand="Trek", model="Verve 3",
            retail_price=1299.99, color="Red", size="Large",
        )
        assert product is not None

        result = ensure_shopify_product(db, product)
        assert result == "gid://shopify/Product/1"

        # Verify the product now has the shopify_product_id
        updated = get_product(db, product["id"])
        assert updated["shopify_product_id"] == "gid://shopify/Product/1"

    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_creates_new_shopify_product(self, db: sqlite3.Connection) -> None:
        """If no sibling and no Shopify match, create a new product."""
        product = create_product(
            db, sku="TREK-VERVE3-BLU-M", brand="Trek", model="Verve 3",
            retail_price=1299.99, color="Blue", size="Medium",
        )
        assert product is not None

        # Search returns no match
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {"products": {"edges": []}},
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # Create returns new product
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productCreate": {
                        "userErrors": [],
                        "product": {
                            "id": "gid://shopify/Product/99",
                            "title": "Trek Verve 3",
                        },
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        result = ensure_shopify_product(db, product)
        assert result == "gid://shopify/Product/99"
        assert len(responses.calls) == 2

    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_finds_existing_shopify_product(self, db: sqlite3.Connection) -> None:
        """If Shopify search finds a matching title, use that product."""
        product = create_product(
            db, sku="TREK-VERVE3-BLU-M", brand="Trek", model="Verve 3",
            retail_price=1299.99, color="Blue", size="Medium",
        )
        assert product is not None

        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/50",
                                    "title": "Trek Verve 3",
                                }
                            }
                        ]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        result = ensure_shopify_product(db, product)
        assert result == "gid://shopify/Product/50"
        assert len(responses.calls) == 1  # Only search, no create


# =========================================================================
# TestCreateVariantsForBikes
# =========================================================================


class TestCreateVariantsForBikes:
    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_creates_variants_with_three_options(self, db: sqlite3.Connection) -> None:
        """Variants should use Color/Size/Serial option values."""
        product = create_product(
            db,
            sku="TREK-V3-BLU-M",
            brand="Trek",
            model="Verve 3",
            retail_price=1299.99,
            color="Blue",
            size="Medium",
            shopify_product_id="gid://shopify/Product/1",
        )
        assert product is not None

        bike1 = create_bike(
            db, serial_number="BIKE-001", product_id=product["id"], actual_cost=800.0
        )
        bike2 = create_bike(
            db, serial_number="BIKE-002", product_id=product["id"], actual_cost=810.0
        )

        # _get_location_id query
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "locations": {
                        "edges": [
                            {"node": {"id": "gid://shopify/Location/1"}}
                        ]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # productVariantsBulkCreate mutation
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productVariantsBulkCreate": {
                        "userErrors": [],
                        "productVariants": [
                            {
                                "id": "gid://shopify/ProductVariant/100",
                                "title": "BIKE-001",
                                "sku": "BIKE-001",
                            },
                            {
                                "id": "gid://shopify/ProductVariant/101",
                                "title": "BIKE-002",
                                "sku": "BIKE-002",
                            },
                        ],
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # _delete_default_variant: get variants query
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "product": {
                        "variants": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "gid://shopify/ProductVariant/999",
                                        "selectedOptions": [
                                            {"name": "Color", "value": "Default"},
                                            {"name": "Size", "value": "Default"},
                                            {"name": "Serial", "value": "Default"},
                                        ],
                                    }
                                }
                            ]
                        }
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # _delete_default_variant: delete mutation
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productVariantsBulkDelete": {
                        "userErrors": [],
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        created = create_variants_for_bikes([bike1, bike2], product)

        assert len(created) == 2
        assert created[0]["sku"] == "BIKE-001"
        assert created[1]["sku"] == "BIKE-002"

        # Verify local DB was updated
        updated_bike1 = get_bike(db, bike1["id"])
        assert updated_bike1 is not None
        assert updated_bike1["shopify_variant_id"] == "gid://shopify/ProductVariant/100"

        updated_bike2 = get_bike(db, bike2["id"])
        assert updated_bike2 is not None
        assert updated_bike2["shopify_variant_id"] == "gid://shopify/ProductVariant/101"

        # Verify option values in the request
        request_body = json.loads(responses.calls[1].request.body)
        variant_input = request_body["variables"]["variants"][0]
        option_values = variant_input["optionValues"]
        assert len(option_values) == 3
        names = {ov["optionName"] for ov in option_values}
        assert names == {"Color", "Size", "Serial"}

        # Verify inventoryQuantities uses InventoryLevelInput format
        inv_qty = variant_input["inventoryQuantities"][0]
        assert inv_qty["locationId"] == "gid://shopify/Location/1"
        assert inv_qty["availableQuantity"] == 1
        assert "name" not in inv_qty
        assert "quantity" not in inv_qty

    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_partial_failure(self, db: sqlite3.Connection) -> None:
        """userErrors should be logged but successful variants still processed."""
        product = create_product(
            db,
            sku="TREK-V3",
            brand="Trek",
            model="Verve 3",
            retail_price=1299.99,
            shopify_product_id="gid://shopify/Product/1",
        )
        assert product is not None

        bike1 = create_bike(
            db, serial_number="BIKE-001", product_id=product["id"], actual_cost=800.0
        )
        bike2 = create_bike(
            db, serial_number="BIKE-002", product_id=product["id"], actual_cost=810.0
        )

        # _get_location_id
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "locations": {
                        "edges": [{"node": {"id": "gid://shopify/Location/1"}}]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # Mutation: one variant created, one failed with userErrors
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productVariantsBulkCreate": {
                        "userErrors": [
                            {"field": ["variants", "1"], "message": "SKU already exists"},
                        ],
                        "productVariants": [
                            {
                                "id": "gid://shopify/ProductVariant/100",
                                "title": "BIKE-001",
                                "sku": "BIKE-001",
                            },
                        ],
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # _delete_default_variant: get variants query
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "product": {
                        "variants": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "gid://shopify/ProductVariant/999",
                                        "selectedOptions": [
                                            {"name": "Color", "value": "Default"},
                                            {"name": "Size", "value": "Default"},
                                            {"name": "Serial", "value": "Default"},
                                        ],
                                    }
                                }
                            ]
                        }
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # _delete_default_variant: delete mutation
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productVariantsBulkDelete": {
                        "userErrors": [],
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        created = create_variants_for_bikes([bike1, bike2], product)

        # Only one variant was created
        assert len(created) == 1
        assert created[0]["sku"] == "BIKE-001"

        # Bike 1 updated, bike 2 not
        updated_bike1 = get_bike(db, bike1["id"])
        assert updated_bike1 is not None
        assert updated_bike1["shopify_variant_id"] == "gid://shopify/ProductVariant/100"

        updated_bike2 = get_bike(db, bike2["id"])
        assert updated_bike2 is not None
        assert updated_bike2["shopify_variant_id"] is None


# =========================================================================
# TestArchiveSoldVariants
# =========================================================================


class TestArchiveSoldVariants:
    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_deletes_sold_variants(self, db: sqlite3.Connection) -> None:
        """Sold bikes with shopify_variant_id should have variants deleted."""
        product = create_product(
            db,
            sku="TREK-V3",
            brand="Trek",
            model="Verve 3",
            retail_price=1299.99,
            shopify_product_id="gid://shopify/Product/1",
        )
        assert product is not None

        bike1 = create_bike(
            db,
            serial_number="BIKE-001",
            product_id=product["id"],
            actual_cost=800.0,
            shopify_variant_id="gid://shopify/ProductVariant/100",
        )
        bike2 = create_bike(
            db,
            serial_number="BIKE-002",
            product_id=product["id"],
            actual_cost=810.0,
            shopify_variant_id="gid://shopify/ProductVariant/101",
        )

        # Mark both as sold
        update_bike_status(db, bike1["id"], "sold", sale_price=1299.99)
        update_bike_status(db, bike2["id"], "sold", sale_price=1299.99)

        # Mock the delete mutation
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productVariantsBulkDelete": {
                        "userErrors": [],
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        deleted = archive_sold_variants(product["id"])

        assert deleted == 2

        # Verify shopify_variant_id cleared in local DB
        updated_bike1 = get_bike(db, bike1["id"])
        assert updated_bike1 is not None
        assert updated_bike1["shopify_variant_id"] is None

        updated_bike2 = get_bike(db, bike2["id"])
        assert updated_bike2 is not None
        assert updated_bike2["shopify_variant_id"] is None

        # Verify the correct variant IDs were sent in the request
        request_body = json.loads(responses.calls[0].request.body)
        sent_ids = request_body["variables"]["variantsIds"]
        assert set(sent_ids) == {
            "gid://shopify/ProductVariant/100",
            "gid://shopify/ProductVariant/101",
        }
