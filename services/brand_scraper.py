"""Brand website scraper for extracting product catalogs.

Supports two strategies:
1. Shopify JSON — fast, structured, no browser needed
2. Playwright + Gemini — headless browser render + AI extraction fallback
"""

from __future__ import annotations

import logging
import time

import requests as http_requests
from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ScrapedProduct(BaseModel):
    """A single product variant scraped from a brand website."""

    brand: str
    model: str
    color: str | None = None
    size: str | None = None
    retail_price: float


class ScrapeResult(BaseModel):
    """Wraps scrape results with metadata."""

    brand_name: str
    source_url: str
    strategy: str
    products: list[ScrapedProduct]
    errors: list[str] = []


class ScrapeError(Exception):
    """Raised when brand scraping fails after all retries."""


# ---------------------------------------------------------------------------
# Shopify JSON strategy
# ---------------------------------------------------------------------------

# Option names that map to Color or Size
_COLOR_NAMES = {"color", "colour", "colorway"}
_SIZE_NAMES = {"size", "frame size", "frame_size"}

# Product types (from Shopify product_type field) that indicate a bike.
# Checked with substring matching so "Electric Bikes" matches "bike".
_BIKE_TYPE_KEYWORDS = {"bike", "bicycle", "ebike", "e-bike", "scooter", "moped"}

# Minimum variant price (USD) to consider a product as a potential bike.
# Virtually all bikes/e-bikes retail above this; accessories rarely do.
_MIN_BIKE_PRICE = 200.0


def _max_variant_price(product: dict) -> float:
    """Return the highest variant price for a Shopify product."""
    best = 0.0
    for variant in product.get("variants", []):
        try:
            best = max(best, float(variant.get("price", "0")))
        except (TypeError, ValueError):
            pass
    return best


def _is_bike_product(product: dict) -> bool:
    """Return True if a Shopify product looks like a bicycle/e-bike.

    Strategy (allowlist-first, not blocklist):
      1. If product_type contains a bike keyword → include.
      2. If product_type is set but has NO bike keyword → exclude.
         (Stores that categorise products label accessories as "Accessories",
          "Parts", "Apparel", etc. — anything that isn't a bike type is not a bike.)
      3. If product_type is empty (store doesn't categorise), fall back to:
         a. Price ≥ $200 (bikes are expensive, accessories aren't)
         b. Tags contain a bike keyword
         Both must pass for inclusion.
    """
    product_type = (product.get("product_type") or "").strip().lower()
    tags_raw = product.get("tags")
    tags = tags_raw.lower() if isinstance(tags_raw, str) else ""

    # --- product_type is set ---
    if product_type:
        return any(kw in product_type for kw in _BIKE_TYPE_KEYWORDS)

    # --- product_type is empty — use heuristics ---
    price = _max_variant_price(product)
    if price < _MIN_BIKE_PRICE:
        return False

    # If tags exist, require a bike-related tag
    if tags:
        return any(kw in tags for kw in _BIKE_TYPE_KEYWORDS)

    # No type, no tags, but price is high enough — include
    # (some stores have zero metadata; price is the best signal we have)
    return True


# Recognized size labels → canonical form.
# Checked longest-first so "Extra Small" matches before "Small".
_KNOWN_SIZES: list[tuple[str, str]] = [
    # Multi-word first (matched before single-word substrings)
    ("extra small", "Extra Small"),
    ("x-small", "Extra Small"),
    ("extra large", "Extra Large"),
    ("x-large", "Extra Large"),
    ("xx-large", "XXL"),
    ("xxx-large", "XXXL"),
    ("step-thru", "Step-Thru"),
    ("step-through", "Step-Thru"),
    ("step thru", "Step-Thru"),
    ("step through", "Step-Thru"),
    ("low-step", "Low-Step"),
    ("low step", "Low-Step"),
    ("high-step", "High-Step"),
    ("high step", "High-Step"),
    # Standard letter sizes
    ("xxxl", "XXXL"),
    ("xxl", "XXL"),
    ("xl", "XL"),
    ("xs", "XS"),
    ("small", "Small"),
    ("medium", "Medium"),
    ("large", "Large"),
    # Single letters last (avoid matching the "s" in "one size" etc.)
    ("s", "S"),
    ("m", "M"),
    ("l", "L"),
]


