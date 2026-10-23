"""Domain errors shared by the service layer and UI."""

from __future__ import annotations


class StockKeepError(Exception):
    """Base class for expected, user-presentable errors."""


class ValidationError(StockKeepError):
    """A field or payload failed validation."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


class NotFoundError(StockKeepError):
    """A requested record does not exist."""


class ConflictError(StockKeepError):
    """The operation conflicts with current data (e.g. insufficient stock)."""


class PermissionError_(StockKeepError):
    """The operation requires a privileged confirmation."""


class PermissionDenied(StockKeepError):
    """The signed-in role is not allowed to perform the action."""


class ImportError_(StockKeepError):
    """A file could not be parsed or imported."""
