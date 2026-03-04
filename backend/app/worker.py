from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date

from app.agents import daily_briefing, hmrc_deadlines, payment_prep, variance_alert
from app.core.database import _get_session_factory


async def run_daily_briefing() -> None:
    tenant_id = uuid.UUID(os.getenv("AGENT_TENANT_ID", "6dfc32c5-8bef-48bd-9753-c8b8aa2dc676"))
    async with _get_session_factory() as db:
        await daily_briefing.run(db, tenant_id, date.today())
        await db.commit()


async def run_payment_prep(cutoff: str) -> None:
    tenant_id = uuid.UUID(os.getenv("AGENT_TENANT_ID", "6dfc32c5-8bef-48bd-9753-c8b8aa2dc676"))
    async with _get_session_factory() as db:
        await payment_prep.run(db, tenant_id, cutoff)
        await db.commit()


async def run_variance_alert() -> None:
    tenant_id = uuid.UUID(os.getenv("AGENT_TENANT_ID", "6dfc32c5-8bef-48bd-9753-c8b8aa2dc676"))
    async with _get_session_factory() as db:
        await variance_alert.run(db, tenant_id)
        await db.commit()


async def run_hmrc_deadlines() -> None:
    tenant_id = uuid.UUID(os.getenv("AGENT_TENANT_ID", "6dfc32c5-8bef-48bd-9753-c8b8aa2dc676"))
    async with _get_session_factory() as db:
        await hmrc_deadlines.run(db, tenant_id, date.today())
        await db.commit()


async def main() -> None:
    mode = os.getenv("AGENT_RUN_MODE", "daily_briefing")
    if mode == "daily_briefing":
        await run_daily_briefing()
    elif mode == "payment_prep_chaps":
        await run_payment_prep("10:00_CHAPS")
    elif mode == "payment_prep_bacs":
        await run_payment_prep("15:00_BACS")
    elif mode == "payment_prep_fps":
        await run_payment_prep("16:30_FPS")
    elif mode == "variance_alert":
        await run_variance_alert()
    elif mode == "hmrc_deadlines":
        await run_hmrc_deadlines()


if __name__ == "__main__":
    asyncio.run(main())
