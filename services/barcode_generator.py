"""Barcode label generation.

Generates Code128 barcode images via python-barcode and assembles
printable PDF label sheets (Avery 5160) and single thermal labels
using reportlab.
"""

from __future__ import annotations

import logging
import sqlite3
from io import BytesIO
from pathlib import Path

import barcode
from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from config import settings
from database.connection import get_db
import database.models as models

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Avery 5160 layout constants
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = LETTER  # 612 x 792 points
LABEL_W = 2.625 * inch  # 189 points
LABEL_H = 1.0 * inch  # 72 points
MARGIN_TOP = 0.5 * inch  # 36 points
MARGIN_LEFT = 0.1875 * inch  # 13.5 points
GAP_H = 0.125 * inch  # 9 points
GAP_V = 0  # labels touch vertically
COLS = 3
ROWS = 10
LABELS_PER_PAGE = COLS * ROWS


# ---------------------------------------------------------------------------
# Barcode image generation
# ---------------------------------------------------------------------------


def generate_barcode_image(serial: str) -> bytes:
    """Generate a Code128 barcode as PNG bytes for the given serial number."""
    code128 = barcode.get("code128", serial, writer=ImageWriter())
    buffer = BytesIO()
    code128.write(buffer, options={
        "module_width": 0.3,
        "module_height": 8.0,
        "text_distance": 3.0,
        "font_size": 8,
        "quiet_zone": 2.0,
    })
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Label sheet (Avery 5160)
# ---------------------------------------------------------------------------


def create_label_sheet(
    serials: list[str],
    output_path: str,
    product_info: dict | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Create an Avery 5160 label sheet PDF with barcodes for each serial.

    If *product_info* is ``None`` the function opens a database connection
    and looks up the product associated with each serial number so that
    the model name and colour can be printed on the label.  When
    *product_info* is supplied it is used for every serial (useful for
    batch prints of a single product).

    Returns the *output_path* string.
    """
    # Build a per-serial product info cache
    products_cache: dict[str, dict] = {}
    if product_info is None:
        owns_conn = conn is None
        if owns_conn:
            conn = get_db(settings.database_path)
        try:
            for serial in serials:
                bike = models.get_bike_by_serial(conn, serial)
                if bike:
                    product = models.get_product(conn, bike["product_id"])
                    if product:
                        products_cache[serial] = product
        finally:
            if owns_conn:
                conn.close()
    else:
        for serial in serials:
            products_cache[serial] = product_info

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    c = Canvas(output_path, pagesize=LETTER)

    for idx, serial in enumerate(serials):
        # Start a new page every LABELS_PER_PAGE labels
        page_idx = idx % LABELS_PER_PAGE
        if idx > 0 and page_idx == 0:
            c.showPage()

        col = page_idx % COLS
        row = page_idx // COLS

        x = MARGIN_LEFT + col * (LABEL_W + GAP_H)
        y = PAGE_H - MARGIN_TOP - (row + 1) * (LABEL_H + GAP_V)

        # Serial number text at top of label
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(x + LABEL_W / 2, y + LABEL_H - 12, serial)

        # Barcode image in the middle
        img_bytes = generate_barcode_image(serial)
        img = ImageReader(BytesIO(img_bytes))
        barcode_w = LABEL_W - 20
        barcode_h = LABEL_H - 30
        c.drawImage(
            img,
            x + 10,
            y + 10,
            width=barcode_w,
            height=barcode_h,
            preserveAspectRatio=True,
            anchor="c",
        )

        # Product info below barcode (if available)
        info = products_cache.get(serial)
        if info:
            label_text = f"{info.get('brand', '')} {info.get('model', '')}".strip()
            if info.get("color"):
                label_text += f" - {info['color']}"
            c.setFont("Helvetica", 5)
            c.drawCentredString(x + LABEL_W / 2, y + 3, label_text)

    c.save()
    logger.info("Label sheet saved to %s (%d labels)", output_path, len(serials))
    return output_path


# ---------------------------------------------------------------------------
# Single thermal label
# ---------------------------------------------------------------------------


def create_single_label(
    serial: str,
    product_info: dict | None = None,
) -> bytes:
    """Create a single thermal-printer label (2" x 1") as PDF bytes.

    Returns the raw PDF content as *bytes*.
    """
    buffer = BytesIO()
    width = 2 * inch
    height = 1 * inch
    c = Canvas(buffer, pagesize=(width, height))

    # Serial number at top
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(width / 2, height - 12, serial)

    # Barcode in the middle
    img_bytes = generate_barcode_image(serial)
    img = ImageReader(BytesIO(img_bytes))
    c.drawImage(
        img,
        5,
        12,
        width=width - 10,
        height=height - 30,
        preserveAspectRatio=True,
        anchor="c",
    )

    # Product info at bottom
    if product_info:
        label_text = f"{product_info.get('brand', '')} {product_info.get('model', '')}".strip()
        if product_info.get("color"):
            label_text += f" - {product_info['color']}"
        c.setFont("Helvetica", 6)
        c.drawCentredString(width / 2, 3, label_text)

    c.save()
    return buffer.getvalue()
