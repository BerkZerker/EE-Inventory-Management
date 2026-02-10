"""API error handling utilities."""

from __future__ import annotations

import functools
import logging
from typing import Any

from flask import jsonify

logger = logging.getLogger(__name__)


def error_response(
    message: str,
    status_code: int,
    details: Any = None,
) -> tuple:
    """Return a consistent JSON error response."""
    body: dict[str, Any] = {"error": message}
    if details is not None:
        body["details"] = details
    return jsonify(body), status_code


def handle_errors(f):
    """Decorator that catches common exceptions and returns JSON errors."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as exc:
            return error_response(str(exc), 400)
        except FileNotFoundError as exc:
            return error_response(str(exc), 404)
        except Exception as exc:
            logger.exception("Unexpected error in %s", f.__name__)
            return error_response("Internal server error", 500)

    return wrapper
