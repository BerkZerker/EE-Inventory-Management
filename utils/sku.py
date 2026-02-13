"""SKU generation utility."""

from __future__ import annotations

import re


def generate_sku(brand: str, model: str, color: str = "", size: str = "") -> str:
    """Generate a SKU from product attributes.

    Format: BRAND-MODEL-COLOR-SIZE (empty parts omitted).
    """
    parts = [brand, model, color, size]
    sku = "-".join(p for p in parts if p).upper().replace(" ", "-")
    return re.sub(r"[^A-Z0-9]+", "-", sku).strip("-")
