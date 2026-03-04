from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.agents import daily_briefing, hmrc_deadlines, payment_prep, variance_alert
from app.models import AgentExecutionLog


@pytest.mark.asyncio
async def test_agents_log_execution(db, tenant):
    payload_a = await daily_briefing.run(db, tenant.tenant_id, date.today())
    payload_b = await payment_prep.run(db, tenant.tenant_id, "10:00_CHAPS")
    payload_c = await variance_alert.run(db, tenant.tenant_id)
    payload_d = await hmrc_deadlines.run(db, tenant.tenant_id, date.today())
    await db.flush()

    logs = (await db.execute(select(AgentExecutionLog))).scalars().all()

    assert payload_a["execution_id"]
    assert payload_b["execution_id"]
    assert payload_c["execution_id"]
    assert payload_d["execution_id"]
    assert len(logs) >= 4
