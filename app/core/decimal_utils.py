"""
NexusTreasury — Decimal Utilities
Central Decimal context setup and rounding helpers.
Never use float near monetary values — always use Decimal.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Union

# Set high-precision context globally for the process
getcontext().prec = 28


def monetary(value: Union[str, int, float, Decimal]) -> Decimal:
    """
    Convert any numeric value to a Decimal suitable for monetary calculations.
    Raises TypeError on non-numeric input to prevent silent float contamination.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # Force via string to avoid float imprecision
        return Decimal(str(value))
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError(f"Cannot convert {type(value).__name__} to Decimal monetary value")


def display_round(amount: Decimal, places: int = 2) -> Decimal:
    """Round to `places` decimal places for display/reporting only."""
    quantizer = Decimal(10) ** -places
    return amount.quantize(quantizer, rounding=ROUND_HALF_UP)


def db_round(amount: Decimal) -> Decimal:
    """Round to 8 decimal places for database storage (Numeric(28,8))."""
    return amount.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def is_zero(amount: Decimal) -> bool:
    return amount == Decimal("0")


def is_positive(amount: Decimal) -> bool:
    return amount > Decimal("0")


def is_negative(amount: Decimal) -> bool:
    return amount < Decimal("0")


def safe_percentage(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """
    Return (numerator / denominator) * 100 as a percentage Decimal.
    Returns None if denominator is zero (infinite variance).
    """
    if denominator == Decimal("0"):
        return None
    return abs(numerator) / abs(denominator) * Decimal("100")
