"""
NexusTreasury — Business Day Logic (Phase 1)
Wrapper around `holidays` library to support multi-region calendars.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, cast

import holidays
from holidays.holiday_base import HolidayBase

from app.core.exceptions import InvalidBusinessDayConventionError

CURRENCY_TO_COUNTRY: Dict[str, str] = {
    "USD": "US",
    "EUR": "DE",
    "GBP": "GB",
    "JPY": "JP",
    "CHF": "CH",
    "AUD": "AU",
    "CAD": "CA",
    "INR": "IN",
    "SEK": "SE",
    "NOK": "NO",
    "DKK": "DK",
}

VALID_CONVENTIONS = {
    "following",
    "preceding",
    "modified_following",
    "modified_preceding",
}


def get_holiday_calendar(currency: str, years: List[int]) -> HolidayBase:
    country = CURRENCY_TO_COUNTRY.get(currency)
    if not country:
        return cast(HolidayBase, {})
    try:
        return holidays.country_holidays(country, years=years)
    except Exception:
        return cast(HolidayBase, {})


def is_business_day(d: date, currency: str = "EUR") -> bool:
    if d.weekday() >= 5:
        return False
    cal = get_holiday_calendar(currency, [d.year])
    return d not in cal


def get_business_days_between(
    start: date, end: date, currency: str = "EUR"
) -> List[date]:
    days = []
    current = start + timedelta(days=1)
    cal = get_holiday_calendar(currency, [start.year, end.year])

    while current < end:
        if current.weekday() < 5 and current not in cal:
            days.append(current)
        current += timedelta(days=1)
    return days


class BusinessDayAdjuster:
    def __init__(self, currency: str = "EUR", convention: str = "following"):
        if currency not in CURRENCY_TO_COUNTRY:
            raise ValueError(f"No country mapping for currency: {currency}")

        valid_conventions = {
            "following",
            "preceding",
            "modified_following",
            "modified_preceding",
        }
        if convention not in valid_conventions:
            raise InvalidBusinessDayConventionError(convention)

        self.currency = currency
        # FIX: was `conventionn` (double-n typo) — caused NameError on every
        # BusinessDayAdjuster instantiation.
        self.convention = convention

    def is_business_day(self, date_obj: date) -> bool:
        return is_business_day(date_obj, self.currency)

    def adjust(
        self,
        date_obj: date,
        convention: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> date:
        cur = currency or self.currency
        conv = convention or self.convention

        if is_business_day(date_obj, cur):
            return date_obj

        if conv == "following":
            return self._roll_forward(date_obj, cur)
        elif conv == "preceding":
            return self._roll_backward(date_obj, cur)
        elif conv == "modified_following":
            next_day = self._roll_forward(date_obj, cur)
            if next_day.month != date_obj.month:
                return self._roll_backward(date_obj, cur)
            return next_day
        elif conv == "modified_preceding":
            prev_day = self._roll_backward(date_obj, cur)
            if prev_day.month != date_obj.month:
                return self._roll_forward(date_obj, cur)
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
