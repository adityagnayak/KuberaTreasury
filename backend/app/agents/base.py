from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentExecutionLog


def new_execution_id() -> str:
    return uuid.uuid4().hex


async def log_tool_call(
    db: AsyncSession,
    execution_id: str,
    tenant_id: uuid.UUID,
    agent_name: str,
    tool_name: str,
    tool_input: dict[str, Any] | None,
    tool_output: dict[str, Any] | None,
) -> None:
    db.add(
        AgentExecutionLog(
            execution_id=execution_id,
            tenant_id=tenant_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_input=json.dumps(tool_input or {}),
            tool_output=json.dumps(tool_output or {}),
            created_at=datetime.now(timezone.utc),
        )
    )
