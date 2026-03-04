"""phase 4 payment controls hardening

Revision ID: 20260304_0003
Revises: 20260304_0002
Create Date: 2026-03-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260304_0003"
down_revision = "20260304_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_approvals",
        sa.Column("initiator_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.execute("""
        UPDATE payment_approvals pa
        SET initiator_user_id = pi.created_by_user_id
        FROM payment_instructions pi
        WHERE pa.payment_instruction_id = pi.payment_instruction_id
        """)

    op.alter_column("payment_approvals", "initiator_user_id", nullable=False)

    op.create_check_constraint(
        "ck_payment_approvals_initiator_not_approver",
        "payment_approvals",
        "initiator_user_id <> approver_user_id",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payment_approvals_initiator_not_approver",
        "payment_approvals",
        type_="check",
    )
    op.drop_column("payment_approvals", "initiator_user_id")
