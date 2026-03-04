from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import log_tool_call, new_execution_id

AGENT_NAME = "variance_alert"
MODEL = "claude-sonnet-4-6"


async def run(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    execution_id = new_execution_id()

    checks = {
        "single_movement_pct": 0,
        "weekly_variance_pct": 0,
        "unmatched_intercompany_days": 0,
    }

    await log_tool_call(db, execution_id, tenant_id, AGENT_NAME, "get_actual_vs_forecast", {}, checks)
    await log_tool_call(db, execution_id, tenant_id, AGENT_NAME, "get_position_movements", {}, checks)
    await log_tool_call(db, execution_id, tenant_id, AGENT_NAME, "get_large_transactions", {}, checks)

    triggered = (
        checks["single_movement_pct"] > 10
        or checks["weekly_variance_pct"] > 15
        or checks["unmatched_intercompany_days"] > 7
    )

    return {
        "execution_id": execution_id,
        "model": MODEL,
        "triggered": triggered,
        "alert_to": "treasury_manager_and_above",
        "checks": checks,
        "at": datetime.utcnow().isoformat(),
    }
