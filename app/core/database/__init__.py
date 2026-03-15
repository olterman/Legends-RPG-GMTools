"""Core database package."""

from .bootstrap import CURRENT_SCHEMA_VERSION, DatabaseManager, ensure_database

__all__ = ["CURRENT_SCHEMA_VERSION", "DatabaseManager", "ensure_database"]
