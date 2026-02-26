"""
NexusTreasury — Day-Count Convention Library
Implements ACT/360, ACT/365, 30/360 (ISDA), and ACT/ACT (ISDA).
All arithmetic uses Decimal; never float.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.exceptions import UnsupportedConventionError


class DayCountConvention:
    """Constants for day-count convention strings used throughout the system."""

    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    THIRTY_360 = "30/360"
    ACT_ACT = "ACT/ACT"


def _is_leap_year(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _30_360_days(start: date, end: date) -> Decimal:
    """30/360 day count per ISDA convention."""
    y1, m1, d1 = start.year, start.month, start.day
    y2, m2, d2 = end.year, end.month, end.day
    d1 = min(d1, 30)
    if d1 == 30:
        d2 = min(d2, 30)
    return Decimal(360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1))


def _act_act_isda_fraction(start: date, end: date) -> Decimal:
    """ACT/ACT ISDA: split period at year boundaries."""
    if start >= end:
        return Decimal("0")
    fraction = Decimal("0")
    current = start
    while current < end:
        year_end = date(current.year + 1, 1, 1)
        segment_end = min(year_end, end)
        days_in_segment = Decimal((segment_end - current).days)
        year_length = Decimal("366") if _is_leap_year(current.year) else Decimal("365")
        fraction += days_in_segment / year_length
        current = segment_end
    return fraction


# ─── Currency → Default Convention Mapping ────────────────────────────────────

CURRENCY_CONVENTION: dict[str, str] = {
    "USD": "ACT/360",
    "EUR": "ACT/360",
    "CHF": "ACT/360",
    "GBP": "ACT/365",
    "JPY": "ACT/365",
    "AUD": "ACT/365",
    "CAD": "ACT/365",
    "ZAR": "ACT/365",
    "USD_BOND": "30/360",
}

SUPPORTED_CONVENTIONS = frozenset({"ACT/360", "ACT/365", "30/360", "ACT/ACT"})


def resolve_convention(currency: str, subtype: str = "") -> str:
    if currency == "USD" and subtype.upper() in ("BOND", "FIXED"):
        return "30/360"
    return CURRENCY_CONVENTION.get(currency.upper(), "ACT/360")


def calculate_year_fraction(
    start: date,
    end: date,
    convention: str,
) -> Decimal:
    """
    Return the year fraction between start and end using the specified convention.
    Accepts either a string ('ACT/360') or a DayCountConvention constant.
    """
    if convention not in SUPPORTED_CONVENTIONS:
        raise UnsupportedConventionError(convention)

    if convention == DayCountConvention.ACT_360:
        return Decimal((end - start).days) / Decimal("360")

    if convention == DayCountConvention.ACT_365:
        return Decimal((end - start).days) / Decimal("365")

    if convention == DayCountConvention.THIRTY_360:
        return _30_360_days(start, end) / Decimal("360")

    if convention == DayCountConvention.ACT_ACT:
        return _act_act_isda_fraction(start, end)

    raise UnsupportedConventionError(convention)


def calculate_interest(
    notional: Decimal,
    rate: Decimal,
    start_date: date,
    end_date: date,
    convention: str,
) -> Decimal:
    """
    Calculate simple interest for a period.
    interest = notional × rate × year_fraction
    Negative rates produce negative interest (caller decides GL direction).

    Also callable with positional args as (principal, annual_rate, start, end, convention)
    for backward compatibility.
    """
    year_fraction = calculate_year_fraction(start_date, end_date, convention)
    return notional * rate * year_fraction
