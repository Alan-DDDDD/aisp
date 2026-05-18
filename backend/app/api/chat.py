import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import (
    AgentTrace,
    ChatMessage,
    ChatRoom,
    Document,
    KnowledgeBase,
    Workspace,
)
from app.schemas.chat import (
    MessageOut,
    RoomCreate,
    RoomOut,
    TraceOut,
    TraceStepOut,
)
from app.schemas.workspace import WorkspaceOut

router = APIRouter(prefix="/api", tags=["chat"])


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    session: AsyncSession = Depends(get_session),
) -> list[WorkspaceOut]:
    """所有可用 workspaces — 給前端 selector。"""
    stmt = (
        select(
            Workspace,
            func.count(KnowledgeBase.id.distinct()).label("kb_count"),
            func.count(Document.id).label("doc_count"),
        )
        .outerjoin(KnowledgeBase, KnowledgeBase.workspace_id == Workspace.id)
        .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
        .where(Workspace.status == "active")
        .group_by(Workspace.id)
        .order_by(Workspace.created_at)
    )
    rows = (await session.execute(stmt)).all()
    return [
        WorkspaceOut(
            id=ws.id,
            display_name=ws.display_name,
            description=ws.description,
            default_kb=ws.default_kb,
            status=ws.status,
            color=ws.color,
            icon=ws.icon,
            created_at=ws.created_at,
            kb_count=int(kb_count or 0),
            doc_count=int(doc_count or 0),
        )
        for ws, kb_count, doc_count in rows
    ]


@router.post("/rooms", response_model=RoomOut)
async def create_room(
    body: RoomCreate,
    session: AsyncSession = Depends(get_session),
) -> RoomOut:
    # 驗證 workspace 存在
    ws = await session.get(Workspace, body.workspace_id)
    if ws is None:
        raise HTTPException(400, f"workspace not found: {body.workspace_id}")
    room = ChatRoom(
        id=uuid.uuid4().hex,
        workspace_id=body.workspace_id,
        status="open",
        created_at=_now(),
    )
    session.add(room)
    await session.commit()
    await session.refresh(room)
    return RoomOut(
        id=room.id,
        workspace_id=room.workspace_id,
        status=room.status,
        created_at=room.created_at,
    )


@router.get("/rooms/{room_id}", response_model=RoomOut)
async def get_room(
    room_id: str,
    session: AsyncSession = Depends(get_session),
) -> RoomOut:
    room = await session.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(404, "room not found")
    return RoomOut(
        id=room.id,
        workspace_id=room.workspace_id,
        status=room.status,
        created_at=room.created_at,
    )


@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
async def list_messages(
    room_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    room = await session.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(404, "room not found")
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at)
    )
    rows = result.scalars().all()
    return [
        MessageOut(
            id=m.id,
            room_id=m.room_id,
            sender_role=m.sender_role,
            content=m.content,
            created_at=m.created_at,
            trace_id=m.trace_id,
        )
        for m in rows
    ]


@router.get("/traces/{trace_id}", response_model=TraceOut)
async def get_trace(
    trace_id: str,
    session: AsyncSession = Depends(get_session),
) -> TraceOut:
    trace = await session.get(AgentTrace, trace_id)
    if not trace:
        raise HTTPException(404, "trace not found")
    steps = [TraceStepOut.model_validate(s) for s in (trace.steps or [])]
    return TraceOut(
        id=trace.id,
        workflow_id=trace.workflow_id,
        total_latency_ms=trace.total_latency_ms,
        steps=steps,
        created_at=trace.created_at,
    )
