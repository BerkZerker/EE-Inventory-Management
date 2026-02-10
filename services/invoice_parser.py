"""Invoice PDF parsing via Google Gemini.

Uses the google-genai SDK to upload PDFs directly to Gemini and extract
structured invoice data with Pydantic schemas.  Includes cost allocation
and fuzzy SKU matching.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ParsedInvoiceItem(BaseModel):
    """A single line item extracted from an invoice."""

    model: str
    color: str | None = None
    size: str | None = None
    quantity: int
    unit_cost: float
    total_cost: float


class ParsedInvoice(BaseModel):
    """Structured data extracted from an invoice PDF."""

    supplier: str
    invoice_number: str
    invoice_date: str  # YYYY-MM-DD
    items: list[ParsedInvoiceItem]
    shipping_cost: float = 0.0
    discount: float = 0.0
    total: float = 0.0


class ParseError(Exception):
    """Raised when invoice parsing fails after all retries."""


# ---------------------------------------------------------------------------
# Gemini parsing
# ---------------------------------------------------------------------------

_PARSE_PROMPT = (
    "Extract all invoice data from this PDF. "
    "Return the supplier name, invoice number, invoice date (YYYY-MM-DD format), "
    "each line item with model name, color, size, quantity, unit cost, and total cost, "
    "plus shipping cost, discount, and invoice total."
)


def parse_invoice_pdf(pdf_path: str | Path) -> ParsedInvoice:
    """Parse an invoice PDF using Gemini and return structured data.

    Raises:
        FileNotFoundError: If pdf_path does not exist.
        ValueError: If the file is not a PDF.
        ParseError: If Gemini returns no parsed data.
    """
    path = Path(pdf_path)
    if not path.exists():
        msg = f"File not found: {path}"
        raise FileNotFoundError(msg)
    if path.suffix.lower() != ".pdf":
        msg = f"Expected a .pdf file, got: {path.suffix}"
        raise ValueError(msg)

    client = genai.Client(api_key=settings.google_api_key)
    uploaded = client.files.upload(file=path)

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[uploaded, _PARSE_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedInvoice,
        ),
    )

    if response.parsed is None:
        msg = "Gemini returned no parsed data"
        raise ParseError(msg)

    return response.parsed  # type: ignore[return-value]


def parse_invoice_with_retry(
    pdf_path: str | Path,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> ParsedInvoice:
    """Parse an invoice PDF with exponential backoff on failure.

    Raises ParseError wrapping the original exception after all retries.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return parse_invoice_pdf(pdf_path)
        except ParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Invoice parse attempt %d failed (%s), retrying in %.1fs",
                    attempt + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)

    msg = f"Invoice parsing failed after {max_retries} retries"
    raise ParseError(msg) from last_exc


# ---------------------------------------------------------------------------
# Cost allocation
# ---------------------------------------------------------------------------


def allocate_costs(
    items: list[ParsedInvoiceItem],
    shipping: float,
    discount: float,
) -> list[float]:
    """Return per-unit allocated cost for each item.

    Distributes shipping and discount proportionally across items based on
    their total_cost relative to the subtotal.  The last item absorbs any
    rounding remainder so the total is penny-accurate.

    Raises ValueError if subtotal is zero.
    """
    subtotal = sum(item.total_cost for item in items)
    if subtotal == 0:
        msg = "Cannot allocate costs: subtotal is zero"
        raise ValueError(msg)

    net_adjustment = shipping - discount
    expected_total = subtotal + net_adjustment

    per_unit_costs: list[float] = []
    for item in items:
        proportion = item.total_cost / subtotal
        per_unit = (item.total_cost + proportion * net_adjustment) / item.quantity
        per_unit_costs.append(round(per_unit, 2))

    # Penny-accurate adjustment: fix rounding on last item
    actual_total = sum(
        cost * item.quantity for cost, item in zip(per_unit_costs, items)
    )
    remainder = round(expected_total - actual_total, 2)
    if remainder != 0 and items:
        last_item = items[-1]
        per_unit_costs[-1] = round(
            per_unit_costs[-1] + remainder / last_item.quantity, 2
        )

    return per_unit_costs


# ---------------------------------------------------------------------------
# Fuzzy catalog matching
# ---------------------------------------------------------------------------

_MODEL_MATCH_THRESHOLD = 3


def match_to_catalog(
    item: ParsedInvoiceItem,
    catalog: list[dict],
) -> int | None:
    """Score each catalog product against the parsed item and return best match.

    Scoring:
      - Model name exact match (case-insensitive): +5
      - Model name substring match (case-insensitive): +3  (required minimum)
      - Color match (case-insensitive): +2
      - Size match (case-insensitive): +2

    Returns the product id of the highest-scoring match, or None if no match
    reaches the threshold (3).
    """
    best_id: int | None = None
    best_score = 0

    item_model = item.model.lower()
    item_color = (item.color or "").lower()
    item_size = (item.size or "").lower()

    for product in catalog:
        score = 0
        product_model = (product.get("model_name") or "").lower()

        if not product_model:
            continue

        # Model matching — exact or substring
        if item_model == product_model:
            score += 5
        elif item_model in product_model or product_model in item_model:
            score += 3
        else:
            # No model match at all — skip this product
            continue

        # Color match
        product_color = (product.get("color") or "").lower()
        if item_color and product_color and item_color == product_color:
            score += 2

        # Size match
        product_size = (product.get("size") or "").lower()
        if item_size and product_size and item_size == product_size:
            score += 2

        if score > best_score:
            best_score = score
            best_id = product["id"]

    if best_score >= _MODEL_MATCH_THRESHOLD:
        return best_id
    return None
