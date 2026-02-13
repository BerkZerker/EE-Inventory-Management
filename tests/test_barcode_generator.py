"""Tests for services.barcode_generator."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services.barcode_generator import (
    create_label_sheet,
    create_single_label,
    generate_barcode_image,
)
from tests.conftest import _NoCloseConnection

# ---------------------------------------------------------------------------
# Shared product_info fixture
# ---------------------------------------------------------------------------

SAMPLE_PRODUCT_INFO: dict = {
    "brand": "Trek",
    "model": "Verve 3",
    "color": "Blue",
    "sku": "TREK-VERVE-3-BLU-M",
}


# =========================================================================
# TestGenerateBarcodeImage
# =========================================================================


class TestGenerateBarcodeImage:
    def test_returns_png_bytes(self) -> None:
        result = generate_barcode_image("BIKE-00001")
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PNG magic bytes
        assert result[:4] == b"\x89PNG"

    def test_different_serials_different_images(self) -> None:
        img1 = generate_barcode_image("BIKE-00001")
        img2 = generate_barcode_image("BIKE-00002")
        assert img1 != img2


# =========================================================================
# TestCreateLabelSheet
# =========================================================================


class TestCreateLabelSheet:
    def test_creates_pdf_file(self, tmp_path: Path) -> None:
        output = str(tmp_path / "labels.pdf")
        serials = ["BIKE-00001", "BIKE-00002", "BIKE-00003"]
        result = create_label_sheet(serials, output, product_info=SAMPLE_PRODUCT_INFO)
        assert result == output
        pdf_path = Path(output)
        assert pdf_path.exists()
        content = pdf_path.read_bytes()
        assert content[:5] == b"%PDF-"

    def test_multi_page(self, tmp_path: Path) -> None:
        output = str(tmp_path / "multi.pdf")
        # 35 serials => 30 on page 1, 5 on page 2
        serials = [f"BIKE-{i:05d}" for i in range(1, 36)]
        create_label_sheet(serials, output, product_info=SAMPLE_PRODUCT_INFO)
        pdf_path = Path(output)
        assert pdf_path.exists()
        content = pdf_path.read_bytes()
        assert content[:5] == b"%PDF-"
        # A two-page PDF should be larger than a single-page PDF
        single_output = str(tmp_path / "single.pdf")
        create_label_sheet(["BIKE-00001"], single_output, product_info=SAMPLE_PRODUCT_INFO)
        single_size = Path(single_output).stat().st_size
        multi_size = pdf_path.stat().st_size
        assert multi_size > single_size

    def test_with_product_info(self, tmp_path: Path) -> None:
        output = str(tmp_path / "with_info.pdf")
        serials = ["BIKE-00001"]
        create_label_sheet(serials, output, product_info=SAMPLE_PRODUCT_INFO)
        assert Path(output).exists()
        content = Path(output).read_bytes()
        assert content[:5] == b"%PDF-"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        output = str(tmp_path / "nested" / "deep" / "labels.pdf")
        serials = ["BIKE-00001"]
        create_label_sheet(serials, output, product_info=SAMPLE_PRODUCT_INFO)
        assert Path(output).exists()

    def test_db_lookup_when_no_product_info(
        self,
        tmp_path: Path,
        db: sqlite3.Connection,
        sample_bike: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When product_info is None, the function should look up products from the DB."""
        wrapper = _NoCloseConnection(db)
        monkeypatch.setattr(
            "services.barcode_generator.get_db", lambda _path: wrapper
        )
        output = str(tmp_path / "db_lookup.pdf")
        serial = sample_bike["serial_number"]
        result = create_label_sheet([serial], output)
        assert result == output
        assert Path(output).exists()
        content = Path(output).read_bytes()
        assert content[:5] == b"%PDF-"

    def test_without_product_info_no_db_match(
        self,
        tmp_path: Path,
        db: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Labels are still created even when serials are not in the DB."""
        wrapper = _NoCloseConnection(db)
        monkeypatch.setattr(
            "services.barcode_generator.get_db", lambda _path: wrapper
        )
        output = str(tmp_path / "no_match.pdf")
        create_label_sheet(["UNKNOWN-99999"], output)
        assert Path(output).exists()


# =========================================================================
# TestCreateSingleLabel
# =========================================================================


class TestCreateSingleLabel:
    def test_returns_pdf_bytes(self) -> None:
        result = create_single_label("BIKE-00001")
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:5] == b"%PDF-"

    def test_with_product_info(self) -> None:
        result = create_single_label("BIKE-00001", product_info=SAMPLE_PRODUCT_INFO)
        assert isinstance(result, bytes)
        assert result[:5] == b"%PDF-"

    def test_product_info_without_color(self) -> None:
        info = {"brand": "Trek", "model": "Verve 3"}
        result = create_single_label("BIKE-00001", product_info=info)
        assert isinstance(result, bytes)
        assert result[:5] == b"%PDF-"