def _clean_size(raw: str) -> str:
    """Return a canonical size label if one is found in *raw*, else ''.

    Uses an allowlist approach: only returns a value when the raw string
    contains a recognized size keyword.  Everything else (numbers, height
    ranges, 'One Size', 'Regular', 'Default Title', …) yields ''.
    """
    import re

    s = raw.strip()
    if not s:
        return ""

    # Strip quotes and parenthesized content so we match the core text
    s = s.strip("\"' \t")
    s = re.sub(r"\s*\(.*?\)", "", s).strip()

    lower = s.lower()

    # Try to find a known size label in the cleaned string.
    # We match on word boundaries to avoid false positives
    # (e.g. the "s" in "uesta").
    for keyword, canonical in _KNOWN_SIZES:
        pattern = r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])"
        if re.search(pattern, lower):
            return canonical

    return ""


# Words/phrases to strip from the end of a product title
_TITLE_STRIP_SUFFIXES = [
    "electric bicycle", "electric bike", "e-bicycle", "e-bike",
    "ebicycle", "ebike", "bicycle", "bike",
]


def _clean_model_name(title: str, brand_name: str) -> str:
    """Extract a clean model name from a Shopify product title.

    Strips the brand name prefix and common trailing descriptors
    like 'ebike', 'e-bike', 'electric bike', etc.
    """
    import re

    model = title.strip()

    # Strip brand name prefix (case-insensitive, word-boundary aware)
    brand_lower = brand_name.lower()
    if model.lower().startswith(brand_lower):
        after = model[len(brand_name):]
        # Only strip if brand is followed by a word boundary (space, dash, etc.)
        if not after or not after[0].isalpha():
            model = after.strip()
            # Also strip a leading dash/pipe separator if present
            model = re.sub(r"^[\s\-|/]+", "", model)

    # Strip trailing suffixes (longest first to match "electric bike" before "bike")
    lower = model.lower().rstrip()
    for suffix in _TITLE_STRIP_SUFFIXES:
        if lower.endswith(suffix):
            model = model[: len(model) - len(suffix)].rstrip(" -|/")
            break

    return model.strip()


def _scrape_shopify_json(url: str, brand_name: str) -> ScrapeResult | None:
    """Scrape products from a Shopify store's /products.json endpoint.

    Returns None if the endpoint is unavailable (404 or non-JSON).
    """
    base = url.rstrip("/")
    all_products: list[ScrapedProduct] = []
    page = 1

    while True:
        try:
            resp = http_requests.get(
                f"{base}/products.json",
                params={"limit": 250, "page": page},
                timeout=30,
            )
        except http_requests.RequestException:
            return None

        if resp.status_code == 404:
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        products = data.get("products", [])
        if not products:
            break

        for product in products:
            raw_title = product.get("title", "").strip()
            if not raw_title:
                continue
            model = _clean_model_name(raw_title, brand_name)
            if not model:
                continue

            if not _is_bike_product(product):
                continue

            # Build option name → position mapping
            options = product.get("options", [])
            color_pos: int | None = None
            size_pos: int | None = None

            for opt in options:
                name = (opt.get("name") or "").strip().lower()
                pos = opt.get("position", 0)
                values = opt.get("values", [])
                if name in _COLOR_NAMES:
                    color_pos = pos
                elif name in _SIZE_NAMES:
                    # Only treat as a real size option if there are
                    # multiple values — a single value like "One Size"
                    # means the product doesn't come in sizes
                    if len(values) > 1:
                        size_pos = pos

            for variant in product.get("variants", []):
                price_str = variant.get("price", "0")
                try:
                    price = float(price_str)
                except (TypeError, ValueError):
                    price = 0.0

                color = None
                size = None
                if color_pos is not None:
                    color = variant.get(f"option{color_pos}") or None
                if size_pos is not None:
                    raw_size = variant.get(f"option{size_pos}") or ""
                    size = _clean_size(raw_size) or None

                all_products.append(
                    ScrapedProduct(
                        brand=brand_name,
                        model=model,
                        color=color,
                        size=size,
                        retail_price=price,
                    )
                )

        page += 1

    if not all_products:
        return None

    deduped = _deduplicate_products(all_products)

    return ScrapeResult(
        brand_name=brand_name,
        source_url=base,
        strategy="shopify json",
        products=deduped,
    )


