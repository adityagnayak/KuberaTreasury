"""add missing auth runtime tables

Revision ID: 20260305_0004
Revises: 20260304_0003
Create Date: 2026-03-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260305_0004"
down_revision = "20260304_0003"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)


def upgrade() -> None:
    if not _has_table("tenant_security_settings"):
        op.create_table(
            "tenant_security_settings",
            sa.Column(
                "tenant_security_settings_id",
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
                "mfa_required_for_all_users",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "concurrent_session_limit",
                sa.Integer(),
                nullable=False,
                server_default="3",
            ),
            sa.Column(
                "inactivity_timeout_minutes",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "ip_allowlist_enforced",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.UniqueConstraint("tenant_id", name="uq_tenant_security_settings_tenant"),
        )

    if not _has_table("password_history"):
        op.create_table(
            "password_history",
            sa.Column(
                "password_history_id",
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
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not _has_table("login_attempts"):
        op.create_table(
            "login_attempts",
            sa.Column(
                "login_attempt_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("username", sa.String(length=150), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("succeeded", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_login_attempts_tenant_username_window",
            "login_attempts",
            ["tenant_id", "username", "succeeded", "created_at"],
        )

    if not _has_table("mfa_backup_codes"):
        op.create_table(
            "mfa_backup_codes",
            sa.Column(
                "backup_code_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_mfa_backup_codes_lookup",
            "mfa_backup_codes",
            ["tenant_id", "user_id", "code_hash", "used_at"],
        )

    if not _has_table("security_events"):
        op.create_table(
            "security_events",
            sa.Column(
                "security_event_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )


def downgrade() -> None:
    if _has_table("security_events"):
        op.drop_table("security_events")

    if _has_table("mfa_backup_codes"):
        op.drop_index("ix_mfa_backup_codes_lookup", table_name="mfa_backup_codes")
        op.drop_table("mfa_backup_codes")

    if _has_table("login_attempts"):
        op.drop_index(
            "ix_login_attempts_tenant_username_window", table_name="login_attempts"
        )
        op.drop_table("login_attempts")

    if _has_table("password_history"):
        op.drop_table("password_history")

    if _has_table("tenant_security_settings"):
        op.drop_table("tenant_security_settings")
