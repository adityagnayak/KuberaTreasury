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
        # Explicitly cast empty dict to HolidayBase to satisfy mypy
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
    """Roll forward to next business day (starting from d + 1)."""
    next_day = d + timedelta(days=1)
    while not is_business_day(next_day, currency):
        next_day += timedelta(days=1)
    return next_day


def get_previous_business_day(d: date, currency: str = "EUR") -> date:
    """Roll backward to previous business day (starting from d - 1)."""
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


# FIX: Added BusinessDayAdjuster class required by forecasting service
class BusinessDayAdjuster:
    """
    Adjusts dates according to business day conventions.
    """

    def adjust(
        self, date_obj: date, convention: str = "following", currency: str = "EUR"
    ) -> date:
        if is_business_day(date_obj, currency):
            return date_obj

        if convention == "following":
            return self._roll_forward(date_obj, currency)
        elif convention == "preceding":
            return self._roll_backward(date_obj, currency)
        elif convention == "modified_following":
            next_day = self._roll_forward(date_obj, currency)
            if next_day.month != date_obj.month:
                return self._roll_backward(date_obj, currency)
            return next_day
        elif convention == "modified_preceding":
            prev_day = self._roll_backward(date_obj, currency)
            if prev_day.month != date_obj.month:
                return self._roll_forward(date_obj, currency)
            return prev_day

        return date_obj

    def _roll_forward(self, d: date, currency: str) -> date:
        candidate = d + timedelta(days=1)
        while not is_business_day(candidate, currency):
            candidate += timedelta(days=1)
        return candidate

    def _roll_backward(self, d: date, currency: str) -> date:
        candidate = d - timedelta(days=1)
        while not is_business_day(candidate, currency):
            candidate -= timedelta(days=1)
        return candidate
