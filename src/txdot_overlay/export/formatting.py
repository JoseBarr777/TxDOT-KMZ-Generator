"""Clean numeric formatting for popup display: no stray ".0", real thousands
separators where useful, decimals preserved where they carry information.

Callers must check for missingness (see values.is_missing_value) before
calling these -- a formatter's job is to make a *present* value readable,
not to decide whether a value should be shown at all. Passing a missing
value here is a caller bug, not something this module papers over.
"""
from __future__ import annotations


def format_number(value: float | int, *, thousands: bool = False, decimals: int = 3) -> str:
    """Format a present numeric value: trims trailing zeros, keeps real ones.

    format_number(4.0) -> "4"
    format_number(0) -> "0"                  (valid zero, never blank)
    format_number(0.257) -> "0.257"
    format_number(12345, thousands=True) -> "12,345"
    format_number(1500.5, thousands=True) -> "1,500.5"
    """
    number = float(value)
    if number == int(number):
        integer_text = f"{int(number):,}" if thousands else str(int(number))
        return integer_text

    text = f"{number:,.{decimals}f}" if thousands else f"{number:.{decimals}f}"
    text = text.rstrip("0").rstrip(".")
    return text


def format_feet(value: float | int) -> str:
    return f"{format_number(value)} ft"


def format_mph(value: float | int) -> str:
    return f"{format_number(value)} mph"


def format_miles(value: float | int) -> str:
    return f"{format_number(value)} mi"


def format_count(value: float | int) -> str:
    """Whole-count values (lanes, year) -- no thousands separator, no decimals."""
    return format_number(value, decimals=0)


def format_traffic_count(value: float | int) -> str:
    """AADT-style counts: thousands separators, since these run into the tens
    of thousands and are read as magnitudes, not precise-looking small numbers."""
    return format_number(value, thousands=True, decimals=0)
