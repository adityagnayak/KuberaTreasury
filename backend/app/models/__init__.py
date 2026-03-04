"""SQLAlchemy 2.0 ORM models for all six Phase-2 domains.

All models extend the generic Base and enforce tenant_id on every table,
mirroring the Phase-1 + Phase-2 Alembic schema exactly.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
    Computed,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ─────────────────────────────────────────────────────────── helpers ──────────
def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ══════════════════════════════════════════════════════════════════════════════
# TENANT
# ══════════════════════════════════════════════════════════════════════════════
class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_number: Mapped[str | None] = mapped_column(String(20))
    utr: Mapped[str | None] = mapped_column(String(10))
    vrn: Mapped[str | None] = mapped_column(String(9))
    accounts_office_reference: Mapped[str | None] = mapped_column(String(13))
    base_currency: Mapped[str] = mapped_column(String(3), server_default="GBP")
    classification_level: Mapped[str] = mapped_column(String(40), server_default="OFFICIAL")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ══════════════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS (extended in Phase 2)
# ══════════════════════════════════════════════════════════════════════════════
class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    account_code: Mapped[str] = mapped_column(String(30), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    account_subtype: Mapped[str | None] = mapped_column(String(60))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    hmrc_nominal_code: Mapped[str | None] = mapped_column(String(10))
    vat_treatment: Mapped[str | None] = mapped_column(String(5))  # T0/T1/T2/T4/T7/T9
    is_treasury_account: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    allows_currency_revaluation: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.account_id"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("tenant_id", "account_code", name="uq_coa_account_code"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNTING PERIOD
# ══════════════════════════════════════════════════════════════════════════════
class AccountingPeriod(Base):
    __tablename__ = "accounting_periods"

    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    period_name: Mapped[str] = mapped_column(String(40), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # monthly/quarterly/annual
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="open")  # open/soft_closed/hard_closed
    ct_period_utr: Mapped[str | None] = mapped_column(String(10))
    ct600_due_date: Mapped[date | None] = mapped_column(Date)
    is_year_end: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_large_company_for_ct: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    qip_due_dates: Mapped[list[str] | None] = mapped_column(JSON)
    soft_closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    hard_closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    soft_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hard_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hard_close_reason: Mapped[str | None] = mapped_column(String(500))
    reopen_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    journals: Mapped[list[Journal]] = relationship("Journal", back_populates="period")

    __table_args__ = (
        CheckConstraint("period_start < period_end", name="ck_period_dates"),
        UniqueConstraint("tenant_id", "period_name", name="uq_period_name"),
        UniqueConstraint("tenant_id", "period_start", "period_end", name="uq_period_dates"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# JOURNAL
# ══════════════════════════════════════════════════════════════════════════════
class Journal(Base):
    __tablename__ = "journals"

    journal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_periods.period_id", ondelete="RESTRICT"),
        nullable=False,
    )
    journal_reference: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    journal_type: Mapped[str] = mapped_column(String(40), server_default="manual")
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    currency_code: Mapped[str] = mapped_column(String(3), server_default="GBP")
    reversal_of_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journals.journal_id", ondelete="SET NULL"),
    )
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_from_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    period: Mapped[AccountingPeriod] = relationship("AccountingPeriod", back_populates="journals")
    lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine", back_populates="journal", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "journal_reference", name="uq_journal_reference"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# JOURNAL LINE
# ══════════════════════════════════════════════════════════════════════════════
class JournalLine(Base):
    __tablename__ = "journal_lines"

    journal_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    journal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journals.journal_id", ondelete="CASCADE"), nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0")
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), server_default="0")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    vat_code: Mapped[str | None] = mapped_column(String(20))
    vat_treatment: Mapped[str | None] = mapped_column(String(5))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    line_order: Mapped[int] = mapped_column(Integer, server_default="0")

    journal: Mapped[Journal] = relationship("Journal", back_populates="lines")

    __table_args__ = (
        CheckConstraint(
            "(debit_amount >= 0 AND credit_amount >= 0 AND NOT (debit_amount > 0 AND credit_amount > 0))",
            name="ck_journal_line_dr_cr",
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# RECURRING JOURNAL TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════
class RecurringJournalTemplate(Base):
    __tablename__ = "recurring_journal_templates"

    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False,
    )
    template_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    frequency: Mapped[str] = mapped_column(String(20), server_default="monthly")
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_run_date: Mapped[date | None] = mapped_column(Date)
    template_lines: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("day_of_month BETWEEN 1 AND 28", name="ck_rjt_day_of_month"),
        UniqueConstraint("tenant_id", "template_name", name="uq_rjt_name"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# HMRC EXCHANGE RATES (already in Phase-1 schema, ORM mapping)
# ══════════════════════════════════════════════════════════════════════════════
class HmrcExchangeRate(Base):
    __tablename__ = "exchange_rates_hmrc"

    exchange_rate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    published_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "base_currency", "quote_currency", "published_date",
            name="uq_exchange_rates_unique",
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# CURRENCY REVALUATION (Phase-1 table, ORM mapping)
# ══════════════════════════════════════════════════════════════════════════════
class CurrencyRevaluation(Base):
    __tablename__ = "currency_revaluations"

    revaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"), nullable=False,
    )
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), server_default="GBP")
    hmrc_exchange_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exchange_rates_hmrc.exchange_rate_id", ondelete="RESTRICT"),
        nullable=True,
    )
    book_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    revalued_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    gain_loss: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("tenant_id", "period_end", "account_id", name="uq_currency_reval_period_account"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# HEDGE DESIGNATION (IFRS 9)
# ══════════════════════════════════════════════════════════════════════════════
class HedgeDesignation(Base):
    __tablename__ = "hedge_designations"

    hedge_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    hedge_reference: Mapped[str] = mapped_column(String(60), nullable=False)
    hedge_type: Mapped[str] = mapped_column(String(30), nullable=False)
    hedging_instrument_description: Mapped[str] = mapped_column(String(500), nullable=False)
    hedged_item_description: Mapped[str] = mapped_column(String(500), nullable=False)
    risk_component: Mapped[str] = mapped_column(String(120), nullable=False)
    hedge_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    designation_date: Mapped[date] = mapped_column(Date, nullable=False)
    prospective_method: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    de_designation_date: Mapped[date | None] = mapped_column(Date)
    de_designation_reason: Mapped[str | None] = mapped_column(String(500))
    cumulative_oci_treatment_on_dedesignation: Mapped[str | None] = mapped_column(String(255))
    tax_note: Mapped[str] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    effectiveness_tests: Mapped[list[HedgeEffectivenessTest]] = relationship(
        "HedgeEffectivenessTest", back_populates="hedge",
    )
    oci_reclassifications: Mapped[list[HedgeOciReclassification]] = relationship(
        "HedgeOciReclassification", back_populates="hedge",
    )

    __table_args__ = (
        CheckConstraint("hedge_ratio > 0 AND hedge_ratio <= 1", name="ck_hedge_ratio"),
        UniqueConstraint("tenant_id", "hedge_reference", name="uq_hedge_reference"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# HEDGE EFFECTIVENESS TEST
# ══════════════════════════════════════════════════════════════════════════════
class HedgeEffectivenessTest(Base):
    __tablename__ = "hedge_effectiveness_tests"

    test_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    hedge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hedge_designations.hedge_id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_periods.period_id", ondelete="RESTRICT"),
        nullable=False,
    )
    test_type: Mapped[str] = mapped_column(String(20), nullable=False)  # prospective/retrospective
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    instrument_fair_value_change: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    hedged_item_fair_value_change: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    effectiveness_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text)
    tested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    hedge: Mapped[HedgeDesignation] = relationship("HedgeDesignation", back_populates="effectiveness_tests")

    __table_args__ = (
        UniqueConstraint("tenant_id", "hedge_id", "period_id", "test_type", name="uq_hedge_test"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# HEDGE OCI RECLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════
class HedgeOciReclassification(Base):
    __tablename__ = "hedge_oci_reclassifications"

    oci_reclassification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    hedge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hedge_designations.hedge_id", ondelete="RESTRICT"),
        nullable=False,
    )
    journal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journals.journal_id", ondelete="RESTRICT"), nullable=False,
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_periods.period_id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_reclassified: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    trigger_description: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    hedge: Mapped[HedgeDesignation] = relationship("HedgeDesignation", back_populates="oci_reclassifications")


# ══════════════════════════════════════════════════════════════════════════════
# INTERCOMPANY TRANSACTION (Phase-1, ORM mapping)
# ══════════════════════════════════════════════════════════════════════════════
class IntercompanyTransaction(Base):
    __tablename__ = "intercompany_transactions"

    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    counterparty_entity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    counterparty_entity_id: Mapped[str] = mapped_column(String(60), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), server_default="GBP")
    contracted_rate_bps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    benchmark_rate_bps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    rate_variance_bps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    tp_flag_raised: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    tp_justification: Mapped[str | None] = mapped_column(Text)
    is_matched: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    matched_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


# ══════════════════════════════════════════════════════════════════════════════
# CORPORATE INTEREST RESTRICTION (Phase-1, ORM mapping)
# ══════════════════════════════════════════════════════════════════════════════
class CorporateInterestRestriction(Base):
    __tablename__ = "corporate_interest_restrictions"

    restriction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    gross_interest_expense: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    gross_interest_income: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    net_interest_expense: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    alert_triggered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    hard_flag_triggered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    restricted_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
