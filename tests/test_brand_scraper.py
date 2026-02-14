"""Tests for services.brand_scraper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import responses

from services.brand_scraper import (
    ScrapedProduct,
    ScrapeError,
    ScrapeResult,
    _clean_model_name,
    _clean_size,
    _deduplicate_products,
    _is_bike_product,
    _scrape_shopify_json,
    scrape_brand,
    scrape_brand_with_retry,
)


# =========================================================================
# Fixtures
# =========================================================================

SHOPIFY_PRODUCTS_PAGE_1 = {
    "products": [
        {
            "title": "Discover 2",
            "options": [
                {"name": "Color", "position": 1, "values": ["Black", "Blue"]},
                {"name": "Size", "position": 2, "values": ["Small", "Large"]},
            ],
            "variants": [
                {
                    "option1": "Black",
                    "option2": "Small",
                    "option3": None,
                    "price": "1799.00",
                },
                {
                    "option1": "Black",
                    "option2": "Large",
                    "option3": None,
                    "price": "1799.00",
                },
                {
                    "option1": "Blue",
                    "option2": "Small",
                    "option3": None,
                    "price": "1799.00",
                },
            ],
        },
        {
            "title": "Thunder 1",
            "options": [
                {"name": "Colour", "position": 1, "values": ["White"]},
            ],
            "variants": [
                {
                    "option1": "White",
                    "option2": None,
                    "option3": None,
                    "price": "1299.00",
                },
            ],
        },
    ]
}

SHOPIFY_PRODUCTS_EMPTY = {"products": []}


# =========================================================================
# Shopify JSON strategy
# =========================================================================


class TestShopifyJsonScraper:
    @responses.activate
    def test_single_page(self) -> None:
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_PAGE_1,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is not None
        assert result.strategy == "shopify json"
        assert result.brand_name == "TestBrand"
        assert len(result.products) == 4
        # All products should have the user-supplied brand
        assert all(p.brand == "TestBrand" for p in result.products)

    @responses.activate
    def test_pagination(self) -> None:
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_PAGE_1,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json={
                "products": [
                    {
                        "title": "Nomad 1",
                        "options": [],
                        "variants": [
                            {"option1": None, "option2": None, "option3": None, "price": "999.00"},
                        ],
                    }
                ]
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is not None
        assert len(result.products) == 5  # 4 from page 1 + 1 from page 2

    @responses.activate
    def test_returns_none_on_404(self) -> None:
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            status=404,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is None

    @responses.activate
    def test_returns_none_on_non_json(self) -> None:
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            body="<html>Not Found</html>",
            status=200,
            content_type="text/html",
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is None

    @responses.activate
    def test_color_and_size_mapping(self) -> None:
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_PAGE_1,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is not None

        # Check Discover 2 variants have color and size
        discover_variants = [p for p in result.products if p.model == "Discover 2"]
        assert len(discover_variants) == 3
        assert discover_variants[0].color == "Black"
        assert discover_variants[0].size == "Small"

        # Thunder 1 uses "Colour" (British spelling)
        thunder_variants = [p for p in result.products if p.model == "Thunder 1"]
        assert len(thunder_variants) == 1
        assert thunder_variants[0].color == "White"
        assert thunder_variants[0].size is None

    @responses.activate
    def test_deduplication_in_shopify(self) -> None:
        """Duplicate variants in Shopify data should be deduplicated."""
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json={
                "products": [
                    {
                        "title": "Bike X",
                        "options": [{"name": "Color", "position": 1}],
                        "variants": [
                            {"option1": "Red", "option2": None, "option3": None, "price": "500.00"},
                            {"option1": "Red", "option2": None, "option3": None, "price": "500.00"},
                        ],
                    }
                ]
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is not None
        assert len(result.products) == 1

    @responses.activate
    def test_trailing_slash_url(self) -> None:
        """URL with trailing slash should work correctly."""
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_PAGE_1,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com/", "TestBrand")
        assert result is not None
        assert len(result.products) == 4

    @responses.activate
    def test_single_size_option_treated_as_no_size(self) -> None:
        """A size option with only one value (e.g., 'One Size') should yield size=None."""
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json={
                "products": [
                    {
                        "title": "City Cruiser",
                        "product_type": "E-Bike",
                        "options": [
                            {"name": "Color", "position": 1, "values": ["Black", "White"]},
                            {"name": "Size", "position": 2, "values": ["One Size"]},
                        ],
                        "variants": [
                            {"option1": "Black", "option2": "One Size", "option3": None, "price": "1299.00"},
                            {"option1": "White", "option2": "One Size", "option3": None, "price": "1299.00"},
                        ],
                    },
                ]
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is not None
        assert len(result.products) == 2
        assert all(p.size is None for p in result.products)


# =========================================================================
# Model name cleaning
# =========================================================================


class TestCleanModelName:
    def test_strips_brand_prefix(self) -> None:
        assert _clean_model_name("Velotric Discover 2", "Velotric") == "Discover 2"

    def test_strips_brand_prefix_case_insensitive(self) -> None:
        assert _clean_model_name("VELOTRIC Discover 2", "Velotric") == "Discover 2"
        assert _clean_model_name("velotric Discover 2", "Velotric") == "Discover 2"

    def test_strips_trailing_ebike(self) -> None:
        assert _clean_model_name("Discover 2 Ebike", "Velotric") == "Discover 2"
        assert _clean_model_name("Discover 2 E-Bike", "Velotric") == "Discover 2"
        assert _clean_model_name("Discover 2 Electric Bike", "Velotric") == "Discover 2"
        assert _clean_model_name("Discover 2 Electric Bicycle", "Velotric") == "Discover 2"
        assert _clean_model_name("Discover 2 Bicycle", "Velotric") == "Discover 2"
        assert _clean_model_name("Discover 2 Bike", "Velotric") == "Discover 2"

    def test_strips_brand_and_suffix_together(self) -> None:
        assert _clean_model_name("Velotric Discover 2 E-Bike", "Velotric") == "Discover 2"

    def test_strips_separator_after_brand(self) -> None:
        assert _clean_model_name("Velotric - Discover 2", "Velotric") == "Discover 2"
        assert _clean_model_name("Velotric | Discover 2", "Velotric") == "Discover 2"

    def test_no_brand_match_leaves_title(self) -> None:
        assert _clean_model_name("Thunder 2 Step-Thru", "Velotric") == "Thunder 2 Step-Thru"

    def test_model_only_title_unchanged(self) -> None:
        assert _clean_model_name("Discover 2", "Velotric") == "Discover 2"

    def test_does_not_strip_partial_brand_match(self) -> None:
        """'Vel' should not strip from 'Velocity X'."""
        assert _clean_model_name("Velocity X", "Vel") == "Velocity X"

    def test_strips_trailing_dash_before_suffix(self) -> None:
        assert _clean_model_name("Discover 2 - E-Bike", "Velotric") == "Discover 2"


# =========================================================================
# Size cleaning
# =========================================================================


class TestCleanSize:
    def test_plain_size_labels(self) -> None:
        assert _clean_size("S") == "S"
        assert _clean_size("M") == "M"
        assert _clean_size("L") == "L"
        assert _clean_size("XS") == "XS"
        assert _clean_size("XL") == "XL"
        assert _clean_size("XXL") == "XXL"
        assert _clean_size("Small") == "Small"
        assert _clean_size("Medium") == "Medium"
        assert _clean_size("Large") == "Large"

    def test_canonicalizes_compound_sizes(self) -> None:
        assert _clean_size("X-Large") == "Extra Large"
        assert _clean_size("Extra Small") == "Extra Small"
        assert _clean_size("x-small") == "Extra Small"

    def test_extracts_size_from_noisy_string(self) -> None:
        assert _clean_size('Large (53"-64")') == "Large"
        assert _clean_size("Small (4'11\"-5'3\")") == "Small"
        assert _clean_size("M (5'4-5'8)") == "M"
        assert _clean_size("M / 5'4\"-5'8\"") == "M"
        assert _clean_size("Small - 4'11-5'3") == "Small"
        assert _clean_size("L - 5'8\"-6'1\"") == "L"

    def test_strips_surrounding_quotes(self) -> None:
        assert _clean_size('"Small"') == "Small"
        assert _clean_size("'Medium'") == "Medium"

    def test_junk_values_become_empty(self) -> None:
        assert _clean_size("One Size") == ""
        assert _clean_size("Default Title") == ""
        assert _clean_size("Regular") == ""
        assert _clean_size("N/A") == ""
        assert _clean_size("Standard") == ""
        assert _clean_size("48cm") == ""
        assert _clean_size("52") == ""
        assert _clean_size("17.5in") == ""
        assert _clean_size("OS") == ""
        assert _clean_size("Unisex") == ""

    def test_preserves_frame_styles(self) -> None:
        assert _clean_size("Step-Thru") == "Step-Thru"
        assert _clean_size("step through") == "Step-Thru"
        assert _clean_size("Low-Step") == "Low-Step"
        assert _clean_size("High-Step") == "High-Step"

    def test_empty_and_whitespace(self) -> None:
        assert _clean_size("") == ""
        assert _clean_size("  ") == ""


# =========================================================================
# Product filtering
# =========================================================================


class TestBikeProductFilter:
    def test_explicit_bike_type_included(self) -> None:
        """Products with a bike product_type are always included."""
        assert _is_bike_product({"product_type": "E-Bike", "title": "Thunder 2", "variants": []}) is True
        assert _is_bike_product({"product_type": "bicycle", "title": "City Cruiser", "variants": []}) is True
        assert _is_bike_product({"product_type": "Electric Bikes", "title": "X", "variants": []}) is True

    def test_non_bike_type_excluded(self) -> None:
        """Any product_type that doesn't contain a bike keyword is excluded."""
        assert _is_bike_product({"product_type": "Accessories", "title": "Rear Rack", "variants": []}) is False
        assert _is_bike_product({"product_type": "Helmet", "title": "Urban Helmet", "variants": []}) is False
        assert _is_bike_product({"product_type": "Apparel", "title": "Hoodie", "variants": []}) is False
        assert _is_bike_product({"product_type": "Gift Card", "title": "Gift Card", "variants": []}) is False
        assert _is_bike_product({"product_type": "Parts", "title": "Replacement Battery", "variants": []}) is False

    def test_empty_type_low_price_excluded(self) -> None:
        """No product_type + low price → excluded (accessories)."""
        assert _is_bike_product({"product_type": "", "title": "Fender Set", "variants": [{"price": "49.99"}]}) is False
        assert _is_bike_product({"product_type": "", "title": "Phone Mount", "variants": [{"price": "29.99"}]}) is False
        assert _is_bike_product({"product_type": "", "title": "Premium Lock", "variants": [{"price": "199.99"}]}) is False

    def test_empty_type_high_price_included(self) -> None:
        """No product_type + price >= $200 → included (likely a bike)."""
        assert _is_bike_product({"product_type": "", "title": "Discover 2 Step-Thru", "variants": [{"price": "1699.00"}]}) is True

    def test_empty_type_high_price_bike_tags_included(self) -> None:
        """No product_type + high price + bike tag → included."""
        assert _is_bike_product({"product_type": "", "title": "Nomad 1", "tags": "e-bike, new", "variants": [{"price": "999.00"}]}) is True

    def test_empty_type_high_price_non_bike_tags_excluded(self) -> None:
        """No product_type + high price but tags exist without bike keyword → excluded."""
        assert _is_bike_product({"product_type": "", "title": "Cargo Trailer", "tags": "accessory, cargo", "variants": [{"price": "499.00"}]}) is False

    def test_uses_max_variant_price(self) -> None:
        """Should use the highest variant price for the threshold check."""
        product = {
            "product_type": "",
            "title": "Some Product",
            "variants": [{"price": "99.00"}, {"price": "299.00"}, {"price": "149.00"}],
        }
        assert _is_bike_product(product) is True  # max price 299 >= 200

    @responses.activate
    def test_accessories_filtered_from_shopify_results(self) -> None:
        """Only bikes should appear in scraped results."""
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json={
                "products": [
                    {
                        "title": "Thunder 2",
                        "product_type": "E-Bike",
                        "options": [{"name": "Color", "position": 1}],
                        "variants": [
                            {"option1": "Black", "option2": None, "option3": None, "price": "1699.00"},
                        ],
                    },
                    {
                        "title": "Rear Fender Set",
                        "product_type": "Accessories",
                        "options": [],
                        "variants": [
                            {"option1": None, "option2": None, "option3": None, "price": "49.99"},
                        ],
                    },
                    {
                        "title": "Front Light",
                        "product_type": "Accessories",
                        "options": [],
                        "variants": [
                            {"option1": None, "option2": None, "option3": None, "price": "29.99"},
                        ],
                    },
                    {
                        "title": "Branded Hoodie",
                        "product_type": "Apparel",
                        "options": [],
                        "variants": [
                            {"option1": None, "option2": None, "option3": None, "price": "59.99"},
                        ],
                    },
                    {
                        "title": "Gift Card",
                        "product_type": "Gift Card",
                        "options": [],
                        "variants": [
                            {"option1": None, "option2": None, "option3": None, "price": "100.00"},
                        ],
                    },
                ]
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "https://example.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = _scrape_shopify_json("https://example.com", "TestBrand")
        assert result is not None
        assert len(result.products) == 1
        assert result.products[0].model == "Thunder 2"


# =========================================================================
# Playwright + Gemini strategy
# =========================================================================


class TestPlaywrightGeminiScraper:
    @patch("services.brand_scraper._extract_with_gemini")
    @patch("services.brand_scraper._fetch_rendered_html")
    def test_scrape_brand_fallback(self, mock_html: MagicMock, mock_gemini: MagicMock) -> None:
        """When Shopify JSON fails, should fall back to Playwright+Gemini."""
        mock_html.return_value = "<html><body>Bikes here</body></html>"
        mock_gemini.return_value = [
            ScrapedProduct(brand="TestBrand", model="E-Bike Pro", color="Red", size="M", retail_price=2499.0),
        ]

        # Shopify will 404 → triggers fallback
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, "https://nonshopify.com/products.json", status=404)
            result = scrape_brand("https://nonshopify.com", "TestBrand")

        assert result.strategy == "playwright gemini"
        assert len(result.products) == 1
        assert result.products[0].model == "E-Bike Pro"
        mock_html.assert_called_once_with("https://nonshopify.com")
        mock_gemini.assert_called_once()

    @patch("services.brand_scraper._extract_with_gemini")
    @patch("services.brand_scraper._fetch_rendered_html")
    def test_gemini_deduplication(self, mock_html: MagicMock, mock_gemini: MagicMock) -> None:
        mock_html.return_value = "<html></html>"
        mock_gemini.return_value = [
            ScrapedProduct(brand="B", model="M1", color="Red", size=None, retail_price=100.0),
            ScrapedProduct(brand="B", model="m1", color="red", size=None, retail_price=100.0),
        ]

        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, "https://example.com/products.json", status=404)
            result = scrape_brand("https://example.com", "B")

        assert len(result.products) == 1


