"""Atomic serial number generation.

Uses BEGIN IMMEDIATE transactions against the serial_counter table
to guarantee unique, gap-free serial numbers even under concurrent access.
"""

from __future__ import annotations

from config import settings
from database.connection import get_db
from database.models import get_next_serial, increment_serial_counter


def _format_serial(prefix: str, number: int) -> str:
    """Format a serial number as PREFIX-NNNNN."""
    return f"{prefix}-{number:05d}"


def generate_serial_numbers(count: int) -> list[str]:
    """Atomically reserve *count* serial numbers and return formatted strings.

    Raises ValueError if count < 1.
    """
    if count < 1:
        msg = "count must be at least 1"
        raise ValueError(msg)

    conn = get_db(settings.database_path)
    try:
        start = increment_serial_counter(conn, count)
        return [
            _format_serial(settings.serial_prefix, start + i)
            for i in range(count)
        ]
    finally:
        conn.close()


def peek_next_serial() -> str:
    """Return the next serial number without incrementing the counter."""
    conn = get_db(settings.database_path)
    try:
        next_val = get_next_serial(conn)
        return _format_serial(settings.serial_prefix, next_val)
    finally:
        conn.close()


def peek_next_serials(count: int) -> list[str]:
    """Preview the next *count* serial numbers without incrementing.

    Raises ValueError if count < 1.
    """
    if count < 1:
        msg = "count must be at least 1"
        raise ValueError(msg)

    conn = get_db(settings.database_path)
    try:
        next_val = get_next_serial(conn)
        return [
            _format_serial(settings.serial_prefix, next_val + i)
            for i in range(count)
        ]
    finally:
        conn.close()
