"""Tests for services.invoice_parser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.invoice_parser import (
    ParsedInvoice,
    ParsedInvoiceItem,
    ParseError,
    _normalize,
    _token_overlap_score,
    allocate_costs,
    match_to_catalog,
    parse_invoice_pdf,
    parse_invoice_with_retry,
)


# =========================================================================
# Pydantic models
# =========================================================================


class TestParsedInvoiceModels:
    def test_item_required_fields(self) -> None:
        item = ParsedInvoiceItem(
            model="Trek Verve 3", quantity=2, unit_cost=800.0, total_cost=1600.0
        )
        assert item.model == "Trek Verve 3"
        assert item.color is None
        assert item.size is None

    def test_item_all_fields(self) -> None:
        item = ParsedInvoiceItem(
            model="Trek Verve 3",
            color="Blue",
            size="Medium",
            quantity=1,
            unit_cost=800.0,
            total_cost=800.0,
        )
        assert item.color == "Blue"
        assert item.size == "Medium"

    def test_invoice_defaults(self) -> None:
        invoice = ParsedInvoice(
            supplier="Trek",
            invoice_number="INV-001",
            invoice_date="2024-01-15",
            items=[],
        )
        assert invoice.shipping_cost == 0.0
        assert invoice.discount == 0.0
        assert invoice.credit_card_fees == 0.0
        assert invoice.tax == 0.0
        assert invoice.other_fees == 0.0
        assert invoice.total == 0.0

    def test_invoice_full(self) -> None:
        invoice = ParsedInvoice(
            supplier="Trek",
            invoice_number="INV-001",
            invoice_date="2024-01-15",
            items=[
                ParsedInvoiceItem(
                    model="Verve 3", quantity=2, unit_cost=800.0, total_cost=1600.0
                )
            ],
            shipping_cost=150.0,
            discount=50.0,
            credit_card_fees=25.0,
            tax=80.0,
            other_fees=10.0,
            total=1815.0,
        )
        assert len(invoice.items) == 1
        assert invoice.shipping_cost == 150.0
        assert invoice.credit_card_fees == 25.0
        assert invoice.tax == 80.0
        assert invoice.other_fees == 10.0


# =========================================================================
# allocate_costs — even-per-bike distribution
# =========================================================================


class TestAllocateCosts:
    def test_no_adjustment(self) -> None:
        """No extras → allocated cost equals unit_cost."""
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=300.0, total_cost=300.0),
        ]
        costs = allocate_costs(items, shipping=0.0, discount=0.0)
        assert costs == [100.0, 300.0]

    def test_shipping_only_even_split(self) -> None:
        """Shipping splits evenly across all bikes."""
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=300.0, total_cost=300.0),
        ]
        # 3 bikes total, $30 shipping → $10/bike
        costs = allocate_costs(items, shipping=30.0, discount=0.0)
        assert costs[0] == 110.0  # 100 + 10
        assert costs[1] == 310.0  # 300 + 10

    def test_two_bikes_with_shipping(self) -> None:
        """User's example: 2 bikes @ $1000 + $200 shipping = $1100/bike."""
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=1000.0, total_cost=2000.0),
        ]
        costs = allocate_costs(items, shipping=200.0, discount=0.0)
        assert costs == [1100.0]  # 1000 + 200/2

    def test_discount_only(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=1, unit_cost=500.0, total_cost=500.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=500.0, total_cost=500.0),
        ]
        # 2 bikes, discount $100 → -$50/bike
        costs = allocate_costs(items, shipping=0.0, discount=100.0)
        assert costs == [450.0, 450.0]

    def test_shipping_and_discount(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=3, unit_cost=100.0, total_cost=300.0),
        ]
        # 5 bikes, shipping=50, discount=25 → extras=25, 25/5=5/bike
        costs = allocate_costs(items, shipping=50.0, discount=25.0)
        assert costs[0] == 105.0  # 100 + 5
        assert costs[1] == 105.0  # 100 + 5

    def test_all_fee_types(self) -> None:
        """Test with credit_card_fees, tax, and other_fees."""
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=500.0, total_cost=1000.0),
        ]
        # extras = 50 + 30 + 20 + 10 - 10 = 100, per bike = 50
        costs = allocate_costs(
            items, shipping=50.0, discount=10.0,
            credit_card_fees=30.0, tax=20.0, other_fees=10.0,
        )
        assert costs == [550.0]

    def test_single_item(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=3, unit_cost=100.0, total_cost=300.0),
        ]
        # 3 bikes, $30 shipping → $10/bike
        costs = allocate_costs(items, shipping=30.0, discount=0.0)
        assert costs == [110.0]

    def test_penny_accurate_rounding(self) -> None:
        """Verify the remainder is applied to the last item for penny accuracy."""
        items = [
            ParsedInvoiceItem(model="A", quantity=3, unit_cost=100.0, total_cost=300.0),
            ParsedInvoiceItem(model="B", quantity=2, unit_cost=200.0, total_cost=400.0),
        ]
        # 5 bikes, shipping=1.0 → extras=1.0, per_bike=0.2
        # A: 100 + 0.2 = 100.2, B: 200 + 0.2 = 200.2
        # actual = 100.2*3 + 200.2*2 = 300.6 + 400.4 = 701
        # expected = 700 + 1 = 701 → exact, no remainder
        costs = allocate_costs(items, shipping=1.0, discount=0.0)
        actual_total = sum(c * item.quantity for c, item in zip(costs, items))
        expected_total = 701.0
        assert round(actual_total, 2) == expected_total

    def test_penny_remainder_on_last_item(self) -> None:
        """Remainder is absorbed by last item (works best when last has qty=1)."""
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=200.0, total_cost=200.0),
        ]
        # 3 bikes, shipping=1.0 → per_bike=0.33
        # A: 100.33*2=200.66, B needs 200+1-200.66=200.34
        costs = allocate_costs(items, shipping=1.0, discount=0.0)
        actual_total = sum(c * item.quantity for c, item in zip(costs, items))
        expected_total = 401.0
        assert round(actual_total, 2) == expected_total

    def test_different_quantities(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=1, unit_cost=1000.0, total_cost=1000.0),
            ParsedInvoiceItem(model="B", quantity=5, unit_cost=200.0, total_cost=1000.0),
        ]
        # 6 bikes, $120 shipping → $20/bike
        costs = allocate_costs(items, shipping=120.0, discount=0.0)
        assert costs[0] == 1020.0  # 1000 + 20
        assert costs[1] == 220.0   # 200 + 20

    def test_zero_quantity_raises(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=0, unit_cost=100.0, total_cost=0.0),
        ]
        with pytest.raises(ValueError, match="bike count is zero"):
            allocate_costs(items, shipping=10.0, discount=0.0)