# =========================================================================
# Deduplication
# =========================================================================


class TestDeduplication:
    def test_exact_duplicates(self) -> None:
        products = [
            ScrapedProduct(brand="A", model="B", color="Red", size="M", retail_price=100.0),
            ScrapedProduct(brand="A", model="B", color="Red", size="M", retail_price=100.0),
        ]
        result = _deduplicate_products(products)
        assert len(result) == 1

    def test_case_insensitive(self) -> None:
        products = [
            ScrapedProduct(brand="Trek", model="Verve", color="Blue", size="Large", retail_price=100.0),
            ScrapedProduct(brand="trek", model="verve", color="blue", size="large", retail_price=100.0),
        ]
        result = _deduplicate_products(products)
        assert len(result) == 1

    def test_different_products_kept(self) -> None:
        products = [
            ScrapedProduct(brand="A", model="B", color="Red", size="M", retail_price=100.0),
            ScrapedProduct(brand="A", model="B", color="Blue", size="M", retail_price=100.0),
            ScrapedProduct(brand="A", model="C", color="Red", size="M", retail_price=200.0),
        ]
        result = _deduplicate_products(products)
        assert len(result) == 3

    def test_none_color_size(self) -> None:
        products = [
            ScrapedProduct(brand="A", model="B", color=None, size=None, retail_price=100.0),
            ScrapedProduct(brand="A", model="B", color=None, size=None, retail_price=100.0),
        ]
        result = _deduplicate_products(products)
        assert len(result) == 1


