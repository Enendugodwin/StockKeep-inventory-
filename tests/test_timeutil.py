"""Timezone, business-date and closing-time tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from stockkeep.timeutil import (
    business_date_for,
    closing_time,
    day_bounds_utc,
    is_report_due,
    last_closed_business_date,
    parse_date,
    parse_hhmm,
)


def test_lagos_offset_has_no_dst():
    start, end = day_bounds_utc(date(2026, 1, 1), "Africa/Lagos")
    assert start == datetime(2025, 12, 31, 23, 0)
    assert end == datetime(2026, 1, 1, 23, 0)


def test_business_date_for_uses_local_offset():
    moment = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)  # 00:30 Lagos on Jan 2
    assert business_date_for(moment, "Africa/Lagos") == date(2026, 1, 2)


def test_last_closed_date_before_and_after_closing():
    before = datetime(2026, 1, 2, 22, 0, tzinfo=timezone.utc)  # 23:00 Lagos
    after = datetime(2026, 1, 2, 23, 30, tzinfo=timezone.utc)  # 00:30 Lagos Jan 3
    assert last_closed_business_date(before, "Africa/Lagos", "23:59") == date(2026, 1, 1)
    assert last_closed_business_date(after, "Africa/Lagos", "23:59") == date(2026, 1, 2)


def test_report_due_only_after_closing():
    now = datetime(2026, 1, 2, 22, 30, tzinfo=timezone.utc)  # 23:30 Lagos on Jan 2
    assert is_report_due(date(2026, 1, 1), now, "Africa/Lagos", "23:59") is True
    assert is_report_due(date(2026, 1, 2), now, "Africa/Lagos", "23:59") is False


def test_parse_helpers():
    assert parse_hhmm("23:59") == closing_time("23:59")
    assert parse_date("2026-02-03") == date(2026, 2, 3)
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    with pytest.raises(ValueError):
        parse_date("not-a-date")
