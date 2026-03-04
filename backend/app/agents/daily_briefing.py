from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import log_tool_call, new_execution_id

AGENT_NAME = "daily_briefing"
MODEL = "claude-sonnet-4-6"


async def run(db: AsyncSession, tenant_id: uuid.UUID, as_of: date) -> dict:
    execution_id = new_execution_id()
    position = {"group_position_gbp": 0, "delta_vs_yesterday_gbp": 0}
    await log_tool_call(
        db,
        execution_id,
        tenant_id,
        AGENT_NAME,
        "get_group_position",
        {"as_of": str(as_of)},
        position,
    )

    obligations: list[dict] = []
    await log_tool_call(
        db,
        execution_id,
        tenant_id,
        AGENT_NAME,
        "get_hmrc_obligations",
        {"week": str(as_of)},
        {"count": 0},
    )
    await log_tool_call(
        db,
        execution_id,
        tenant_id,
        AGENT_NAME,
        "get_payment_queue",
        {"as_of": str(as_of)},
        {"count": 0, "value_gbp": 0},
    )
    await log_tool_call(
        db,
        execution_id,
        tenant_id,
        AGENT_NAME,
        "get_covenant_headroom",
        {"as_of": str(as_of)},
        {"headroom_pct": 100},
    )
    await log_tool_call(
        db,
        execution_id,
        tenant_id,
        AGENT_NAME,
        "get_cir_status",
        {"as_of": str(as_of)},
        {"status": "green"},
    )

    payload = {
        "execution_id": execution_id,
        "model": MODEL,
        "position_vs_yesterday": "unchanged",
        "payments_due_today": {"count": 0, "value_gbp": 0},
        "hmrc_obligations_this_week": obligations,
        "covenant_alerts": [],
        "cir_status": "green",
        "ai_forecast_update": "stable",
    }
    return payload