# =========================================================================
# Retry logic
# =========================================================================


class TestRetry:
    @patch("services.brand_scraper.scrape_brand")
    def test_returns_on_first_success(self, mock_scrape: MagicMock) -> None:
        expected = ScrapeResult(
            brand_name="B",
            source_url="https://example.com",
            strategy="shopify json",
            products=[],
        )
        mock_scrape.return_value = expected

        result = scrape_brand_with_retry("https://example.com", "B")
        assert result == expected
        assert mock_scrape.call_count == 1

    @patch("services.brand_scraper.time.sleep")
    @patch("services.brand_scraper.scrape_brand")
    def test_retries_on_failure(self, mock_scrape: MagicMock, mock_sleep: MagicMock) -> None:
        expected = ScrapeResult(
            brand_name="B",
            source_url="https://example.com",
            strategy="shopify json",
            products=[],
        )
        mock_scrape.side_effect = [RuntimeError("fail"), expected]

        result = scrape_brand_with_retry("https://example.com", "B", max_retries=3, base_delay=0.1)
        assert result == expected
        assert mock_scrape.call_count == 2
        mock_sleep.assert_called_once()

    @patch("services.brand_scraper.time.sleep")
    @patch("services.brand_scraper.scrape_brand")
    def test_raises_after_max_retries(self, mock_scrape: MagicMock, mock_sleep: MagicMock) -> None:
        mock_scrape.side_effect = RuntimeError("always fails")

        with pytest.raises(ScrapeError, match="failed after 3 retries"):
            scrape_brand_with_retry("https://example.com", "B", max_retries=3, base_delay=0.1)

        assert mock_scrape.call_count == 3

    @patch("services.brand_scraper.scrape_brand")
    def test_scrape_error_not_retried(self, mock_scrape: MagicMock) -> None:
        mock_scrape.side_effect = ScrapeError("immediate failure")

        with pytest.raises(ScrapeError, match="immediate failure"):
            scrape_brand_with_retry("https://example.com", "B")

        assert mock_scrape.call_count == 1


# =========================================================================
# Main entry point
# =========================================================================


class TestScrapeBrand:
    @responses.activate
    def test_prefers_shopify(self) -> None:
        """Should use Shopify JSON when available, not falling back."""
        responses.add(
            responses.GET,
            "https://shopify-store.com/products.json",
            json=SHOPIFY_PRODUCTS_PAGE_1,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://shopify-store.com/products.json",
            json=SHOPIFY_PRODUCTS_EMPTY,
            status=200,
        )

        result = scrape_brand("https://shopify-store.com", "TestBrand")
        assert result.strategy == "shopify json"
