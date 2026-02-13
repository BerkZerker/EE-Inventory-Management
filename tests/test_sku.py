"""Tests for utils.sku."""

from __future__ import annotations

from utils.sku import generate_sku


class TestGenerateSku:
    def test_basic(self) -> None:
        assert generate_sku("Trek", "Verve 3", "Blue", "Medium") == "TREK-VERVE-3-BLUE-MEDIUM"

    def test_empty_color_and_size(self) -> None:
        assert generate_sku("Trek", "Verve 3") == "TREK-VERVE-3"

    def test_empty_size_only(self) -> None:
        assert generate_sku("Trek", "Verve 3", "Red") == "TREK-VERVE-3-RED"

    def test_special_characters(self) -> None:
        assert generate_sku("Giant", "Escape 3 (Disc)", "Black/White", "L") == "GIANT-ESCAPE-3-DISC-BLACK-WHITE-L"

    def test_whitespace_handling(self) -> None:
        assert generate_sku("Santa Cruz", "Hightower LT", "Matte Black", "XL") == "SANTA-CRUZ-HIGHTOWER-LT-MATTE-BLACK-XL"

    def test_empty_brand_and_model(self) -> None:
        assert generate_sku("", "") == ""

    def test_empty_parts_omitted(self) -> None:
        assert generate_sku("Trek", "Verve", "", "Large") == "TREK-VERVE-LARGE"
