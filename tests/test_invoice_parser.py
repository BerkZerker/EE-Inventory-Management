"""Tests for services.invoice_parser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.invoice_parser import (
    ParsedInvoice,
    ParsedInvoiceItem,
    ParseError,
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
            total=1700.0,
        )
        assert len(invoice.items) == 1
        assert invoice.shipping_cost == 150.0


# =========================================================================
# allocate_costs
# =========================================================================


class TestAllocateCosts:
    def test_no_adjustment(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=300.0, total_cost=300.0),
        ]
        costs = allocate_costs(items, shipping=0.0, discount=0.0)
        assert costs == [100.0, 300.0]

    def test_shipping_only(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=300.0, total_cost=300.0),
        ]
        costs = allocate_costs(items, shipping=50.0, discount=0.0)
        # A proportion = 200/500 = 0.4, B proportion = 300/500 = 0.6
        # A per-unit = (200 + 0.4*50) / 2 = 220/2 = 110.0
        # B per-unit = (300 + 0.6*50) / 1 = 330.0
        assert costs[0] == 110.0
        assert costs[1] == 330.0

    def test_discount_only(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=1, unit_cost=500.0, total_cost=500.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=500.0, total_cost=500.0),
        ]
        costs = allocate_costs(items, shipping=0.0, discount=100.0)
        # Each proportion = 0.5, net_adjustment = -100
        # A per-unit = (500 + 0.5*(-100)) / 1 = 450.0
        # B per-unit = (500 + 0.5*(-100)) / 1 = 450.0
        assert costs == [450.0, 450.0]

    def test_shipping_and_discount(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=2, unit_cost=100.0, total_cost=200.0),
            ParsedInvoiceItem(model="B", quantity=3, unit_cost=100.0, total_cost=300.0),
        ]
        costs = allocate_costs(items, shipping=50.0, discount=25.0)
        # subtotal = 500, net = 25
        # A: proportion=0.4, per-unit = (200 + 10) / 2 = 105.0
        # B: proportion=0.6, per-unit = (300 + 15) / 3 = 105.0
        assert costs[0] == 105.0
        assert costs[1] == 105.0

    def test_single_item(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=3, unit_cost=100.0, total_cost=300.0),
        ]
        costs = allocate_costs(items, shipping=30.0, discount=0.0)
        # per-unit = (300 + 30) / 3 = 110.0
        assert costs == [110.0]

    def test_penny_accurate_rounding(self) -> None:
        """Verify the remainder is applied to the last item for penny accuracy."""
        items = [
            ParsedInvoiceItem(model="A", quantity=3, unit_cost=33.33, total_cost=100.0),
            ParsedInvoiceItem(model="B", quantity=1, unit_cost=200.0, total_cost=200.0),
        ]
        # shipping=1.0 → net_adjustment = 1.0
        # subtotal = 300, expected_total = 301
        # A proportion = 100/300 = 1/3, per_unit = (100 + 1/3) / 3 = 33.44
        # B proportion = 200/300 = 2/3, per_unit = (200 + 2/3) / 1 = 200.67
        # actual_total = 33.44*3 + 200.67 = 100.32 + 200.67 = 300.99
        # remainder = 301 - 300.99 = 0.01
        # Last item adjusted: 200.67 + 0.01 = 200.68
        costs = allocate_costs(items, shipping=1.0, discount=0.0)
        actual_total = sum(c * item.quantity for c, item in zip(costs, items))
        expected_total = 301.0
        assert round(actual_total, 2) == expected_total

    def test_different_quantities(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=1, unit_cost=1000.0, total_cost=1000.0),
            ParsedInvoiceItem(model="B", quantity=5, unit_cost=200.0, total_cost=1000.0),
        ]
        costs = allocate_costs(items, shipping=100.0, discount=0.0)
        # Each proportion = 0.5
        # A: (1000 + 50) / 1 = 1050.0
        # B: (1000 + 50) / 5 = 210.0
        assert costs[0] == 1050.0
        assert costs[1] == 210.0

    def test_zero_subtotal_raises(self) -> None:
        items = [
            ParsedInvoiceItem(model="A", quantity=1, unit_cost=0.0, total_cost=0.0),
        ]
        with pytest.raises(ValueError, match="subtotal is zero"):
            allocate_costs(items, shipping=10.0, discount=0.0)


# =========================================================================
# match_to_catalog
# =========================================================================


class TestMatchToCatalog:
    def _catalog(self) -> list[dict]:
        return [
            {"id": 1, "model_name": "Trek Verve 3", "color": "Blue", "size": "Medium"},
            {"id": 2, "model_name": "Trek Verve 3", "color": "Red", "size": "Large"},
            {"id": 3, "model_name": "Specialized Turbo", "color": "Black", "size": "Small"},
        ]

    def test_exact_match(self) -> None:
        item = ParsedInvoiceItem(
            model="Trek Verve 3", color="Blue", size="Medium",
            quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, self._catalog()) == 1

    def test_case_insensitive(self) -> None:
        item = ParsedInvoiceItem(
            model="trek verve 3", color="blue", size="medium",
            quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, self._catalog()) == 1

    def test_partial_model_name(self) -> None:
        item = ParsedInvoiceItem(
            model="Verve 3", quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        # "verve 3" is a substring of "trek verve 3" → score 3
        result = match_to_catalog(item, self._catalog())
        assert result in (1, 2)  # Both Trek Verve 3 products match

    def test_no_match(self) -> None:
        item = ParsedInvoiceItem(
            model="Giant Defy", quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, self._catalog()) is None

    def test_best_match_wins(self) -> None:
        item = ParsedInvoiceItem(
            model="Trek Verve 3", color="Red", size="Large",
            quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        # Product 2 matches model (5) + color (2) + size (2) = 9
        # Product 1 matches model (5) only = 5
        assert match_to_catalog(item, self._catalog()) == 2

    def test_empty_catalog(self) -> None:
        item = ParsedInvoiceItem(
            model="Trek Verve 3", quantity=1, unit_cost=800.0, total_cost=800.0,
        )
        assert match_to_catalog(item, []) is None


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
