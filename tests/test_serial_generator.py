"""Tests for services.serial_generator."""

from __future__ import annotations

import sqlite3

import pytest

from services.serial_generator import (
    _format_serial,
    generate_serial_numbers,
    peek_next_serial,
    peek_next_serials,
)


class _NoCloseConnection:
    """Wrapper around a sqlite3.Connection that ignores .close() calls.

    This prevents the serial_generator's finally-block from closing
    the shared in-memory test fixture.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        object.__setattr__(self, "_conn", conn)

    def close(self) -> None:  # noqa: D102
        pass  # intentionally do nothing

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._conn, name, value)


@pytest.fixture
def _patch_db(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace get_db in serial_generator with a no-close wrapper around db."""
    wrapper = _NoCloseConnection(db)
    monkeypatch.setattr("services.serial_generator.get_db", lambda _path: wrapper)


# =========================================================================
# _format_serial
# =========================================================================


class TestFormatSerial:
    def test_default_prefix(self) -> None:
        assert _format_serial("BIKE", 1) == "BIKE-00001"

    def test_custom_prefix(self) -> None:
        assert _format_serial("EB", 42) == "EB-00042"

    def test_large_number(self) -> None:
        assert _format_serial("BIKE", 123456) == "BIKE-123456"

    def test_zero_padding(self) -> None:
        assert _format_serial("BIKE", 0) == "BIKE-00000"
        assert _format_serial("BIKE", 99999) == "BIKE-99999"


# =========================================================================
# generate_serial_numbers
# =========================================================================


@pytest.mark.usefixtures("_patch_db")
class TestGenerateSerialNumbers:
    def test_single(self, db: sqlite3.Connection) -> None:
        result = generate_serial_numbers(1)
        assert result == ["BIKE-00001"]

    def test_multiple(self, db: sqlite3.Connection) -> None:
        result = generate_serial_numbers(3)
        assert result == ["BIKE-00001", "BIKE-00002", "BIKE-00003"]

    def test_sequential_non_overlapping(self, db: sqlite3.Connection) -> None:
        batch1 = generate_serial_numbers(2)
        batch2 = generate_serial_numbers(3)
        assert batch1 == ["BIKE-00001", "BIKE-00002"]
        assert batch2 == ["BIKE-00003", "BIKE-00004", "BIKE-00005"]

    def test_counter_advances(self, db: sqlite3.Connection) -> None:
        generate_serial_numbers(5)
        from database.models import get_next_serial

        assert get_next_serial(db) == 6

    def test_invalid_count_raises(self) -> None:
        with pytest.raises(ValueError, match="count must be at least 1"):
            generate_serial_numbers(0)
        with pytest.raises(ValueError, match="count must be at least 1"):
            generate_serial_numbers(-1)


# =========================================================================
# peek_next_serial
# =========================================================================


@pytest.mark.usefixtures("_patch_db")
class TestPeekNextSerial:
    def test_format(self, db: sqlite3.Connection) -> None:
        assert peek_next_serial() == "BIKE-00001"

    def test_does_not_increment(self, db: sqlite3.Connection) -> None:
        first = peek_next_serial()
        second = peek_next_serial()
        assert first == second == "BIKE-00001"

    def test_reflects_prior_generation(self, db: sqlite3.Connection) -> None:
        generate_serial_numbers(3)
        assert peek_next_serial() == "BIKE-00004"


# =========================================================================
# peek_next_serials
# =========================================================================


@pytest.mark.usefixtures("_patch_db")
class TestPeekNextSerials:
    def test_multiple_preview(self, db: sqlite3.Connection) -> None:
        result = peek_next_serials(3)
        assert result == ["BIKE-00001", "BIKE-00002", "BIKE-00003"]

    def test_does_not_increment(self, db: sqlite3.Connection) -> None:
        peek_next_serials(5)
        from database.models import get_next_serial

        assert get_next_serial(db) == 1

    def test_invalid_count_raises(self) -> None:
        with pytest.raises(ValueError, match="count must be at least 1"):
            peek_next_serials(0)
        with pytest.raises(ValueError, match="count must be at least 1"):
            peek_next_serials(-1)
