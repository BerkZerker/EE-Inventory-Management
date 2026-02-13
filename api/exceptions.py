"""Custom exception classes for structured API error handling."""

from __future__ import annotations


class AppError(Exception):
    """Base application error with an associated HTTP status code."""

    status_code: int = 500

    def __init__(self, message: str = "Internal server error") -> None:
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404


class ValidationError(AppError):
    status_code = 400


class ConflictError(AppError):
    status_code = 409


class ShopifySyncError(AppError):
    status_code = 502
