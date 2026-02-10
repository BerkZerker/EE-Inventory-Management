"""Database package — connection helpers and schema management."""

from database.connection import get_db, init_database

__all__ = ["get_db", "init_database"]
