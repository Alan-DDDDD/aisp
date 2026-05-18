"""TicketCreateTool — IT 部門 demo 用的 mock 工單建立工具。

實際應用中應接 Jira / ServiceNow / 公司內部工單系統。對接外部時
side_effect 要改 WRITE_EXTERNAL 且建議 requires_approval=True。
"""

from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel

from app.db.database import SessionLocal
from app.db.models import Ticket
from app.schemas.agent import AgentContext
from app.tools.base import BaseTool, SideEffect, ToolExample

log = logging.getLogger(__name__)


class TicketCreateInput(BaseModel):
    summary: str
    rationale: str = ""


class TicketCreateOutput(BaseModel):
    ticket_id: str
    status: str = "open"


class TicketCreateTool(BaseTool):
    id = "ticket_create"
    version = "1.0.0"
    source = "builtin"

    description = "Create a helpdesk ticket scoped to the current room/workspace."
    when_to_use = (
        "IT helpdesk 場景中，使用者問題需要 IT 人員親自介入時（例如密碼重設驗證失敗、"
        "權限申請、硬體故障、軟體採購、安全事件）。工單建立後可由 admin endpoint 列出追蹤。"
    )
    when_NOT_to_use = (
        "不要用於 FAQ 可解、使用者可自助的一般問題。"
        "不要用於其他 workspace（CS / HR / 法務）的問題類型。"
        "不要用於建立非 IT 性質的任務追蹤（例如業務 leads、HR 流程）。"
    )
    examples = [
        ToolExample(
            scenario="員工密碼重設驗證失敗，需要 IT 介入",
            input={"summary": "密碼重設驗證失敗 - alan@hf.com", "rationale": "MFA token 持續無法收到"},
            output={"ticket_id": "T-A1B2C3D4", "status": "open"},
        ),
        ToolExample(
            scenario="疑似可疑連線 - 安全事件",
            input={
                "summary": "可疑外部連線 - 工作站 W-1029",
                "rationale": "防火牆 log 顯示固定每 5 分鐘對外連線到未知 IP",
            },
            output={"ticket_id": "T-E5F6G7H8", "status": "open"},
        ),
    ]

    input_schema = TicketCreateInput
    output_schema = TicketCreateOutput

    # demo 用本地 SQLite tickets 表，故為 WRITE_LOCAL；
    # 對接 Jira / ServiceNow 時應升級為 WRITE_EXTERNAL + requires_approval=True。
    side_effect = SideEffect.WRITE_LOCAL
    requires_approval = False
    tags = ["it", "ticket", "helpdesk"]

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
