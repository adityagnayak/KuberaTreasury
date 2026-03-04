from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import reset_tenant_context, set_tenant_context
from app.models import User


@pytest.mark.asyncio
async def test_cross_tenant_read_isolation(db) -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    user_a = User(tenant_id=tenant_a, username="a@tenant.test", password_hash="x")
    user_b = User(tenant_id=tenant_b, username="b@tenant.test", password_hash="x")
    db.add_all([user_a, user_b])
    await db.flush()

    token = set_tenant_context(tenant_a)
    try:
        rows = (await db.execute(select(User))).scalars().all()
    finally:
        reset_tenant_context(token)

    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_a
