"""
NexusTreasury — Business Day Adjuster
Rolls dates for weekends/public holidays using following, modified_following,
or preceding conventions. Backed by the `holidays` library.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

import holidays as holidays_lib

from app.core.exceptions import InvalidBusinessDayConventionError

# ─── Currency → ISO country code ──────────────────────────────────────────────

CURRENCY_COUNTRY_MAP: Dict[str, str] = {
    "USD": "US",
    "GBP": "GB",
    "EUR": "DE",   # ECB TARGET2 — Germany as proxy
    "JPY": "JP",
    "CHF": "CH",
    "AUD": "AU",
    "CAD": "CA",
    "SEK": "SE",
    "NOK": "NO",
    "DKK": "DK",
}


class BusinessDayAdjuster:
    """
    Roll dates that fall on weekends or public holidays.
    Conventions: 'following', 'modified_following', 'preceding'.
    """

    SUPPORTED_CONVENTIONS = frozenset(
        {"following", "modified_following", "preceding"}
    )

    def __init__(self, currency: str, convention: str = "modified_following") -> None:
        country = CURRENCY_COUNTRY_MAP.get(currency.upper())
        if country is None:
            raise ValueError(f"No country mapping for currency '{currency}'")

        if convention not in self.SUPPORTED_CONVENTIONS:
            raise InvalidBusinessDayConventionError(convention)

        self._currency = currency.upper()
        self._convention = convention
        self._holidays = holidays_lib.country_holidays(country)

    def is_business_day(self, d: date) -> bool:
        """Return True if `d` is a Mon–Fri weekday that is not a public holiday."""
        return d.weekday() < 5 and d not in self._holidays

    def adjust(self, d: date) -> date:
        """Roll `d` to the nearest valid business day per the configured convention."""
        if self.is_business_day(d):
            return d

        if self._convention == "following":
            return self._roll_forward(d)

        if self._convention == "preceding":
            return self._roll_backward(d)

        if self._convention == "modified_following":
            candidate = self._roll_forward(d)
            if candidate.month != d.month:
                # Crossed month boundary — roll backward instead
                return self._roll_backward(d)
            return candidate

        raise InvalidBusinessDayConventionError(self._convention)

    def _roll_forward(self, d: date) -> date:
        candidate = d + timedelta(days=1)
        while not self.is_business_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def _roll_backward(self, d: date) -> date:
        candidate = d - timedelta(days=1)
        while not self.is_business_day(candidate):
            candidate -= timedelta(days=1)
        return candidate


def get_business_days_between(
    start_date: date,
    end_date: date,
    currency: str,
) -> List[date]:
    """
    Return all Mon–Fri business days strictly between start_date and end_date
    (both exclusive). Uses holiday calendar for the currency's home country.
    """
    country_code = CURRENCY_COUNTRY_MAP.get(currency.upper(), "US")
    try:
        country_holidays = holidays_lib.country_holidays(country_code)
    except Exception:
        country_holidays = {}

    result: List[date] = []
    current = start_date + timedelta(days=1)
    while current < end_date:
        if current.weekday() < 5 and current not in country_holidays:
            result.append(current)
        current += timedelta(days=1)
    return result
