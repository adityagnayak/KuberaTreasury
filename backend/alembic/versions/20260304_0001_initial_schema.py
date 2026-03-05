"""initial kubera treasury schema

Revision ID: 20260304_0001
Revises:
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260304_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    classification_enum = postgresql.ENUM(
        "PUBLIC", "OFFICIAL", name="classification_level", create_type=False
    )
    role_enum = postgresql.ENUM(
        "system_admin",
        "cfo",
        "head_of_treasury",
        "treasury_manager",
        "treasury_analyst",
        "auditor",
        "compliance_officer",
        "board_member",
        name="role_name",
        create_type=False,
    )
    permission_effect_enum = postgresql.ENUM(
        "allow", "deny", name="permission_effect", create_type=False
    )
    vat_code_enum = postgresql.ENUM(
        "standard",
        "reduced",
        "zero",
        "exempt",
        "outside_scope",
        name="vat_code",
        create_type=False,
    )
    hmrc_tax_type_enum = postgresql.ENUM(
        "CT", "VAT", "PAYE", "CIS", name="hmrc_tax_type", create_type=False
    )
    hmrc_obligation_status_enum = postgresql.ENUM(
        "open", "fulfilled", "overdue", name="hmrc_obligation_status", create_type=False
    )
    payment_status_enum = postgresql.ENUM(
        "draft",
        "pending_approval",
        "approved",
        "rejected",
        "exported_pain001",
        name="payment_status",
        create_type=False,
    )
    payment_channel_enum = postgresql.ENUM(
        "manual_pain001", name="payment_channel", create_type=False
    )
    auth_factor_type_enum = postgresql.ENUM(
        "totp", name="auth_factor_type", create_type=False
    )

    bind = op.get_bind()
    classification_enum.create(bind, checkfirst=True)
    role_enum.create(bind, checkfirst=True)
    permission_effect_enum.create(bind, checkfirst=True)
    vat_code_enum.create(bind, checkfirst=True)
    hmrc_tax_type_enum.create(bind, checkfirst=True)
    hmrc_obligation_status_enum.create(bind, checkfirst=True)
    payment_status_enum.create(bind, checkfirst=True)
    payment_channel_enum.create(bind, checkfirst=True)
    auth_factor_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_name", sa.String(length=255), nullable=False),
        sa.Column("company_number", sa.String(length=20), nullable=True),
        sa.Column("utr", sa.String(length=10), nullable=True),
        sa.Column("vrn", sa.String(length=9), nullable=True),
        sa.Column("accounts_office_reference", sa.String(length=13), nullable=True),
        sa.Column(
            "base_currency", sa.String(length=3), nullable=False, server_default="GBP"
        ),
        sa.Column(
            "classification_level",
            classification_enum,
            nullable=False,
            server_default="OFFICIAL",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("char_length(utr) = 10", name="ck_tenants_utr_len"),
        sa.CheckConstraint("char_length(vrn) = 9", name="ck_tenants_vrn_len"),
        sa.CheckConstraint(
            "char_length(accounts_office_reference) = 13", name="ck_tenants_aor_len"
        ),
        sa.UniqueConstraint("tenant_name", name="uq_tenants_name"),
    )

    op.create_table(
        "users",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
    )

    op.create_table(
        "personal_data_records",
        sa.Column(
            "personal_data_id",
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
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("address_line_1", sa.String(length=255), nullable=True),
        sa.Column("address_line_2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("postcode", sa.String(length=20), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_pdr_tenant_subject", "tenant_id", "subject_type"),
    )

    op.create_table(
        "roles",
        sa.Column(
            "role_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role_name", role_enum, nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("tenant_id", "role_name", name="uq_roles_tenant_role_name"),
    )

    op.create_table(
        "permissions",
        sa.Column(
            "permission_id",
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
        sa.Column("permission_key", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "permission_key", name="uq_permissions_tenant_key"
        ),
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "user_role_id",
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
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.role_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "role_id", name="uq_user_roles_unique"
        ),
    )

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_permission_id",
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
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.role_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("permissions.permission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effect", permission_effect_enum, nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "role_id", "permission_id", name="uq_role_permission_unique"
        ),
    )

    op.create_table(
        "auth_factors",
        sa.Column(
            "auth_factor_id",
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
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("factor_type", auth_factor_type_enum, nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "ip_allowlist_entries",
        sa.Column(
            "ip_allowlist_id",
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
        sa.Column("cidr", sa.String(length=50), nullable=False),
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
        sa.UniqueConstraint("tenant_id", "cidr", name="uq_ip_allowlist_tenant_cidr"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column(
            "session_id",
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
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jwt_id", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "jwt_id", name="uq_auth_sessions_tenant_jwt_id"
        ),
    )

    op.create_table(
        "counterparties",
        sa.Column(
            "counterparty_id",
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
        sa.Column("counterparty_code", sa.String(length=40), nullable=False),
        sa.Column("counterparty_type", sa.String(length=30), nullable=False),
        sa.Column("personal_data_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_intercompany",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "counterparty_code", name="uq_counterparty_code"
        ),
    )

    op.create_table(
        "bank_accounts",
        sa.Column(
            "bank_account_id",
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
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("sort_code", sa.String(length=6), nullable=True),
        sa.Column("account_number", sa.String(length=8), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "iban", name="uq_bank_account_iban"),
    )

    op.create_table(
        "chart_of_accounts",
        sa.Column(
            "account_id",
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
        sa.Column("account_code", sa.String(length=30), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.UniqueConstraint("tenant_id", "account_code", name="uq_coa_account_code"),
    )

    op.create_table(
        "ledger_events",
        sa.Column(
            "event_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("counterparties.counterparty_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vat_code", vat_code_enum, nullable=False),
        sa.Column("vat_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("source_reference", sa.String(length=120), nullable=True),
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
        sa.CheckConstraint("amount <> 0", name="ck_ledger_events_amount_nonzero"),
        sa.UniqueConstraint(
            "tenant_id", "event_sequence", name="uq_ledger_events_sequence"
        ),
    )
    op.create_index(
        "ix_ledger_events_tenant_effective",
        "ledger_events",
        ["tenant_id", "effective_at"],
    )
    op.create_index(
        "ix_ledger_events_tenant_vat_code", "ledger_events", ["tenant_id", "vat_code"]
    )

    op.create_table(
        "ledger_positions",
        sa.Column(
            "position_id",
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
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balance", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "account_id", "as_of", name="uq_ledger_position_snapshot"
        ),
    )

    op.create_table(
        "exchange_rates_hmrc",
        sa.Column(
            "exchange_rate_id",
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
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "base_currency",
            "quote_currency",
            "published_date",
            name="uq_exchange_rates_unique",
        ),
    )

    op.create_table(
        "currency_revaluations",
        sa.Column(
            "revaluation_id",
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
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_currency", sa.String(length=3), nullable=False),
        sa.Column(
            "to_currency", sa.String(length=3), nullable=False, server_default="GBP"
        ),
        sa.Column(
            "hmrc_exchange_rate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exchange_rates_hmrc.exchange_rate_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("book_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("revalued_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("gain_loss", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "period_end",
            "account_id",
            name="uq_currency_reval_period_account",
        ),
    )

    op.create_table(
        "payment_policies",
        sa.Column(
            "payment_policy_id",
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
        sa.Column("policy_name", sa.String(length=120), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("threshold_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "required_approvals", sa.Integer(), nullable=False, server_default="2"
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.UniqueConstraint(
            "tenant_id", "policy_name", "currency_code", name="uq_payment_policy"
        ),
        sa.CheckConstraint(
            "required_approvals >= 2", name="ck_payment_policy_four_eyes_min"
        ),
    )

    op.create_table(
        "payment_batches",
        sa.Column(
            "payment_batch_id",
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
        sa.Column("batch_reference", sa.String(length=60), nullable=False),
        sa.Column("execution_date", sa.Date(), nullable=False),
        sa.Column(
            "channel",
            payment_channel_enum,
            nullable=False,
            server_default="manual_pain001",
        ),
        sa.Column(
            "status", payment_status_enum, nullable=False, server_default="draft"
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
        sa.UniqueConstraint(
            "tenant_id", "batch_reference", name="uq_payment_batch_reference"
        ),
    )

    op.create_table(
        "payment_instructions",
        sa.Column(
            "payment_instruction_id",
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
            "payment_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_batches.payment_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("counterparties.counterparty_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "debit_bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.bank_account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("purpose_code", sa.String(length=20), nullable=True),
        sa.Column("remittance_information", sa.String(length=140), nullable=True),
        sa.Column(
            "status", payment_status_enum, nullable=False, server_default="draft"
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
        sa.CheckConstraint("amount > 0", name="ck_payment_instruction_positive_amount"),
    )

    op.create_table(
        "payment_approvals",
        sa.Column(
            "payment_approval_id",
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
            "payment_instruction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "payment_instructions.payment_instruction_id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "approver_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("decision_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "payment_instruction_id",
            "approver_user_id",
            name="uq_payment_approver_once",
        ),
    )

    op.create_table(
        "pain001_exports",
        sa.Column(
            "pain001_export_id",
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
            "payment_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_batches.payment_batch_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("sha256_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "exported_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "exported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("upload_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "file_name", name="uq_pain001_file_name"),
    )

    op.create_table(
        "tax_profiles",
        sa.Column(
            "tax_profile_id",
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
            "is_large_company_for_ct",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "ct_due_rule",
            sa.String(length=40),
            nullable=False,
            server_default="9_months_post_year_end",
        ),
        sa.Column(
            "cir_threshold_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="2000000.00",
        ),
        sa.Column("vat_stagger", sa.String(length=2), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", name="uq_tax_profile_tenant"),
    )

    op.create_table(
        "hmrc_obligations",
        sa.Column(
            "hmrc_obligation_id",
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
        sa.Column("tax_type", hmrc_tax_type_enum, nullable=False),
        sa.Column("period_key", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status", hmrc_obligation_status_enum, nullable=False, server_default="open"
        ),
        sa.Column(
            "source", sa.String(length=20), nullable=False, server_default="hmrc_api_v1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "tax_type", "period_key", name="uq_hmrc_obligation_period"
        ),
    )

    op.create_table(
        "hmrc_api_submissions",
        sa.Column(
            "hmrc_submission_id",
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
        sa.Column("tax_type", hmrc_tax_type_enum, nullable=False),
        sa.Column(
            "api_version", sa.String(length=10), nullable=False, server_default="v1.0"
        ),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("request_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_correlation_id", sa.String(length=120), nullable=True),
        sa.Column(
            "submitted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Index(
            "ix_hmrc_submission_tenant_tax_time",
            "tenant_id",
            "tax_type",
            "submitted_at",
        ),
    )

    op.create_table(
        "tax_payment_references",
        sa.Column(
            "tax_payment_reference_id",
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
        sa.Column("tax_type", hmrc_tax_type_enum, nullable=False),
        sa.Column("reference_value", sa.String(length=30), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(tax_type = 'CT' AND reference_value ~ '^[0-9]{10}A001$')"
            " OR (tax_type = 'VAT' AND reference_value ~ '^[0-9]{9}$')"
            " OR (tax_type = 'PAYE' AND char_length(reference_value) = 13)"
            " OR (tax_type = 'CIS' AND reference_value ~ '^[0-9]{10}[A-Z0-9]{0,20}$')",
            name="ck_tax_payment_reference_format",
        ),
    )

    op.create_table(
        "paye_calendar_entries",
        sa.Column(
            "paye_calendar_entry_id",
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
        sa.Column("tax_month", sa.Integer(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("due_date_non_electronic", sa.Date(), nullable=False),
        sa.Column("due_date_electronic", sa.Date(), nullable=False),
        sa.Column("forecast_entry_reference", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("tax_month BETWEEN 1 AND 12", name="ck_paye_tax_month"),
        sa.UniqueConstraint(
            "tenant_id", "tax_month", "tax_year", name="uq_paye_calendar_month_year"
        ),
    )

    op.create_table(
        "corporate_interest_restrictions",
        sa.Column(
            "cir_record_id",
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
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("net_group_interest", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "threshold", sa.Numeric(20, 2), nullable=False, server_default="2000000.00"
        ),
        sa.Column(
            "is_above_threshold",
            sa.Boolean(),
            sa.Computed("net_group_interest > threshold"),
            nullable=False,
        ),
        sa.Column(
            "review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "period_start", "period_end", name="uq_cir_period"
        ),
    )

    op.create_table(
        "intercompany_transactions",
        sa.Column(
            "intercompany_transaction_id",
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
            "source_ledger_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_events.event_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("counterparties.counterparty_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tp_document_uri", sa.String(length=500), nullable=True),
        sa.Column("tp_document_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "tp_document_hash IS NULL OR char_length(tp_document_hash)=64",
            name="ck_tp_doc_hash_len",
        ),
    )

    op.create_table(
        "forecast_cashflows",
        sa.Column(
            "forecast_cashflow_id",
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
        sa.Column("flow_date", sa.Date(), nullable=False),
        sa.Column("flow_type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("related_tax_type", hmrc_tax_type_enum, nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Index("ix_forecast_tenant_flow_date", "tenant_id", "flow_date"),
    )

    op.create_table(
        "contracts",
        sa.Column(
            "contract_id",
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
        sa.Column("contract_reference", sa.String(length=60), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column(
            "is_mod_contract",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "classification_level",
            classification_enum,
            nullable=False,
            server_default="OFFICIAL",
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "contract_reference", name="uq_contract_reference"
        ),
    )

    op.create_table(
        "record_retention_policies",
        sa.Column(
            "retention_policy_id",
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
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column("retention_years", sa.Integer(), nullable=False),
        sa.Column("legal_basis", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "retention_years IN (7, 10)", name="ck_retention_years_allowed"
        ),
        sa.UniqueConstraint(
            "tenant_id", "record_type", name="uq_retention_record_type"
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column(
            "audit_event_id",
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
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("before_state_hash", sa.String(length=64), nullable=True),
        sa.Column("after_state_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
    )

    op.create_table(
        "audit_export_jobs",
        sa.Column(
            "audit_export_job_id",
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
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pdf_file_name", sa.String(length=255), nullable=True),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("digital_signature", sa.Text(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "ai_inference_logs",
        sa.Column(
            "ai_inference_log_id",
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
        sa.Column("request_ref", sa.String(length=120), nullable=False),
        sa.Column(
            "model_name",
            sa.String(length=80),
            nullable=False,
            server_default="claude-sonnet-4-6",
        ),
        sa.Column(
            "input_reference_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "output_reference_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "contains_pii",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.CheckConstraint("contains_pii = false", name="ck_ai_inference_no_pii"),
        sa.UniqueConstraint("tenant_id", "request_ref", name="uq_ai_request_ref"),
    )

    op.create_table(
        "outbox_events",
        sa.Column(
            "outbox_event_id",
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
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_outbox_unprocessed", "tenant_id", "processed_at"),
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_update_delete() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Immutable table: operation % not permitted on %', TG_OP, TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """)

    for table_name in [
        "ledger_events",
        "audit_events",
        "hmrc_api_submissions",
        "ai_inference_logs",
    ]:
        op.execute(f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
            """)

    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_payment_four_eyes() RETURNS TRIGGER AS $$
        DECLARE
            creator_id uuid;
            approval_count integer;
        BEGIN
            SELECT created_by_user_id INTO creator_id
            FROM payment_instructions
            WHERE payment_instruction_id = NEW.payment_instruction_id;

            IF creator_id = NEW.approver_user_id THEN
                RAISE EXCEPTION 'Payment creator cannot approve own payment (segregation of duties)';
            END IF;

            SELECT COUNT(*) INTO approval_count
            FROM payment_approvals
            WHERE payment_instruction_id = NEW.payment_instruction_id
              AND decision = 'approved';

            IF approval_count >= 2 THEN
                RAISE EXCEPTION 'Four-eyes approval already satisfied; additional approval not required';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)

    op.execute("""
        CREATE TRIGGER trg_payment_approval_four_eyes
        BEFORE INSERT ON payment_approvals
        FOR EACH ROW EXECUTE FUNCTION enforce_payment_four_eyes();
        """)


def downgrade() -> None:
    for table_name in [
        "ledger_events",
        "audit_events",
        "hmrc_api_submissions",
        "ai_inference_logs",
    ]:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name};"
        )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_payment_approval_four_eyes ON payment_approvals;"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_payment_four_eyes;")
    op.execute("DROP FUNCTION IF EXISTS prevent_update_delete;")

    op.drop_table("outbox_events")
    op.drop_table("ai_inference_logs")
    op.drop_table("audit_export_jobs")
    op.drop_table("audit_events")
    op.drop_table("record_retention_policies")
    op.drop_table("contracts")
    op.drop_table("forecast_cashflows")
    op.drop_table("intercompany_transactions")
    op.drop_table("corporate_interest_restrictions")
    op.drop_table("paye_calendar_entries")
    op.drop_table("tax_payment_references")
    op.drop_table("hmrc_api_submissions")
    op.drop_table("hmrc_obligations")
    op.drop_table("tax_profiles")
    op.drop_table("pain001_exports")
    op.drop_table("payment_approvals")
    op.drop_table("payment_instructions")
    op.drop_table("payment_batches")
    op.drop_table("payment_policies")
    op.drop_table("currency_revaluations")
    op.drop_table("exchange_rates_hmrc")
    op.drop_table("ledger_positions")
    op.drop_index("ix_ledger_events_tenant_vat_code", table_name="ledger_events")
    op.drop_index("ix_ledger_events_tenant_effective", table_name="ledger_events")
    op.drop_table("ledger_events")
    op.drop_table("chart_of_accounts")
    op.drop_table("bank_accounts")
    op.drop_table("counterparties")
    op.drop_table("auth_sessions")
    op.drop_table("ip_allowlist_entries")
    op.drop_table("auth_factors")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("personal_data_records")
    op.drop_table("users")
    op.drop_table("tenants")

    bind = op.get_bind()
    for enum_name in [
        "auth_factor_type",
        "payment_channel",
        "payment_status",
        "hmrc_obligation_status",
        "hmrc_tax_type",
        "vat_code",
        "permission_effect",
        "role_name",
        "classification_level",
    ]:
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
