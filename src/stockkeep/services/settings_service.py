"""Business settings persisted in SQLite (with filesystem path resolution)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ..db import default_settings
from ..errors import ValidationError
from ..models import Setting
from ..money import CURRENCY_SYMBOLS
from ..paths import AppPaths, legacy_home, resolve_dir
from ..timeutil import closing_time, get_timezone


@dataclass
class AppSettings:
    values: dict[str, str] = field(default_factory=dict)
    operator_id: int | None = None
    operator_name: str = "Operator"

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    @property
    def business_name(self) -> str:
        return self.get("business_name", "My Business")

    @property
    def currency_code(self) -> str:
        return self.get("currency_code", "NGN")

    @property
    def currency_symbol(self) -> str:
        return self.get("currency_symbol", "\u20a6")

    @property
    def timezone(self) -> str:
        return self.get("timezone", "Africa/Lagos")

    @property
    def close_time(self) -> str:
        return self.get("daily_close_time", "23:59")

    @property
    def theme(self) -> str:
        return self.get("theme", "light")

    @property
    def page_size(self) -> int:
        try:
            return max(10, min(500, int(self.get("page_size", "50"))))
        except ValueError:
            return 50

    @property
    def backup_enabled(self) -> bool:
        return self.get("backup_enabled", "0") in {"1", "true", "True", "yes"}

    @property
    def backup_retention(self) -> int:
        try:
            return max(1, min(365, int(self.get("backup_retention", "14"))))
        except ValueError:
            return 14

    def report_root(self, paths: AppPaths) -> Path:
        raw = self.get("report_dir") or str(paths.reports_dir)
        return resolve_dir(raw, base=paths.home)

    def backup_root(self, paths: AppPaths) -> Path:
        raw = self.get("backup_dir") or str(paths.backups_dir)
        return resolve_dir(raw, base=paths.home)


def _is_under(path: str | Path, root: Path) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def load_settings(session: Session, paths: AppPaths) -> AppSettings:
    rows = session.query(Setting).all()
    values = default_settings(paths.home)
    for row in rows:
        if row.value is not None:
            values[row.key] = row.value

    # 1.0 stored absolute report/backup folders under AppData.  Rewrite them to
    # the portable app folder so no new files are written outside it.
    legacy = legacy_home()
    if legacy is not None:
        portable = {
            "report_dir": paths.reports_dir,
            "backup_dir": paths.backups_dir,
        }
        by_key = {row.key: row for row in rows}
        for key, target in portable.items():
            current = values.get(key)
            if current and _is_under(current, legacy):
                values[key] = str(target)
                row = by_key.get(key)
                if row is not None and row.value != values[key]:
                    row.value = values[key]

    return AppSettings(
        values=values,
        operator_id=None,
        operator_name=values.get("operator_name") or "Administrator",
    )


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=str(value)))
    else:
        row.value = str(value)


def update_settings(session: Session, values: dict[str, str], paths: AppPaths) -> AppSettings:
    """Validate and persist a batch of settings."""
    allowed = set(default_settings(paths.home))
    unknown = set(values) - allowed
    if unknown:
        raise ValidationError(f"Unknown setting(s): {', '.join(sorted(unknown))}")

    if "timezone" in values:
        try:
            get_timezone(values["timezone"])
        except Exception:
            raise ValidationError("Unknown timezone.", "timezone") from None
    if "daily_close_time" in values:
        try:
            closing_time(values["daily_close_time"])
        except ValueError as exc:
            raise ValidationError(str(exc), "daily_close_time") from None
    if "theme" in values and values["theme"] not in {"light", "dark"}:
        raise ValidationError("Theme must be light or dark.", "theme")
    if "currency_code" in values:
        code = values["currency_code"].strip().upper()
        if not code:
            raise ValidationError("Currency code is required.", "currency_code")
        values["currency_code"] = code
        if "currency_symbol" not in values:
            values.setdefault("currency_symbol", CURRENCY_SYMBOLS.get(code, code + " "))
    if "currency_symbol" in values and values["currency_symbol"].strip() == "":
        raise ValidationError("Currency symbol is required.", "currency_symbol")
    if "page_size" in values:
        try:
            int(values["page_size"])
        except ValueError:
            raise ValidationError("Page size must be a number.", "page_size") from None
    if "report_dir" in values:
        resolve_dir(values["report_dir"], base=paths.home)
    if "backup_dir" in values:
        resolve_dir(values["backup_dir"], base=paths.home)
    if "operator_name" in values and not values["operator_name"].strip():
        raise ValidationError("Operator name is required.", "operator_name")

    for key, value in values.items():
        set_setting(session, key, value)

    return load_settings(session, paths)
