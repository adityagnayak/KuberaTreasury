"""
NexusTreasury — Business Day Logic (Phase 1)
Wrapper around `holidays` library to support multi-region calendars.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, cast

import holidays
from holidays.holiday_base import HolidayBase

# Map ISO currency codes to primary country codes for holiday lookups
CURRENCY_TO_COUNTRY: Dict[str, str] = {
    "USD": "US",
    "EUR": "DE",  # TARGET2 proxy (Frankfurt)
    "GBP": "GB",
    "JPY": "JP",
    "CHF": "CH",
    "AUD": "AU",
    "CAD": "CA",
    "INR": "IN",
}


def get_holiday_calendar(currency: str, years: List[int]) -> HolidayBase:
    """
    Return a holiday calendar object for the currency's country.
    Defaults to empty if not found.
    """
    country = CURRENCY_TO_COUNTRY.get(currency)
    if not country:
        # FIX: Explicitly cast empty dict to HolidayBase to satisfy mypy
        return cast(HolidayBase, {})

    try:
        # holidays.country_holidays returns a HolidayBase object
        return holidays.country_holidays(country, years=years)
    except Exception:
        return cast(HolidayBase, {})


def is_business_day(d: date, currency: str = "EUR") -> bool:
    """Check if date is a weekday and not a holiday."""
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False

    cal = get_holiday_calendar(currency, [d.year])
    return d not in cal


def get_next_business_day(d: date, currency: str = "EUR") -> date:
    """Roll forward to next business day."""
    next_day = d + timedelta(days=1)
    while not is_business_day(next_day, currency):
        next_day += timedelta(days=1)
    return next_day


def get_previous_business_day(d: date, currency: str = "EUR") -> date:
    """Roll backward to previous business day."""
    prev_day = d - timedelta(days=1)
    while not is_business_day(prev_day, currency):
        prev_day -= timedelta(days=1)
    return prev_day


def get_business_days_between(
    start: date, end: date, currency: str = "EUR"
) -> List[date]:
    """Return list of business days between start (exclusive) and end (inclusive)."""
    days = []
    current = start + timedelta(days=1)
    cal = get_holiday_calendar(currency, [start.year, end.year])

    while current <= end:
        if current.weekday() < 5 and current not in cal:
            days.append(current)
        current += timedelta(days=1)
    return days
