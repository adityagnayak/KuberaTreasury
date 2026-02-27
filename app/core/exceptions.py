"""
NexusTreasury — Unified Custom Exceptions (all phases consolidated).
Each exception carries: message, error_code, http_status_code, optional detail dict.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# BASE
# ─────────────────────────────────────────────────────────────────────────────


class NexusTreasuryError(Exception):
    """Root exception for all NexusTreasury errors."""

    http_status_code: int = 400
    error_code: str = "NEXUS_ERROR"

    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self.message = message
        self.detail = detail or {}
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Statement Ingestion & Database Integrity
# ─────────────────────────────────────────────────────────────────────────────


class DuplicateStatementError(NexusTreasuryError):
    http_status_code = 409
    error_code = "DUPLICATE_STATEMENT"

    def __init__(
        self, message_id: str, original_import_timestamp: datetime, file_hash: str
    ) -> None:
        self.message_id = message_id
        self.original_import_timestamp = original_import_timestamp
        self.file_hash = file_hash
        super().__init__(
            message=f"Duplicate statement: message_id={message_id!r} first imported at {original_import_timestamp.isoformat()}",
            detail={
                "message_id": message_id,
                "original_import_timestamp": original_import_timestamp.isoformat(),
                "file_hash": file_hash,
            },
        )


class LockedPeriodError(NexusTreasuryError):
    http_status_code = 422
    error_code = "LOCKED_PERIOD"

    def __init__(self, value_date: date, locked_until: date) -> None:
        self.value_date = value_date
        self.locked_until = locked_until
        super().__init__(
            message=f"Transaction value_date {value_date} falls within locked period (locked_until={locked_until})",
            detail={"value_date": str(value_date), "locked_until": str(locked_until)},
        )


class AccountNotFoundError(NexusTreasuryError):
    http_status_code = 404
    error_code = "ACCOUNT_NOT_FOUND"

    def __init__(
        self, iban: Optional[str] = None, account_id: Optional[str] = None
    ) -> None:
        self.iban = iban
        self.account_id = account_id
        identifier = f"IBAN={iban!r}" if iban else f"id={account_id!r}"
        super().__init__(
            message=f"No bank account found for {identifier}",
            detail={"iban": iban, "account_id": account_id},
        )


class InvalidIBANError(NexusTreasuryError):
    http_status_code = 422
    error_code = "INVALID_IBAN"

    def __init__(self, iban: str, reason: str = "failed validation") -> None:
        self.iban = iban
        self.reason = reason
        super().__init__(
            message=f"Invalid IBAN '{iban}': {reason}",
            detail={"iban": iban, "reason": reason},
        )


class InvalidBICError(NexusTreasuryError):
    http_status_code = 422
    error_code = "INVALID_BIC"

    def __init__(self, bic: str, reason: str = "failed validation") -> None:
        self.bic = bic
        self.reason = reason
        super().__init__(
            message=f"Invalid BIC '{bic}': {reason}",
            detail={"bic": bic, "reason": reason},
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Cash Positioning & Forecasting
# ─────────────────────────────────────────────────────────────────────────────


class FXRateNotFoundError(NexusTreasuryError):
    http_status_code = 404
    error_code = "FX_RATE_NOT_FOUND"

    def __init__(self, from_ccy: str, to_ccy: str) -> None:
        self.from_ccy = from_ccy
        self.to_ccy = to_ccy
        super().__init__(
            message=f"FX rate not found: {from_ccy} -> {to_ccy}",
            detail={"from_currency": from_ccy, "to_currency": to_ccy},
        )


class ForecastNotFoundError(NexusTreasuryError):
    http_status_code = 404
    error_code = "FORECAST_NOT_FOUND"

    def __init__(self, forecast_id: str) -> None:
        self.forecast_id = forecast_id
        super().__init__(
            message=f"Forecast {forecast_id} not found",
            detail={"forecast_id": forecast_id},
        )


class VarianceThresholdBreached(NexusTreasuryError):
    """Raised when forecast vs actual variance exceeds the configured threshold."""

    http_status_code = 422
    error_code = "VARIANCE_THRESHOLD_BREACHED"

    def __init__(self, variance_amount: Decimal, threshold: Decimal) -> None:
        self.variance_amount = variance_amount
        self.threshold = threshold
        super().__init__(
            message=f"Variance {variance_amount} exceeds threshold {threshold}",
            detail={
                "variance_amount": str(variance_amount),
                "threshold": str(threshold),
            },
        )


class InvalidBusinessDayConventionError(NexusTreasuryError):
    http_status_code = 422
    error_code = "INVALID_BUSINESS_DAY_CONVENTION"

    def __init__(self, convention: str) -> None:
        self.convention = convention
        super().__init__(
            message=f"Unknown business-day convention: {convention!r}",
            detail={"convention": convention},
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Payment Factory
# ─────────────────────────────────────────────────────────────────────────────


class SelfApprovalError(NexusTreasuryError):
    http_status_code = 403
    error_code = "SELF_APPROVAL_FORBIDDEN"

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__(
            message=f"Self-approval not permitted for user '{user_id}'",
            detail={"user_id": user_id},
        )


class UnauthorizedApproverError(NexusTreasuryError):
    """Raised when the approver does not have sufficient role/permissions."""

    http_status_code = 403
    error_code = "UNAUTHORIZED_APPROVER"

    def __init__(self, user_id: str, required_role: str = "manager") -> None:
        self.user_id = user_id
        self.required_role = required_role
        super().__init__(
            message=f"User '{user_id}' is not authorized to approve payments (requires {required_role})",
            detail={"user_id": user_id, "required_role": required_role},
        )


class SanctionsHitError(NexusTreasuryError):
    http_status_code = 403
    error_code = "SANCTIONS_HIT"

    def __init__(
        self,
        payment_id: str,
        matched_field: str,
        matched_value: str,
        list_entry_name: str,
        list_type: str,
        similarity_score: float,
    ) -> None:
        self.payment_id = payment_id
        self.matched_field = matched_field
        self.matched_value = matched_value
        self.list_entry_name = list_entry_name
        self.list_type = list_type
        self.similarity_score = similarity_score
        self.match_score = similarity_score  # alias used by tests
        super().__init__(
            message=f"Sanctions hit: {matched_field}={matched_value!r} matches {list_entry_name!r}",
            detail={
                "payment_id": payment_id,
                "matched_field": matched_field,
                "matched_value": matched_value,
                "list_entry_name": list_entry_name,
                "list_type": list_type,
                "similarity_score": similarity_score,
            },
        )


class InsufficientFundsError(NexusTreasuryError):
    http_status_code = 422
    error_code = "INSUFFICIENT_FUNDS"

    def __init__(self, available: Decimal, requested: Decimal) -> None:
        self.available = available
        self.requested = requested
        super().__init__(
            message=f"Insufficient funds: available={available}, requested={requested}",
            detail={
                "available": str(available),
                "requested": str(requested),
                "shortfall": str(requested - available),
            },
        )


class PaymentValidationError(NexusTreasuryError):
    http_status_code = 422
    error_code = "PAYMENT_VALIDATION_ERROR"

    def __init__(self, errors: List[Dict[str, str]]) -> None:
        self.errors = errors
        super().__init__(
            message=f"Payment validation failed with {len(errors)} error(s)",
            detail={"validation_errors": errors},
        )


class InvalidSignatureError(NexusTreasuryError):
    http_status_code = 401
    error_code = "INVALID_SIGNATURE"

    def __init__(self, payment_id: str) -> None:
        self.payment_id = payment_id
        super().__init__(
            message=f"Signature verification failed for payment {payment_id}",
            detail={"payment_id": payment_id},
        )


class InvalidStateTransitionError(NexusTreasuryError):
    http_status_code = 422
    error_code = "INVALID_STATE_TRANSITION"

    def __init__(self, current: str, target: str) -> None:
        self.current_state = current
        self.target_state = target
        super().__init__(
            message=f"Cannot transition from '{current}' to '{target}'",
            detail={"current_state": current, "target_state": target},
        )


class PaymentNotFoundError(NexusTreasuryError):
    http_status_code = 404
    error_code = "PAYMENT_NOT_FOUND"

    def __init__(self, payment_id: str) -> None:
        self.payment_id = payment_id
        super().__init__(
            message=f"Payment {payment_id} not found", detail={"payment_id": payment_id}
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — FX Risk & GL Engine
# ─────────────────────────────────────────────────────────────────────────────


class MarketVolatilityAlert(NexusTreasuryError):
    """Soft flash-crash alert: move exceeds soft threshold but not hard threshold."""

    http_status_code = 503
    error_code = "MARKET_VOLATILITY_ALERT"
    is_hard_crash: bool = False
    severity: str = "SOFT"

    def __init__(
        self, pair: str, old_rate: Decimal, new_rate: Decimal, swing_pct: Decimal
    ) -> None:
        self.pair = pair
        self.old_rate = old_rate
        self.new_rate = new_rate
        self.swing_pct = swing_pct
        super().__init__(
            message=f"Flash crash detected on {pair}: {float(swing_pct):.2%} swing",
            detail={
                "pair": pair,
                "old_rate": str(old_rate),
                "new_rate": str(new_rate),
                "swing_pct": str(swing_pct),
                "severity": self.severity,
            },
        )


class FlashCrashAlert(MarketVolatilityAlert):
    """Hard flash-crash alert: move exceeds hard threshold — halt trading."""

    error_code = "FLASH_CRASH_ALERT"
    is_hard_crash: bool = True
    severity: str = "HARD"


class UnbalancedJournalError(NexusTreasuryError):
    http_status_code = 422
    error_code = "UNBALANCED_JOURNAL"

    def __init__(self, total_debits: Decimal, total_credits: Decimal) -> None:
        self.total_debits = total_debits
        self.total_credits = total_credits
        super().__init__(
            message=f"Journal imbalance: debits={total_debits} credits={total_credits} difference={total_debits - total_credits}",
            detail={
                "total_debits": str(total_debits),
                "total_credits": str(total_credits),
                "difference": str(total_debits - total_credits),
            },
        )


class TransferPricingViolationError(NexusTreasuryError):
    http_status_code = 422
    error_code = "TRANSFER_PRICING_VIOLATION"

    # FIX: Updated signature to match test usage (deviation_bps, max_allowed_bps)
    def __init__(
        self,
        proposed_rate: Decimal,
        base_rate: Decimal,
        deviation_bps: int | float | None = None,
        max_allowed_bps: int | float | None = None,
        arm_length_bps: Decimal | None = None,
    ) -> None:
        self.proposed_rate = proposed_rate
        self.base_rate = base_rate

        # Handle different arguments from test vs code
        threshold = arm_length_bps
        if threshold is None and max_allowed_bps is not None:
            threshold = Decimal(str(max_allowed_bps))
        if threshold is None:
            threshold = Decimal("150")  # Default fallback

        bps = threshold / Decimal("10000")
        lower = base_rate - bps
        upper = base_rate + bps

        detail_dict = {
            "proposed_rate": str(proposed_rate),
            "base_rate": str(base_rate),
            "lower_bound": str(lower),
            "upper_bound": str(upper),
            "threshold_bps": str(threshold),
        }

        if deviation_bps is not None:
            detail_dict["deviation_bps"] = str(deviation_bps)

        super().__init__(
            message=f"Proposed rate {proposed_rate} is outside arm's-length range [{lower}, {upper}]",
            detail=detail_dict,
        )


class UnsupportedConventionError(NexusTreasuryError):
    http_status_code = 422
    error_code = "UNSUPPORTED_CONVENTION"

    def __init__(self, convention: str) -> None:
        self.convention = convention
        super().__init__(
            message=f"Unsupported day-count convention: {convention!r}",
            detail={"convention": convention},
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 — E-BAM, RBAC, Concurrency
# ─────────────────────────────────────────────────────────────────────────────


class PositionLockConflict(NexusTreasuryError):
    http_status_code = 409
    error_code = "POSITION_LOCK_CONFLICT"

    def __init__(self, account_id: str, locked_by: str, expires_at: datetime) -> None:
        self.account_id = account_id
        self.locked_by = locked_by
        self.expires_at = expires_at
        super().__init__(
            message=f"Position lock conflict on account {account_id}: held by {locked_by!r}, expires {expires_at.isoformat()}",
            detail={
                "account_id": account_id,
                "locked_by": locked_by,
                "expires_at": expires_at.isoformat(),
            },
        )


class NoMandateError(NexusTreasuryError):
    # FIX: Changed to 404 to match test expectations (400, 404)
    http_status_code = 404
    error_code = "NO_MANDATE"

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(
            message=f"No active mandate found for account {account_id}",
            detail={"account_id": account_id},
        )


class ExpiredMandateError(NexusTreasuryError):
    # FIX: Changed to 422 to match test expectations (400, 422)
    http_status_code = 422
    error_code = "EXPIRED_MANDATE"

    def __init__(self, account_id: str, expired_on: date) -> None:
        self.account_id = account_id
        self.expired_on = expired_on
        super().__init__(
            message=f"Mandate for account {account_id} expired on {expired_on.isoformat()}",
            detail={"account_id": account_id, "expired_on": str(expired_on)},
        )


class MandateKeyMismatchError(NexusTreasuryError):
    http_status_code = 403
    error_code = "MANDATE_KEY_MISMATCH"

    # FIX: Added arguments for expected/actual fingerprint to match tests
    def __init__(
        self,
        account_id: str,
        expected_fingerprint: str | None = None,
        actual_fingerprint: str | None = None,
    ) -> None:
        self.account_id = account_id
        detail = {"account_id": account_id}
        if expected_fingerprint:
            detail["expected"] = expected_fingerprint
        if actual_fingerprint:
            detail["actual"] = actual_fingerprint

        super().__init__(
            message=f"Checker public key does not match any active mandate for account {account_id}",
            detail=detail,
        )


class PermissionDeniedError(NexusTreasuryError):
    http_status_code = 403
    error_code = "PERMISSION_DENIED"

    def __init__(self, role: str, action: str = "", resource: str = "") -> None:
        self.role = role
        self.action = action
        self.resource = resource
        super().__init__(
            message=f"Role '{role}' is not permitted to perform {action} on {resource}",
            detail={"role": role, "action": action, "resource": resource},
        )


class AuthenticationError(NexusTreasuryError):
    http_status_code = 401
    error_code = "AUTHENTICATION_ERROR"

    def __init__(self, reason: str = "Invalid or expired token") -> None:
        super().__init__(message=reason, detail={"reason": reason})


class DoubleApprovalError(NexusTreasuryError):
    http_status_code = 409
    error_code = "DOUBLE_APPROVAL"

    def __init__(self, payment_id: str, user_id: str) -> None:
        self.payment_id = payment_id
        self.user_id = user_id
        super().__init__(
            message=f"Payment {payment_id} has already been approved or processed.",
            detail={"payment_id": payment_id, "attempted_by": user_id},
        )
