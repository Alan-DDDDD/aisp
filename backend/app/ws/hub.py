"""WebSocket hub — room-based pub/sub。

Phase 1 用記憶體管理連線，未來多 worker 時可換成 Redis pub/sub。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import AgentTrace, ChatMessage, ChatRoom
from app.schemas.chat import (
    MessageOut,
    TraceOut,
    TraceStepOut,
    WsAiSuggestionOut,
    WsErrorOut,
    WsUserMessageOut,
)
from app.workflow import loader as workflow_loader
from app.workflow.runtime import run_workflow

log = logging.getLogger(__name__)

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, room_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms[room_id].add(ws)
        log.info("WS connected: room=%s, total=%d", room_id, len(self._rooms[room_id]))

    async def disconnect(self, room_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms[room_id].discard(ws)
            if not self._rooms[room_id]:
                self._rooms.pop(room_id, None)
        log.info("WS disconnected: room=%s", room_id)

    async def broadcast(self, room_id: str, payload: dict) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(room_id, ()))
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                log.warning("Broadcast to a socket failed; removing.", exc_info=True)
                await self.disconnect(room_id, ws)


manager = ConnectionManager()


@router.websocket("/ws/rooms/{room_id}")
async def chat_socket(websocket: WebSocket, room_id: str) -> None:
    # 驗證 room 存在
    async with SessionLocal() as session:
        room = await session.get(ChatRoom, room_id)
        if not room:
            await websocket.close(code=4004, reason="room not found")
            return

    await manager.connect(room_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await _handle_event(room_id, data)
    except WebSocketDisconnect:
        await manager.disconnect(room_id, websocket)
    except Exception as e:  # noqa: BLE001
        log.exception("WS error in room %s", room_id)
        try:
            await websocket.send_json(WsErrorOut(message=str(e)).model_dump())
        except Exception:
            pass
        await manager.disconnect(room_id, websocket)


async def _handle_event(room_id: str, data: dict) -> None:
    event_type = data.get("type")
    if event_type != "user_message":
        await manager.broadcast(
            room_id,
            WsErrorOut(message=f"unsupported event type: {event_type}").model_dump(),
        )
        return

    content = (data.get("content") or "").strip()
    if not content:
        return

    # 1. Persist user message
    user_msg_id = uuid.uuid4().hex
    async with SessionLocal() as session:
        user_msg = ChatMessage(
            id=user_msg_id,
            room_id=room_id,
            sender_role="user",
            content=content,
            created_at=_now(),
        )
        session.add(user_msg)
        await session.commit()

        room_row = await session.get(ChatRoom, room_id)
        workspace_id = room_row.workspace_id if room_row else "cs"

        # Load history for orchestrator
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.room_id == room_id)
            .order_by(ChatMessage.created_at)
        )
        history_rows = result.scalars().all()

    history = [
        {"role": m.sender_role, "content": m.content}
        for m in history_rows[:-1]  # 不包含剛存的這則
    ]

    # 2. Broadcast user message back
    await manager.broadcast(
        room_id,
        WsUserMessageOut(
            message=MessageOut(
                id=user_msg_id,
                room_id=room_id,
                sender_role="user",
                content=content,
                created_at=history_rows[-1].created_at,
            )
        ).model_dump(mode="json"),
    )

    # 3. Run workflow (YAML-driven)
    try:
        workflow = workflow_loader.get(workspace_id)
    except FileNotFoundError as e:
        log.warning("No workflow.yaml for workspace %s: %s", workspace_id, e)
        await manager.broadcast(
            room_id,
            WsErrorOut(message=f"no workflow for workspace: {workspace_id}").model_dump(),
        )
        return

    try:
        result = await run_workflow(
            workflow,
            event={"message": content},
            workspace_id=workspace_id,
            room_id=room_id,
            history=history,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Workflow failed in room %s", room_id)
        await manager.broadcast(
            room_id,
            WsErrorOut(message=f"workflow failed: {e}").model_dump(),
        )
        return

    draft = (result.emit.get("draft") or "").strip()
    citations = result.emit.get("citations") or []
    extras = {k: v for k, v in result.emit.items() if k not in {"draft", "citations"}}
    if not draft:
        log.warning("Workflow %s produced empty draft; emit=%r", workflow.id, result.emit)
        draft = "（系統暫時無法產生回覆，請稍後再試。）"

    # 4. Persist trace + AI message
    ai_msg_id = uuid.uuid4().hex
    async with SessionLocal() as session:
        trace_row = AgentTrace(
            id=result.trace_id,
            room_id=room_id,
            message_id=ai_msg_id,
            workflow_id=result.workflow_id,
            steps=[s.model_dump() for s in result.steps],
            total_latency_ms=result.total_latency_ms,
            created_at=_now(),
        )
        session.add(trace_row)

        ai_msg = ChatMessage(
            id=ai_msg_id,
            room_id=room_id,
            sender_role="ai",
            content=draft,
            trace_id=result.trace_id,
            created_at=_now(),
        )
        session.add(ai_msg)
        await session.commit()

    # 5. Broadcast AI suggestion + trace
    payload = WsAiSuggestionOut(
        room_id=room_id,
        message_id=ai_msg_id,
        draft=draft,
        citations=citations,
        extras=extras,
        trace=TraceOut(
            id=result.trace_id,
            workflow_id=result.workflow_id,
            total_latency_ms=result.total_latency_ms,
            steps=[TraceStepOut.model_validate(s.model_dump()) for s in result.steps],
            created_at=_now(),
        ),
    )
    await manager.broadcast(room_id, payload.model_dump(mode="json"))
