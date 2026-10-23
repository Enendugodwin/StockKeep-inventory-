"""Fixed-precision money and quantity helpers.

Financial values are stored as integer minor units (kobo/cents) and quantities
as integer thousandths.  Conversion to Decimal happens at service boundaries;
binary floating point is never used for arithmetic.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .errors import ValidationError

CENT = Decimal("0.01")
MILLI = Decimal("0.001")
ZERO = Decimal("0")

CURRENCY_SYMBOLS = {
    "NGN": "\u20a6",
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "GHS": "\u20b5",
    "KES": "KSh ",
    "ZAR": "R ",
    "CAD": "C$",
    "INR": "\u20b9",
}

_STRIP = "\u20a6$\u20ac\u00a3\u00b5\u20b9, \t\r\n\u00a0"


def parse_decimal(value, *, field: str = "value", allow_blank: bool = False) -> Decimal:
    """Parse a user/CSV supplied value into an exact Decimal.

    Accepts thousands separators, surrounding whitespace and common currency
    symbols.  Raises ValidationError with a friendly message on garbage input.
    """
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a number.", field)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(str(value))
    else:
        text = str(value if value is not None else "").strip()
        if text == "":
            if allow_blank:
                return ZERO
            raise ValidationError(f"{field} is required.", field)
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        text = text.replace("_", "")
        for symbol in _STRIP:
            text = text.replace(symbol, "")
        if text in {"", "-", "+"}:
            if allow_blank:
                return ZERO
            raise ValidationError(f"{field} is not a valid number.", field)
        try:
            result = Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValidationError(f"{field} is not a valid number: {value!r}", field) from None
        if negative:
            result = -result
    if not result.is_finite():
        raise ValidationError(f"{field} must be a finite number.", field)
    return result


def parse_non_negative(value, *, field: str) -> Decimal:
    number = parse_decimal(value, field=field)
    if number < 0:
        raise ValidationError(f"{field} cannot be negative.", field)
    return number


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_minor(value, *, field: str = "amount") -> int:
    """Convert a money amount to integer minor units (kobo/cents)."""
    number = parse_decimal(value, field=field)
    return int(quantize_money(number) * 100)


def from_minor(minor: int | None) -> Decimal:
    return Decimal(int(minor or 0)) / 100


def to_milli(value, *, field: str = "quantity") -> int:
    """Convert a quantity to integer thousandths (supports weighed goods)."""
    number = parse_decimal(value, field=field)
    return int((number.quantize(MILLI, rounding=ROUND_HALF_UP)) * 1000)


def from_milli(milli: int | None) -> Decimal:
    return Decimal(int(milli or 0)) / 1000


def format_qty(milli: int | None, *, thousands: bool = True) -> str:
    number = from_milli(milli)
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    if thousands:
        try:
            whole, _, fraction = text.partition(".")
            whole = f"{int(whole):,}"
            text = f"{whole}.{fraction}" if fraction else whole
        except ValueError:
            pass
    return text


def format_money(minor: int | None, symbol: str = "\u20a6", *, space: bool = False) -> str:
    value = Decimal(int(minor or 0)) / 100
    negative = value < 0
    value = abs(value)
    whole, frac = divmod(int((value * 100).to_integral_value()), 100)
    text = f"{whole:,}.{frac:02d}"
    separator = " " if space else ""
    return f"{'-' if negative else ''}{symbol}{separator}{text}"


def format_plain(minor: int | None) -> str:
    """Money without a currency symbol, suitable for CSV/Excel numeric cells."""
    value = Decimal(int(minor or 0)) / 100
    whole, frac = divmod(int((abs(value) * 100).to_integral_value()), 100)
    return f"{'-' if value < 0 else ''}{whole:,}.{frac:02d}"


def line_total_minor(quantity_milli: int, unit_price_minor: int, discount_minor: int = 0) -> int:
    """qty * price, rounded to minor units, minus a discount in minor units."""
    if quantity_milli < 0:
        raise ValidationError("Quantity cannot be negative.", "quantity")
    if unit_price_minor < 0:
        raise ValidationError("Unit price cannot be negative.", "unit_price")
    if discount_minor < 0:
        raise ValidationError("Discount cannot be negative.", "discount")
    gross = quantize_money(from_milli(quantity_milli) * from_minor(unit_price_minor))
    total = int(gross * 100) - int(discount_minor)
    if total < 0:
        raise ValidationError("Discount cannot exceed the line value.", "discount")
    return total


def percent_of(minor: int, percent: Decimal) -> int:
    """Return `percent` of a money amount, rounded half-up."""
    return int(quantize_money(from_minor(minor) * percent / Decimal(100)) * 100)


def as_decimal_str(minor: int | None) -> str:
    """Stable decimal string for CSV cells (no thousands separators)."""
    return f"{from_minor(minor):.2f}"
