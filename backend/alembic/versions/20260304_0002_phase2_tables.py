"""Phase 2 — operational tables

Revision ID: 20260304_0002
Revises: 20260304_0001
Create Date: 2026-03-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260304_0002"
down_revision = "20260304_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---- new enums ----
    vat_treatment_enum = postgresql.ENUM(
        "T0",
        "T1",
        "T2",
        "T4",
        "T7",
        "T9",
        name="vat_treatment_code",
        create_type=False,
    )
    account_subtype_enum = postgresql.ENUM(
        "current_asset",
        "non_current_asset",
        "current_liability",
        "non_current_liability",
        "equity",
        "share_capital",
        "retained_earnings",
        "revenue",
        "cost_of_sales",
        "operating_expense",
        "finance_income",
        "finance_expense",
        "fx_revaluation_reserve",
        "hedging_reserve_oci",
        "intercompany_loan",
        "cash_pool",
        "cir_adjustment",
        "interest_payable",
        "interest_receivable",
        "tax_payable",
        name="account_subtype",
        create_type=False,
    )
    period_status_enum = postgresql.ENUM(
        "open",
        "soft_closed",
        "hard_closed",
        name="period_status",
        create_type=False,
    )
    period_type_enum = postgresql.ENUM(
        "monthly",
        "quarterly",
        "annual",
        name="period_type",
        create_type=False,
    )
    journal_status_enum = postgresql.ENUM(
        "draft",
        "posted",
        "reversed",
        name="journal_status",
        create_type=False,
    )
    journal_type_enum = postgresql.ENUM(
        "manual",
        "auto_vat",
        "auto_reversal",
        "auto_revaluation",
        "auto_oci_reclassification",
        "recurring",
        "year_end_rollover",
        name="journal_type",
        create_type=False,
    )
    hedge_type_enum = postgresql.ENUM(
        "fair_value",
        "cash_flow",
        "net_investment",
        name="hedge_type",
        create_type=False,
    )
    effectiveness_method_enum = postgresql.ENUM(
        "dollar_offset",
        "regression",
        name="effectiveness_method",
        create_type=False,
    )
    for e in [
        vat_treatment_enum,
        account_subtype_enum,
        period_status_enum,
        period_type_enum,
        journal_status_enum,
        journal_type_enum,
        hedge_type_enum,
        effectiveness_method_enum,
    ]:
        e.create(bind, checkfirst=True)

    # ---- extend chart_of_accounts ----
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "hmrc_nominal_code",
            sa.String(10),
            nullable=True,
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "vat_treatment",
            postgresql.ENUM(
                "T0",
                "T1",
                "T2",
                "T4",
                "T7",
                "T9",
                name="vat_treatment_code",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "account_subtype",
            postgresql.ENUM(name="account_subtype", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "is_treasury_account",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "allows_currency_revaluation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "parent_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_coa_parent",
        "chart_of_accounts",
        "chart_of_accounts",
        ["parent_account_id"],
        ["account_id"],
    )

    # ---- accounting_periods ----
    op.create_table(
        "accounting_periods",
        sa.Column(
            "period_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("period_name", sa.String(40), nullable=False),
        sa.Column(
            "period_type",
            postgresql.ENUM(name="period_type", create_type=False),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="period_status", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("ct_period_utr", sa.String(10), nullable=True),
        sa.Column("ct600_due_date", sa.Date(), nullable=True),
        sa.Column(
            "soft_closed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "hard_closed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("soft_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hard_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("period_start < period_end", name="ck_period_dates"),
        sa.UniqueConstraint("tenant_id", "period_name", name="uq_period_name"),
        sa.UniqueConstraint(
            "tenant_id", "period_start", "period_end", name="uq_period_dates"
        ),
    )
    op.create_index(
        "ix_accounting_periods_tenant_start",
        "accounting_periods",
        ["tenant_id", "period_start"],
    )

    # ---- journals ----
    op.create_table(
        "journals",
        sa.Column(
            "journal_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "period_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounting_periods.period_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("journal_reference", sa.String(60), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "journal_type",
            postgresql.ENUM(name="journal_type", create_type=False),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="journal_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="GBP"),
        sa.Column(
            "reversal_of_journal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journals.journal_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "posted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_from_ip", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "journal_reference", name="uq_journal_reference"
        ),
    )
    op.create_index("ix_journals_tenant_period", "journals", ["tenant_id", "period_id"])
    op.create_index("ix_journals_tenant_status", "journals", ["tenant_id", "status"])

    # immutability trigger on journals
    op.execute("""
        CREATE TRIGGER trg_journals_immutable
        BEFORE UPDATE ON journals
        FOR EACH ROW
        WHEN (OLD.status = 'posted')
        EXECUTE FUNCTION prevent_update_delete();
        """)

    # ---- journal_lines ----
    op.create_table(
        "journal_lines",
        sa.Column(
            "journal_line_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "journal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journals.journal_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "debit_amount", sa.Numeric(20, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "credit_amount", sa.Numeric(20, 4), nullable=False, server_default="0"
        ),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "vat_code",
            postgresql.ENUM(
                "standard",
                "reduced",
                "zero",
                "exempt",
                "outside_scope",
                name="vat_code",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "vat_treatment",
            postgresql.ENUM(
                "T0",
                "T1",
                "T2",
                "T4",
                "T7",
                "T9",
                name="vat_treatment_code",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("vat_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("line_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "(debit_amount >= 0 AND credit_amount >= 0 AND NOT (debit_amount > 0 AND credit_amount > 0))",
            name="ck_journal_line_dr_cr",
        ),
    )
    op.create_index(
        "ix_journal_lines_journal", "journal_lines", ["tenant_id", "journal_id"]
    )
    op.create_index(
        "ix_journal_lines_account", "journal_lines", ["tenant_id", "account_id"]
    )

    # ---- recurring_journal_templates ----
    op.create_table(
        "recurring_journal_templates",
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("last_run_date", sa.Date(), nullable=True),
        sa.Column(
            "template_lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("day_of_month BETWEEN 1 AND 28", name="ck_rjt_day_of_month"),
        sa.UniqueConstraint("tenant_id", "template_name", name="uq_rjt_name"),
    )

    # ---- hedge_designations ----
    op.create_table(
        "hedge_designations",
        sa.Column(
            "hedge_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("hedge_reference", sa.String(60), nullable=False),
        sa.Column(
            "hedge_type",
            postgresql.ENUM(name="hedge_type", create_type=False),
            nullable=False,
        ),
        sa.Column("hedging_instrument_description", sa.String(500), nullable=False),
        sa.Column("hedged_item_description", sa.String(500), nullable=False),
        sa.Column("risk_component", sa.String(120), nullable=False),
        sa.Column("hedge_ratio", sa.Numeric(8, 6), nullable=False),
        sa.Column("designation_date", sa.Date(), nullable=False),
        sa.Column(
            "prospective_method",
            postgresql.ENUM(name="effectiveness_method", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("de_designation_date", sa.Date(), nullable=True),
        sa.Column("de_designation_reason", sa.String(500), nullable=True),
        sa.Column(
            "cumulative_oci_treatment_on_dedesignation", sa.String(255), nullable=True
        ),
        sa.Column(
            "tax_note",
            sa.String(500),
            nullable=False,
            server_default="Hedge accounting treatment does not alter the corporation "
            "tax position. Tax follows the underlying transaction.",
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "hedge_ratio > 0 AND hedge_ratio <= 1", name="ck_hedge_ratio"
        ),
        sa.UniqueConstraint("tenant_id", "hedge_reference", name="uq_hedge_reference"),
    )

    # ---- hedge_effectiveness_tests ----
    op.create_table(
        "hedge_effectiveness_tests",
        sa.Column(
            "test_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "hedge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hedge_designations.hedge_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "period_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounting_periods.period_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("test_type", sa.String(20), nullable=False),
        sa.Column(
            "method",
            postgresql.ENUM(name="effectiveness_method", create_type=False),
            nullable=False,
        ),
        sa.Column("instrument_fair_value_change", sa.Numeric(20, 4), nullable=False),
        sa.Column("hedged_item_fair_value_change", sa.Numeric(20, 4), nullable=False),
        sa.Column("effectiveness_ratio", sa.Numeric(10, 6), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column(
            "tested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "tested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "hedge_id", "period_id", "test_type", name="uq_hedge_test"
        ),
    )
    # effectiveness test results are immutable
    op.execute("""
        CREATE TRIGGER trg_hedge_effectiveness_tests_immutable
        BEFORE UPDATE OR DELETE ON hedge_effectiveness_tests
        FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
        """)

    # ---- hedge_oci_reclassifications ----
    op.create_table(
        "hedge_oci_reclassifications",
        sa.Column(
            "oci_reclassification_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "hedge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hedge_designations.hedge_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "journal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journals.journal_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "period_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounting_periods.period_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_reclassified", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("trigger_description", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_hedge_effectiveness_tests_immutable ON hedge_effectiveness_tests;"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_journals_immutable ON journals;")

    op.drop_table("hedge_oci_reclassifications")
    op.drop_table("hedge_effectiveness_tests")
    op.drop_table("hedge_designations")
    op.drop_table("recurring_journal_templates")
    op.drop_index("ix_journal_lines_account", table_name="journal_lines")
    op.drop_index("ix_journal_lines_journal", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journals_tenant_status", table_name="journals")
    op.drop_index("ix_journals_tenant_period", table_name="journals")
    op.drop_table("journals")
    op.drop_index("ix_accounting_periods_tenant_start", table_name="accounting_periods")
    op.drop_table("accounting_periods")

    op.drop_constraint("fk_coa_parent", "chart_of_accounts", type_="foreignkey")
    for col in [
        "hmrc_nominal_code",
        "vat_treatment",
        "account_subtype",
        "is_treasury_account",
        "allows_currency_revaluation",
        "parent_account_id",
    ]:
        op.drop_column("chart_of_accounts", col)

    bind = op.get_bind()
    for name in [
        "effectiveness_method",
        "hedge_type",
        "journal_type",
        "journal_status",
        "period_type",
        "period_status",
        "account_subtype",
        "vat_treatment_code",
    ]:
        sa.Enum(name=name).drop(bind, checkfirst=True)