# =========================================================================
# match_to_catalog
# =========================================================================


class TestMatchToCatalog:
    def _catalog(self) -> list[dict]:
        return [
            {"id": 1, "brand": "Trek", "model": "Verve 3", "color": "Blue", "size": "Medium"},
            {"id": 2, "brand": "Trek", "model": "Verve 3", "color": "Red", "size": "Large"},
            {"id": 3, "brand": "Specialized", "model": "Turbo", "color": "Black", "size": "Small"},
        ]

    def test_exact_match(self) -> None:
        item = ParsedInvoiceItem(
            brand="Trek", model="Verve 3", color="Blue", size="Medium",
            quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, self._catalog()) == 1

    def test_case_insensitive(self) -> None:
        item = ParsedInvoiceItem(
            brand="trek", model="verve 3", color="blue", size="medium",
            quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, self._catalog()) == 1

    def test_partial_model_name(self) -> None:
        item = ParsedInvoiceItem(
            model="Verve 3", quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        # "verve 3" exact matches catalog "Verve 3" → score 5
        result = match_to_catalog(item, self._catalog())
        assert result in (1, 2)  # Both Trek Verve 3 products match

    def test_no_match(self) -> None:
        item = ParsedInvoiceItem(
            brand="Giant", model="Defy", quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, self._catalog()) is None

    def test_best_match_wins(self) -> None:
        item = ParsedInvoiceItem(
            brand="Trek", model="Verve 3", color="Red", size="Large",
            quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        # Product 2 matches brand (3) + model (5) + color (2) + size (2) = 12
        # Product 1 matches brand (3) + model (5) only = 8
        assert match_to_catalog(item, self._catalog()) == 2

    def test_empty_catalog(self) -> None:
        item = ParsedInvoiceItem(
            brand="Trek", model="Verve 3", quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, []) is None

    def test_brand_field_in_item(self) -> None:
        """Test that brand field is properly handled in ParsedInvoiceItem."""
        item = ParsedInvoiceItem(
            brand="Specialized", model="Turbo", color="Black", size="Small",
            quantity=1, unit_cost=1200.0, total_cost=1200.0,
        )
        assert item.brand == "Specialized"
        assert match_to_catalog(item, self._catalog()) == 3


# =========================================================================
# parse_invoice_pdf (mocked Gemini)
# =========================================================================


class TestParseInvoicePdf:
    def test_successful_parse(self, tmp_path: Path) -> None:
        pdf_file = tmp_path / "invoice.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        mock_parsed = ParsedInvoice(
            supplier="Trek",
            invoice_number="INV-001",
            invoice_date="2024-01-15",
            items=[
                ParsedInvoiceItem(
                    model="Trek Verve 3", quantity=2, unit_cost=800.0, total_cost=1600.0
                )
            ],
            shipping_cost=50.0,
            total=1650.0,
        )

        mock_response = MagicMock()
        mock_response.parsed = mock_parsed

        mock_client = MagicMock()
        mock_client.files.upload.return_value = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("services.invoice_parser.genai.Client", return_value=mock_client):
            result = parse_invoice_pdf(pdf_file)

        assert result.supplier == "Trek"
        assert result.invoice_number == "INV-001"
        assert len(result.items) == 1
        assert result.items[0].model == "Trek Verve 3"

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="File not found"):
            parse_invoice_pdf("/nonexistent/path/invoice.pdf")

    def test_invalid_extension(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "invoice.txt"
        txt_file.write_text("not a pdf")
        with pytest.raises(ValueError, match="Expected a .pdf file"):
            parse_invoice_pdf(txt_file)

    def test_parse_error_on_null_response(self, tmp_path: Path) -> None:
        pdf_file = tmp_path / "invoice.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        mock_response = MagicMock()
        mock_response.parsed = None

        mock_client = MagicMock()
        mock_client.files.upload.return_value = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("services.invoice_parser.genai.Client", return_value=mock_client):
            with pytest.raises(ParseError, match="no parsed data"):
                parse_invoice_pdf(pdf_file)


# =========================================================================
# parse_invoice_with_retry (mocked)
# =========================================================================


class TestParseInvoiceWithRetry:
    def _make_pdf(self, tmp_path: Path) -> Path:
        pdf_file = tmp_path / "invoice.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")
        return pdf_file

    def _mock_parsed(self) -> ParsedInvoice:
        return ParsedInvoice(
            supplier="Trek",
            invoice_number="INV-001",
            invoice_date="2024-01-15",
            items=[],
        )

    def test_first_try_success(self, tmp_path: Path) -> None:
        pdf_file = self._make_pdf(tmp_path)
        expected = self._mock_parsed()

        with patch("services.invoice_parser.parse_invoice_pdf", return_value=expected):
            result = parse_invoice_with_retry(pdf_file)

        assert result == expected

    def test_retry_success(self, tmp_path: Path) -> None:
        pdf_file = self._make_pdf(tmp_path)
        expected = self._mock_parsed()

        with (
            patch(
                "services.invoice_parser.parse_invoice_pdf",
                side_effect=[RuntimeError("API error"), expected],
            ),
            patch("services.invoice_parser.time.sleep"),
        ):
            result = parse_invoice_with_retry(pdf_file, max_retries=3, base_delay=0.0)

        assert result == expected

    def test_all_retries_fail(self, tmp_path: Path) -> None:
        pdf_file = self._make_pdf(tmp_path)

        with (
            patch(
                "services.invoice_parser.parse_invoice_pdf",
                side_effect=RuntimeError("API error"),
            ),
            patch("services.invoice_parser.time.sleep"),
        ):
            with pytest.raises(ParseError, match="failed after 3 retries"):
                parse_invoice_with_retry(pdf_file, max_retries=3, base_delay=0.0)

    def test_backoff_timing(self, tmp_path: Path) -> None:
        pdf_file = self._make_pdf(tmp_path)

        sleep_calls: list[float] = []

        def mock_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with (
            patch(
                "services.invoice_parser.parse_invoice_pdf",
                side_effect=RuntimeError("API error"),
            ),
            patch("services.invoice_parser.time.sleep", side_effect=mock_sleep),
        ):
            with pytest.raises(ParseError):
                parse_invoice_with_retry(pdf_file, max_retries=3, base_delay=1.0)

        # Delays: 1*2^0=1, 1*2^1=2 (no sleep after last attempt)
        assert sleep_calls == [1.0, 2.0]

    def test_parse_error_not_retried(self, tmp_path: Path) -> None:
        """ParseError should propagate immediately without retries."""
        pdf_file = self._make_pdf(tmp_path)

        with patch(
            "services.invoice_parser.parse_invoice_pdf",
            side_effect=ParseError("no parsed data"),
        ):
            with pytest.raises(ParseError, match="no parsed data"):
                parse_invoice_with_retry(pdf_file, max_retries=3)
