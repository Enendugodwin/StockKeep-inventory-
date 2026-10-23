"""Tabular export helpers: safe CSV cells and atomic file writes."""

from __future__ import annotations

import csv
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from .errors import ValidationError

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitise_cell(value, *, escape_formula: bool = True):
    """Neutralise CSV/Excel formula injection in user-controlled text."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}" if value.as_tuple().exponent < 0 else str(value)
    if not isinstance(value, str):
        return value
    if not escape_formula:
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_text(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def atomic_path(target: Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-", suffix=target.suffix + ".tmp", dir=target.parent, delete=False
    )
    handle.close()
    return Path(handle.name)


def replace_atomically(temp: Path, target: Path) -> None:
    os.replace(temp, target)


def write_csv(path: Path | str, headers: list[str], rows: list[list], *, delimiter: str = ",") -> Path:
    target = Path(path)
    if target.suffix.lower() != ".csv":
        target = target.with_suffix(".csv")
    temp = atomic_path(target)
    try:
        with open(temp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([safe_text(h) for h in headers])
            for row in rows:
                writer.writerow([sanitise_cell(value) for value in row])
        replace_atomically(temp, target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return target


def ensure_extension(path: str | Path, extension: str) -> Path:
    target = Path(path)
    if target.suffix.lower() != extension.lower():
        target = target.with_suffix(extension)
    return target


def parse_import_extension(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValidationError(
            "Unsupported file type. Choose a .csv or .xlsx file.",
            "file",
        )
    return suffix
