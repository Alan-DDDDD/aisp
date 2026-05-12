"""TicketCreateTool — IT 部門 demo 用的 mock 工單建立工具。

實際應用中應接 Jira / ServiceNow / 公司內部工單系統。
這裡寫進本地 SQLite tickets 表，可由 admin endpoint 列出。
"""

from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel, Field

from app.db.database import SessionLocal
from app.db.models import Ticket
from app.schemas.agent import AgentContext
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


class TicketCreateInput(BaseModel):
    summary: str
    rationale: str = ""


class TicketCreateOutput(BaseModel):
    ticket_id: str
    status: str = "open"


class TicketCreateTool(BaseTool):
    id = "ticket_create"
    description = "Create a helpdesk ticket scoped to the current room/workspace."
    input_schema = TicketCreateInput
    output_schema = TicketCreateOutput

    async def call(  # type: ignore[override]
        self, ctx: AgentContext, payload: TicketCreateInput
    ) -> TicketCreateOutput:
        ticket_id = f"T-{uuid.uuid4().hex[:8].upper()}"
        async with SessionLocal() as session:
            session.add(
                Ticket(
                    id=ticket_id,
                    room_id=ctx.room_id,
                    workspace_id=ctx.workspace_id,
                    summary=payload.summary,
                    rationale=payload.rationale,
                    status="open",
                )
            )
            await session.commit()
        log.info("Ticket created: %s (workspace=%s, room=%s)", ticket_id, ctx.workspace_id, ctx.room_id)
        return TicketCreateOutput(ticket_id=ticket_id, status="open")
