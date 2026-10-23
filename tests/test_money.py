"""Money and quantity precision tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stockkeep.errors import ValidationError
from stockkeep.money import (
    format_money,
    format_qty,
    from_milli,
    from_minor,
    line_total_minor,
    parse_decimal,
    percent_of,
    to_milli,
    to_minor,
)


def test_parse_decimal_accepts_symbols_and_separators():
    assert parse_decimal("₦1,234.50") == Decimal("1234.50")
    assert parse_decimal(" 12_000 ") == Decimal("12000")
    assert parse_decimal("(25.00)") == Decimal("-25.00")
    assert parse_decimal("", allow_blank=True) == Decimal("0")


@pytest.mark.parametrize("value", ["abc", "", "1.2.3", True])
def test_parse_decimal_rejects_garbage(value):
    with pytest.raises(ValidationError):
        parse_decimal(value)


def test_to_minor_rounds_half_up():
    assert to_minor("10.004") == 1000
    assert to_minor("10.005") == 1001
    assert to_minor(Decimal("0.1")) + to_minor(Decimal("0.2")) == 30


def test_to_milli_supports_three_decimals():
    assert to_milli("1.2344") == 1234
    assert to_milli("1.2345") == 1235
    assert from_milli(2500) == Decimal("2.5")


def test_formatting():
    assert format_money(123456) == "₦1,234.56"
    assert format_money(-500) == "-₦5.00"
    assert format_qty(1500) == "1.5"
    assert format_qty(0) == "0"
    assert from_minor(1999) == Decimal("19.99")


def test_line_total_uses_exact_arithmetic():
    # 3 x ₦0.10 is exactly 30 kobo (would drift with binary floats).
    assert line_total_minor(3000, 10) == 30
    assert line_total_minor(1500, 10000, discount_minor=500) == 14500
    with pytest.raises(ValidationError):
        line_total_minor(1000, 100, discount_minor=101)


def test_percent_of_rounds_half_up():
    assert percent_of(1000, Decimal("12.5")) == 125
    assert percent_of(999, Decimal("10")) == 100
