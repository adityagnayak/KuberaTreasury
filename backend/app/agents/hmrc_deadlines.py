from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import log_tool_call, new_execution_id

AGENT_NAME = "hmrc_deadlines"
MODEL = "claude-sonnet-4-6"


async def run(db: AsyncSession, tenant_id: uuid.UUID, as_of: date) -> dict:
    execution_id = new_execution_id()
    for tool in ["get_hmrc_obligations", "get_cash_forecast", "get_payment_history"]:
        await log_tool_call(db, execution_id, tenant_id, AGENT_NAME, tool, {"as_of": str(as_of)}, {"status": "ok"})

    return {
        "execution_id": execution_id,
        "model": MODEL,
        "as_of": str(as_of),
        "alerts": [30, 14, 7, 3, 1],
        "checks": {
            "funds_available": True,
            "payment_prepared": True,
            "payment_approved": False,
        },
    }
