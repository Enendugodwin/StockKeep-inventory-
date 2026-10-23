"""Timezone and business-date helpers.

Business dates are local calendar dates in the configured business timezone
(default Africa/Lagos).  Timestamps are persisted as naive UTC.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

DEFAULT_TZ = "Africa/Lagos"
DEFAULT_CLOSE = "23:59"


def get_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        log.warning("Timezone %r is unavailable; using UTC+1 fallback", name or DEFAULT_TZ)
        return timezone(timedelta(hours=1))


def utc_now() -> datetime:
    """Naive UTC timestamp, matching the database column convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc_naive(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def as_local(moment: datetime | None, tz_name: str | None = None) -> datetime | None:
    if moment is None:
        return None
    tz = get_timezone(tz_name)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def local_now(tz_name: str | None = None) -> datetime:
    return datetime.now(get_timezone(tz_name))


def today(tz_name: str | None = None) -> date:
    return local_now(tz_name).date()


def business_date_for(moment: datetime, tz_name: str | None = None) -> date:
    """Local calendar date for a timestamp (aware or naive UTC)."""
    local = as_local(moment, tz_name)
    return local.date() if local else today(tz_name)


def day_bounds_utc(day: date, tz_name: str | None = None) -> tuple[datetime, datetime]:
    """Inclusive/exclusive naive-UTC bounds covering a local business date."""
    tz = get_timezone(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        timezone.utc
    ).replace(tzinfo=None)
    return start, end


def parse_hhmm(value: str) -> time:
    try:
        hour, minute = str(value).strip().split(":")
        hour_i, minute_i = int(hour), int(minute)
        if not (0 <= hour_i <= 23 and 0 <= minute_i <= 59):
            raise ValueError
        return time(hour_i, minute_i)
    except (ValueError, AttributeError):
        raise ValueError(f"Closing time must be HH:MM (received {value!r}).") from None


def closing_time(close_text: str | None) -> time:
    try:
        return parse_hhmm(close_text or DEFAULT_CLOSE)
    except ValueError:
        return time(23, 59)


def last_closed_business_date(now: datetime, tz_name: str, close_text: str) -> date:
    """The latest business date whose daily report is due at `now`."""
    tz = get_timezone(tz_name)
    local = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=timezone.utc).astimezone(tz)
    close = closing_time(close_text)
    if local.time() >= close:
        return local.date()
    return local.date() - timedelta(days=1)


def is_report_due(day: date, now: datetime, tz_name: str, close_text: str) -> bool:
    return day <= last_closed_business_date(now, tz_name, close_text)


def parse_date(value, *, field: str = "date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{field} is not a valid date: {value!r}")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12:
        raise ValueError("Month must be between 1 and 12.")
    first = date(year, month, 1)
    last = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return first, last


def format_datetime_local(moment: datetime | None, tz_name: str | None = None) -> str:
    local = as_local(moment, tz_name)
    return local.strftime("%Y-%m-%d %H:%M:%S") if local else ""
