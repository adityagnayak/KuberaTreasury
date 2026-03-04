from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import log_tool_call, new_execution_id

AGENT_NAME = "payment_prep"
MODEL = "claude-sonnet-4-6"


async def run(db: AsyncSession, tenant_id: uuid.UUID, cutoff_label: str) -> dict:
    execution_id = new_execution_id()
    tools = [
        "get_approved_payments",
        "check_funds_availability",
        "validate_beneficiaries",
        "check_sanctions",
        "generate_pain001",
    ]
    actions: list[dict] = []
    for tool_name in tools:
        result = {"status": "ok", "prepared_only": True, "timestamp": datetime.utcnow().isoformat()}
        await log_tool_call(db, execution_id, tenant_id, AGENT_NAME, tool_name, {"cutoff": cutoff_label}, result)
        actions.append({"tool": tool_name, **result})

    return {
        "execution_id": execution_id,
        "model": MODEL,
        "cutoff": cutoff_label,
        "staged": True,
        "human_approval_required": True,
        "actions": actions,
    }
