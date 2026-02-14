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

    brand: str | None = None
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
    credit_card_fees: float = 0.0
    tax: float = 0.0
    other_fees: float = 0.0
    total: float = 0.0


class ParseError(Exception):
    """Raised when invoice parsing fails after all retries."""


# ---------------------------------------------------------------------------
# Gemini parsing
# ---------------------------------------------------------------------------

_PARSE_PROMPT = (
    "Extract all invoice data from this PDF.\n"
    "Return the supplier name, invoice number, invoice date (YYYY-MM-DD format).\n\n"
    "For line items, ONLY extract bicycles and e-bikes. "
    "IGNORE all accessories and parts including: fenders, racks, lights, locks, "
    "helmets, bags, pumps, tools, spare parts, kickstands, bells, mirrors, "
    "baskets, panniers, chargers, batteries sold separately, and similar accessories.\n"
    "IGNORE wholesale/dealer price adjustment line items and credit/discount lines.\n\n"
    "For each bike line item extract:\n"
    "- brand: the manufacturer name (e.g., Trek, Specialized, Giant). "
    "Do NOT include the brand in the model name.\n"
    "- model: the model name WITHOUT the brand prefix "
    "(e.g., 'Verve 3' not 'Trek Verve 3')\n"
    "- color: the color if listed (e.g., Blue, Matte Black). Use null if not determinable.\n"
    "- size: the frame size if listed (e.g., S, M, L, 48cm, 52cm, Small, Medium, Large). "
    "Use null if not determinable.\n"
    "- quantity: number of units\n"
    "- unit_cost: cost per unit\n"
    "- total_cost: total cost for this line\n\n"
    "Also extract: shipping cost, discount, credit card fees, tax, "
    "other fees/surcharges, and invoice total."
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
    credit_card_fees: float = 0.0,
    tax: float = 0.0,
    other_fees: float = 0.0,
) -> list[float]:
    """Return per-unit allocated cost for each item.

    Even distribution across all bikes:
      total_extras = shipping + credit_card_fees + tax + other_fees - discount
      extra_per_bike = total_extras / total_bike_count
      allocated_cost_per_bike = unit_cost + extra_per_bike

    The last bike absorbs any rounding remainder so the total is penny-accurate.

    Raises ValueError if total bike count is zero.
    """
    total_bikes = sum(item.quantity for item in items)
    if total_bikes == 0:
        msg = "Cannot allocate costs: total bike count is zero"
        raise ValueError(msg)

    total_extras = shipping + credit_card_fees + tax + other_fees - discount
    extra_per_bike = round(total_extras / total_bikes, 2)

    per_unit_costs: list[float] = []
    for item in items:
        per_unit = round(item.unit_cost + extra_per_bike, 2)
        per_unit_costs.append(per_unit)

    # Penny-accurate adjustment: compute last item's per-unit from the
    # remaining balance so the grand total is exact.
    if len(items) > 0:
        subtotal = sum(item.total_cost for item in items)
        expected_total = subtotal + total_extras
        non_last_total = sum(
            cost * item.quantity
            for cost, item in zip(per_unit_costs[:-1], items[:-1])
        )
        last_item = items[-1]
        last_per_unit = round(
            (expected_total - non_last_total) / last_item.quantity, 2
        )
        per_unit_costs[-1] = last_per_unit

    return per_unit_costs


# ---------------------------------------------------------------------------
# Fuzzy catalog matching
# ---------------------------------------------------------------------------

_MODEL_MATCH_THRESHOLD = 3

# Common abbreviations for normalization
_ABBREVIATIONS: dict[str, str] = {
    "sm": "small",
    "med": "medium",
    "md": "medium",
    "lg": "large",
    "xl": "extra large",
    "xs": "extra small",
    "blu": "blue",
    "blk": "black",
    "wht": "white",
    "grn": "green",
    "red": "red",
    "gry": "gray",
    "grey": "gray",
    "slv": "silver",
    "org": "orange",
    "ylw": "yellow",
    "pur": "purple",
    "pnk": "pink",
    "brn": "brown",
}


def _normalize(text: str) -> str:
    """Normalize text by expanding abbreviations and lowering case."""
    words = text.lower().split()
    return " ".join(_ABBREVIATIONS.get(w, w) for w in words)


def _token_overlap_score(a: str, b: str) -> float:
    """Return the fraction of tokens in common between two strings (0.0-1.0)."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a & tokens_b
    return len(overlap) / max(len(tokens_a), len(tokens_b))


def match_to_catalog(
    item: ParsedInvoiceItem,
    catalog: list[dict],
) -> int | None:
    """Score each catalog product against the parsed item and return best match.

    Scoring:
      - Brand exact match (case-insensitive, normalized): +3
      - Model exact match (case-insensitive, normalized): +5
      - Model substring match (case-insensitive): +3  (required minimum)
      - Model token overlap >= 0.5: +3 (alternative to substring)
      - Color match (case-insensitive, normalized): +2
      - Size match (case-insensitive, normalized): +2

    Returns the product id of the highest-scoring match, or None if no match
    reaches the threshold (3).
    """
    best_id: int | None = None
    best_score = 0

    item_brand = _normalize(item.brand or "")
    item_model = _normalize(item.model)
    item_color = _normalize(item.color or "")
    item_size = _normalize(item.size or "")

    for product in catalog:
        score = 0
        product_model = _normalize(product.get("model") or "")

        if not product_model:
            continue

        # Model matching — exact, substring, or token overlap
        if item_model == product_model:
            score += 5
        elif item_model in product_model or product_model in item_model:
            score += 3
        elif _token_overlap_score(item_model, product_model) >= 0.5:
            score += 3
        else:
            # No model match at all — skip this product
            continue

        # Brand match
        product_brand = _normalize(product.get("brand") or "")
        if item_brand and product_brand and item_brand == product_brand:
            score += 3

        # Color match
        product_color = _normalize(product.get("color") or "")
        if item_color and product_color and item_color == product_color:
            score += 2

        # Size match
        product_size = _normalize(product.get("size") or "")
        if item_size and product_size and item_size == product_size:
            score += 2

        if score > best_score:
            best_score = score
            best_id = product["id"]

    if best_score >= _MODEL_MATCH_THRESHOLD:
        return best_id
    return None
