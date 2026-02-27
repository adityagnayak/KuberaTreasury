"""
NexusTreasury — Core Utilities Test Suite
Covers app/core/: business_days, decimal_utils, security, exceptions
"""

from __future__ import annotations

import base64
from datetime import date, datetime  # Added datetime here
from decimal import Decimal

import pytest
from fastapi import HTTPException

# --- Moved these imports to the top ---
from app.core.business_days import BusinessDayAdjuster, get_business_days_between
from app.core.decimal_utils import (
    db_round,
    display_round,
    is_negative,
    is_positive,
    is_zero,
    monetary,
    safe_percentage,
)
from app.core.exceptions import (
    AccountNotFoundError,
    DuplicateStatementError,
    ExpiredMandateError,
    InsufficientFundsError,
    InvalidBusinessDayConventionError,
    InvalidStateTransitionError,
    LockedPeriodError,
    MandateKeyMismatchError,
    NexusTreasuryError,
    NoMandateError,
    PaymentNotFoundError,
    PaymentValidationError,
    PermissionDeniedError,
    SanctionsHitError,
    SelfApprovalError,
    TransferPricingViolationError,
    UnbalancedJournalError,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_credential,
    encrypt_credential,
    hash_password,
    verify_password,
)

# ═══════════════════════════════════════════════════════════════════════════════
# business_days.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestBusinessDayAdjuster:
    def test_weekday_unchanged(self):
        adjuster = BusinessDayAdjuster("EUR")
        monday = date(2024, 1, 8)  # Monday
        assert adjuster.adjust(monday) == monday

    def test_saturday_rolls_forward(self):
        adjuster = BusinessDayAdjuster("EUR", convention="following")
        saturday = date(2024, 1, 6)  # Saturday → Monday Jan 8
        result = adjuster.adjust(saturday)
        assert result.weekday() < 5
        assert result > saturday

    def test_saturday_modified_following(self):
        adjuster = BusinessDayAdjuster("EUR", convention="modified_following")
        saturday = date(2024, 1, 6)
        result = adjuster.adjust(saturday)
        assert result.weekday() < 5

    def test_saturday_preceding_rolls_backward(self):
        adjuster = BusinessDayAdjuster("EUR", convention="preceding")
        saturday = date(2024, 1, 6)  # Saturday → Friday Jan 5
        result = adjuster.adjust(saturday)
        assert result.weekday() < 5
        assert result < saturday

    def test_modified_following_month_boundary(self):
        # Last Saturday of month — should roll BACK, not forward into next month
        adjuster = BusinessDayAdjuster("EUR", convention="modified_following")
        # Find a last-day-of-month that's a Saturday
        saturday_eom = date(2022, 4, 30)  # April 30 2022 is a Saturday
        result = adjuster.adjust(saturday_eom)
        assert result.month == 4  # stays in April, rolls back to Friday

    def test_is_business_day_weekday(self):
        adjuster = BusinessDayAdjuster("USD")
        assert adjuster.is_business_day(date(2024, 1, 8)) is True  # Monday

    def test_is_business_day_weekend(self):
        adjuster = BusinessDayAdjuster("USD")
        assert adjuster.is_business_day(date(2024, 1, 6)) is False  # Saturday
        assert adjuster.is_business_day(date(2024, 1, 7)) is False  # Sunday

    def test_invalid_currency_raises(self):
        with pytest.raises(ValueError, match="No country mapping"):
            BusinessDayAdjuster("ZZZ")

    def test_invalid_convention_raises(self):
        with pytest.raises(InvalidBusinessDayConventionError):
            BusinessDayAdjuster("EUR", convention="bad_convention")

    def test_gbp_uses_gb_holidays(self):
        adjuster = BusinessDayAdjuster("GBP")
        # UK Christmas Day 2024 is Wednesday — should not be a business day
        christmas = date(2024, 12, 25)
        assert adjuster.is_business_day(christmas) is False

    def test_all_supported_currencies(self):
        for ccy in [
            "USD",
            "GBP",
            "EUR",
            "JPY",
            "CHF",
            "AUD",
            "CAD",
            "SEK",
            "NOK",
            "DKK",
        ]:
            adj = BusinessDayAdjuster(ccy)
            assert adj.is_business_day(date(2024, 6, 3)) is True  # Monday