# ---------------------------------------------------------------------------
# Playwright + Gemini strategy
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = (
    "Extract all bicycle / e-bike products from this webpage HTML.\n"
    "For each product variant, return:\n"
    "- brand: use '{brand}' as the brand name\n"
    "- model: the model/product name\n"
    "- color: the color if listed, null otherwise\n"
    "- size: the frame size if listed, null otherwise\n"
    "- retail_price: the retail price as a number\n\n"
    "ONLY include bicycles and e-bikes. IGNORE accessories, parts, apparel, "
    "and non-bike products.\n"
    "Return one entry per variant (each color/size combo is a separate entry)."
)


def _fetch_rendered_html(url: str) -> str:
    """Render a page with Playwright headless Chromium and return HTML."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        # Scroll to bottom to trigger lazy-loaded content
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        html = page.content()
        browser.close()

    return html


def _extract_with_gemini(html: str, brand_name: str) -> list[ScrapedProduct]:
    """Use Gemini to extract structured product data from HTML."""
    client = genai.Client(api_key=settings.google_api_key)
    prompt = _EXTRACT_PROMPT.replace("{brand}", brand_name)

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[html, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[ScrapedProduct],
        ),
    )

    if response.parsed is None:
        return []

    return response.parsed  # type: ignore[return-value]


def _scrape_playwright_gemini(url: str, brand_name: str) -> ScrapeResult:
    """Scrape products using headless browser + Gemini AI extraction."""
    html = _fetch_rendered_html(url)
    products = _extract_with_gemini(html, brand_name)
    deduped = _deduplicate_products(products)

    return ScrapeResult(
        brand_name=brand_name,
        source_url=url,
        strategy="playwright gemini",
        products=deduped,
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_products(
    products: list[ScrapedProduct],
) -> list[ScrapedProduct]:
    """Deduplicate products by lowercase (brand, model, color, size) tuple."""
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ScrapedProduct] = []

    for p in products:
        key = (
            p.brand.lower(),
            p.model.lower(),
            (p.color or "").lower(),
            (p.size or "").lower(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def scrape_brand(url: str, brand_name: str) -> ScrapeResult:
    """Scrape a brand website for products.

    Tries Shopify JSON first, then falls back to Playwright + Gemini.

    Raises ScrapeError if both strategies fail.
    """
    # Try Shopify JSON first
    result = _scrape_shopify_json(url, brand_name)
    if result is not None:
        return result

    # Fall back to Playwright + Gemini
    return _scrape_playwright_gemini(url, brand_name)


def scrape_brand_with_retry(
    url: str,
    brand_name: str,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> ScrapeResult:
    """Scrape a brand website with exponential backoff on failure.

    Raises ScrapeError wrapping the original exception after all retries.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return scrape_brand(url, brand_name)
        except ScrapeError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Brand scrape attempt %d failed (%s), retrying in %.1fs",
                    attempt + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)

    msg = f"Brand scraping failed after {max_retries} retries"
    raise ScrapeError(msg) from last_exc
