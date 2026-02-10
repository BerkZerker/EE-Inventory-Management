"""Tests for services.shopify_sync — Shopify GraphQL Admin API integration."""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import patch

import pytest
import responses

from database.models import (
    create_bike,
    create_product,
    get_bike,
    list_bikes,
    update_bike,
    update_bike_status,
)
from services.shopify_sync import (
    _get_location_id,
    _graphql_request,
    archive_sold_variants,
    create_variants_for_bikes,
    ensure_serial_option,
    sync_products_from_shopify,
)

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


class _NoCloseConnection:
    """Wrapper around a sqlite3.Connection that ignores .close() calls.

    Prevents finally-block closes from destroying the shared in-memory fixture.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        object.__setattr__(self, "_conn", conn)

    def close(self) -> None:  # noqa: D102
        pass

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._conn, name, value)


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
        import json

        body = json.loads(req.body)
        assert body["query"] == "{ products { id } }"

    @responses.activate
    def test_graphql_errors_raises(self) -> None:
        """GraphQL-level errors should raise RuntimeError."""
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "errors": [{"message": "Throttled"}],
            },
            status=200,
        )

        with pytest.raises(RuntimeError, match="GraphQL errors"):
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
# TestSyncProducts
# =========================================================================


class TestSyncProducts:
    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_sync_creates_products(self, db: sqlite3.Connection) -> None:
        """Products from Shopify should be created in the local DB."""
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/1",
                                    "title": "Trek Verve 3",
                                    "variants": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "gid://shopify/ProductVariant/10",
                                                    "sku": "TREK-V3-BLU",
                                                    "price": "1299.99",
                                                    "inventoryItem": {
                                                        "unitCost": {
                                                            "amount": "800.00",
                                                        }
                                                    },
                                                }
                                            }
                                        ]
                                    },
                                }
                            }
                        ],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        count = sync_products_from_shopify()

        assert count == 1
        from database.models import get_product_by_sku

        product = get_product_by_sku(db, "TREK-V3-BLU")
        assert product is not None
        assert product["model_name"] == "Trek Verve 3"
        assert product["retail_price"] == 1299.99
        assert product["shopify_product_id"] == "gid://shopify/Product/1"

    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_sync_updates_existing(self, db: sqlite3.Connection) -> None:
        """If a product with the same SKU exists, it should be updated."""
        create_product(db, sku="TREK-V3-BLU", model_name="Old Name", retail_price=999.99)

        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/1",
                                    "title": "Trek Verve 3 Updated",
                                    "variants": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "gid://shopify/ProductVariant/10",
                                                    "sku": "TREK-V3-BLU",
                                                    "price": "1399.99",
                                                    "inventoryItem": {
                                                        "unitCost": {
                                                            "amount": "850.00",
                                                        }
                                                    },
                                                }
                                            }
                                        ]
                                    },
                                }
                            }
                        ],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        count = sync_products_from_shopify()

        assert count == 1
        from database.models import get_product_by_sku

        product = get_product_by_sku(db, "TREK-V3-BLU")
        assert product is not None
        assert product["model_name"] == "Trek Verve 3 Updated"
        assert product["retail_price"] == 1399.99

    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_sync_pagination(self, db: sqlite3.Connection) -> None:
        """Multiple pages of products should all be synced."""
        # Page 1 — hasNextPage=true
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/1",
                                    "title": "Bike A",
                                    "variants": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "gid://shopify/ProductVariant/10",
                                                    "sku": "SKU-A",
                                                    "price": "1000.00",
                                                    "inventoryItem": {
                                                        "unitCost": {"amount": "500.00"}
                                                    },
                                                }
                                            }
                                        ]
                                    },
                                }
                            }
                        ],
                        "pageInfo": {
                            "hasNextPage": True,
                            "endCursor": "cursor-page-1",
                        },
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # Page 2 — hasNextPage=false
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "products": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/2",
                                    "title": "Bike B",
                                    "variants": {
                                        "edges": [
                                            {
                                                "node": {
                                                    "id": "gid://shopify/ProductVariant/20",
                                                    "sku": "SKU-B",
                                                    "price": "2000.00",
                                                    "inventoryItem": {
                                                        "unitCost": {"amount": "900.00"}
                                                    },
                                                }
                                            }
                                        ]
                                    },
                                }
                            }
                        ],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        count = sync_products_from_shopify()

        assert count == 2
        assert len(responses.calls) == 2
        from database.models import get_product_by_sku

        assert get_product_by_sku(db, "SKU-A") is not None
        assert get_product_by_sku(db, "SKU-B") is not None


# =========================================================================
# TestEnsureSerialOption
# =========================================================================


class TestEnsureSerialOption:
    @responses.activate
    def test_option_already_exists(self) -> None:
        """If 'Serial' option already exists, no mutation should be called."""
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "product": {
                        "options": [
                            {"id": "gid://shopify/ProductOption/1", "name": "Color"},
                            {"id": "gid://shopify/ProductOption/2", "name": "Serial"},
                        ]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        option_id = ensure_serial_option("gid://shopify/Product/1")

        assert option_id == "gid://shopify/ProductOption/2"
        # Only one request (the query), no mutation
        assert len(responses.calls) == 1

    @responses.activate
    def test_creates_serial_option(self) -> None:
        """If 'Serial' option is missing, a mutation should create it."""
        # First call: query returns no Serial option
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "product": {
                        "options": [
                            {"id": "gid://shopify/ProductOption/1", "name": "Color"},
                        ]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )
        # Second call: mutation creates Serial option
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "productOptionsCreate": {
                        "userErrors": [],
                        "product": {
                            "options": [
                                {"id": "gid://shopify/ProductOption/1", "name": "Color"},
                                {"id": "gid://shopify/ProductOption/3", "name": "Serial"},
                            ]
                        },
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
        )

        option_id = ensure_serial_option("gid://shopify/Product/1")

        assert option_id == "gid://shopify/ProductOption/3"
        assert len(responses.calls) == 2


# =========================================================================
# TestCreateVariantsForBikes
# =========================================================================


class TestCreateVariantsForBikes:
    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_creates_variants(self, db: sqlite3.Connection) -> None:
        """Variants should be created and local bikes updated with variant IDs."""
        product = create_product(
            db,
            sku="TREK-V3",
            model_name="Trek Verve 3",
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

        # ensure_serial_option query — Serial already exists
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "product": {
                        "options": [
                            {"id": "gid://shopify/ProductOption/1", "name": "Serial"},
                        ]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
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

    @responses.activate
    @pytest.mark.usefixtures("_patch_db")
    def test_partial_failure(self, db: sqlite3.Connection) -> None:
        """userErrors should be logged but successful variants still processed."""
        product = create_product(
            db,
            sku="TREK-V3",
            model_name="Trek Verve 3",
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

        # ensure_serial_option — already exists
        responses.add(
            responses.POST,
            SHOPIFY_GRAPHQL_URL,
            json={
                "data": {
                    "product": {
                        "options": [
                            {"id": "gid://shopify/ProductOption/1", "name": "Serial"},
                        ]
                    }
                },
                "extensions": _good_extensions(),
            },
            status=200,
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
            model_name="Trek Verve 3",
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
        import json

        request_body = json.loads(responses.calls[0].request.body)
        sent_ids = request_body["variables"]["variantsIds"]
        assert set(sent_ids) == {
            "gid://shopify/ProductVariant/100",
            "gid://shopify/ProductVariant/101",
        }