class TestGetBusinessDaysBetween:
    def test_returns_weekdays_only(self):
        result = get_business_days_between(date(2024, 1, 1), date(2024, 1, 8), "EUR")
        for d in result:
            assert d.weekday() < 5

    def test_exclusive_bounds(self):
        result = get_business_days_between(date(2024, 1, 8), date(2024, 1, 12), "EUR")
        # Jan 8 (Mon) and Jan 12 (Fri) are excluded; Jan 9–11 (Tue/Wed/Thu) included
        assert date(2024, 1, 8) not in result
        assert date(2024, 1, 12) not in result

    def test_empty_range(self):
        result = get_business_days_between(date(2024, 1, 8), date(2024, 1, 9), "EUR")
        assert result == []

    def test_returns_list_of_dates(self):
        result = get_business_days_between(date(2024, 1, 1), date(2024, 1, 31), "USD")
        assert all(isinstance(d, date) for d in result)
        assert len(result) > 0

    def test_unknown_currency_defaults_to_us(self):
        # Should not raise — falls back to US calendar
        result = get_business_days_between(date(2024, 1, 1), date(2024, 1, 10), "XYZ")
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════════════════
# decimal_utils.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestMonetary:
    def test_decimal_passthrough(self):
        d = Decimal("123.456")
        assert monetary(d) is d

    def test_int_converts(self):
        assert monetary(100) == Decimal("100")

    def test_str_converts(self):
        assert monetary("99.99") == Decimal("99.99")

    def test_float_via_string(self):
        result = monetary(1.1)
        assert isinstance(result, Decimal)
        # Should not have float imprecision artefact
        assert str(result) == "1.1"

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            monetary([1, 2, 3])

    def test_negative_decimal(self):
        assert monetary("-500.00") == Decimal("-500.00")


class TestRounding:
    def test_display_round_2dp(self):
        result = display_round(Decimal("1234.5678"))
        assert result == Decimal("1234.57")

    def test_display_round_custom_places(self):
        result = display_round(Decimal("1.23456"), places=4)
        assert result == Decimal("1.2346")

    def test_db_round_8dp(self):
        result = db_round(Decimal("1.123456789"))
        assert result == Decimal("1.12345679")

    def test_display_round_half_up(self):
        # 2.5 rounds up to 3
        assert display_round(Decimal("2.5"), places=0) == Decimal("3")


class TestPredicates:
    def test_is_zero(self):
        assert is_zero(Decimal("0")) is True
        assert is_zero(Decimal("0.001")) is False

    def test_is_positive(self):
        assert is_positive(Decimal("0.01")) is True
        assert is_positive(Decimal("0")) is False
        assert is_positive(Decimal("-1")) is False

    def test_is_negative(self):
        assert is_negative(Decimal("-0.01")) is True
        assert is_negative(Decimal("0")) is False
        assert is_negative(Decimal("1")) is False


class TestSafePercentage:
    def test_normal_calculation(self):
        result = safe_percentage(Decimal("50"), Decimal("200"))
        assert result == Decimal("25")

    def test_zero_denominator_returns_none(self):
        assert safe_percentage(Decimal("100"), Decimal("0")) is None

    def test_negative_numerator_uses_abs(self):
        result = safe_percentage(Decimal("-30"), Decimal("100"))
        assert result == Decimal("30")


# ═══════════════════════════════════════════════════════════════════════════════
# security.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestJWT:
    def test_create_and_decode_round_trip(self):
        token = create_access_token("user_001", "treasury_analyst")
        payload = decode_access_token(token)
        assert payload["sub"] == "user_001"
        assert payload["role"] == "treasury_analyst"

    def test_token_has_exp_claim(self):
        token = create_access_token("user_002", "auditor")
        payload = decode_access_token(token)
        assert "exp" in payload

    def test_custom_expiry(self):
        token = create_access_token("user_003", "system_admin", expires_minutes=120)
        payload = decode_access_token(token)
        assert payload["sub"] == "user_003"

    def test_extra_claims_embedded(self):
        token = create_access_token("user_004", "auditor", extra={"dept": "finance"})
        payload = decode_access_token(token)
        assert payload["dept"] == "finance"

    def test_invalid_token_raises_http_401(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("not.a.valid.token")
        assert exc_info.value.status_code == 401

    def test_tampered_token_raises_401(self):
        token = create_access_token("user_005", "auditor")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(tampered)
        assert exc_info.value.status_code == 401


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("securepassword123")
        assert verify_password("securepassword123", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correcthorse")
        assert verify_password("wrongpassword", hashed) is False

    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mypassword")
        assert "mypassword" not in hashed

    def test_same_password_different_hashes(self):
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2  # bcrypt uses random salt


class TestAESEncryption:
    def test_encrypt_decrypt_round_trip(self):
        plaintext = "swift:COBADEFFXXX:secret_credentials"
        encrypted = encrypt_credential(plaintext)
        assert encrypted != plaintext
        decrypted = decrypt_credential(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_base64(self):
        encrypted = encrypt_credential("test_credential")
        # Should be valid base64
        decoded = base64.b64decode(encrypted)
        assert len(decoded) > 12  # nonce(12) + ciphertext

    def test_different_nonces_each_call(self):
        # Two encryptions of same plaintext should differ (random nonce)
        e1 = encrypt_credential("same_text")
        e2 = encrypt_credential("same_text")
        assert e1 != e2

    def test_tampered_ciphertext_raises(self):
        encrypted = encrypt_credential("sensitive_data")
        raw = base64.b64decode(encrypted)
        # Flip a byte in the ciphertext region
        tampered_raw = raw[:12] + bytes([raw[12] ^ 0xFF]) + raw[13:]
        tampered = base64.b64encode(tampered_raw).decode()
        with pytest.raises(ValueError, match="decryption failed"):
            decrypt_credential(tampered)


# ═══════════════════════════════════════════════════════════════════════════════
# exceptions.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestExceptions:
    def test_base_exception_to_dict(self):
        exc = NexusTreasuryError("test message", detail={"key": "val"})
        d = exc.to_dict()
        assert d["message"] == "test message"
        assert d["detail"]["key"] == "val"
        assert "error_code" in d

    def test_duplicate_statement_error(self):
        ts = datetime(2024, 1, 15, 10, 30)
        exc = DuplicateStatementError("MSG-001", ts, "abc123hash")
        assert exc.message_id == "MSG-001"
        assert exc.http_status_code == 409
        d = exc.to_dict()
        assert d["detail"]["file_hash"] == "abc123hash"

    def test_sanctions_hit_error(self):
        exc = SanctionsHitError(
            payment_id="PAY-001",
            matched_field="beneficiary_name",
            matched_value="Bad Actor Corp",
            list_entry_name="BAD ACTOR CORP",
            list_type="OFAC_SDN",
            similarity_score=0.97,
        )
        assert exc.http_status_code == 403
        assert exc.matched_field == "beneficiary_name"

    def test_insufficient_funds_error(self):
        exc = InsufficientFundsError(
            available=Decimal("100.00"),
            requested=Decimal("5000.00"),
        )
        assert exc.http_status_code == 422
        d = exc.to_dict()
        assert "available" in str(d) or "requested" in str(d)

    def test_self_approval_error(self):
        exc = SelfApprovalError("user_001")
        assert exc.http_status_code == 403

    def test_invalid_state_transition(self):
        exc = InvalidStateTransitionError("DRAFT", "SETTLED")
        assert "DRAFT" in exc.message
        assert "SETTLED" in exc.message

    def test_permission_denied_error(self):
        exc = PermissionDeniedError("treasury_analyst", "WRITE", "approve_payment")
        assert exc.http_status_code == 403

    def test_payment_validation_error(self):
        errors = [{"field": "beneficiary_iban", "error": "Invalid checksum"}]
        exc = PaymentValidationError(errors)
        assert exc.http_status_code == 422

    def test_account_not_found(self):
        exc = AccountNotFoundError(iban="DE00INVALID")
        assert exc.http_status_code == 404

    def test_payment_not_found(self):
        exc = PaymentNotFoundError("PAY-UNKNOWN")
        assert exc.http_status_code == 404

    def test_unbalanced_journal_error(self):
        exc = UnbalancedJournalError(Decimal("1000"), Decimal("999"))
        assert exc.http_status_code in (400, 422)

    def test_transfer_pricing_violation(self):
        exc = TransferPricingViolationError(
            proposed_rate=Decimal("0.09"),
            base_rate=Decimal("0.04"),
            deviation_bps=500,
            max_allowed_bps=150,
        )
        assert exc.http_status_code in (400, 422)

    def test_expired_mandate_error(self):
        exc = ExpiredMandateError("MAND-001", date(2023, 12, 31))
        assert exc.http_status_code in (400, 422)

    def test_no_mandate_error(self):
        exc = NoMandateError("ACC-001")
        assert exc.http_status_code in (400, 404)

    def test_mandate_key_mismatch_error(self):
        exc = MandateKeyMismatchError("MAND-001", "fingerprint_a", "fingerprint_b")
        assert exc.http_status_code in (400, 403)

    def test_locked_period_error(self):
        exc = LockedPeriodError(
            value_date=date(2024, 1, 5),
            locked_until=date(2024, 1, 31),
        )
        assert exc.http_status_code in (400, 422)

    def test_invalid_business_day_convention(self):
        exc = InvalidBusinessDayConventionError("nonsense_convention")
        assert exc.http_status_code in (400, 422)
        assert "nonsense_convention" in exc.message

    def test_all_exceptions_are_subclass_of_base(self):
        exceptions = [
            DuplicateStatementError("x", datetime.now(), "h"),
            SelfApprovalError("u"),
            PermissionDeniedError("r", "a", "res"),
            PaymentNotFoundError("p"),
            AccountNotFoundError(iban="DE89370400440532013000"),
        ]
        for exc in exceptions:
            assert isinstance(exc, NexusTreasuryError)
