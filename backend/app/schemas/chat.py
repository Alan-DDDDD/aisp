from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    workspace_id: str = "default"


class RoomOut(BaseModel):
    id: str
    workspace_id: str
    status: str
    created_at: datetime


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: str
    room_id: str
    sender_role: str
    content: str
    created_at: datetime
    trace_id: str | None = None


class TraceStepOut(BaseModel):
    step_id: str
    agent_id: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = 0
    model: str | None = None


class TraceOut(BaseModel):
    id: str
    workflow_id: str
    total_latency_ms: int
    steps: list[TraceStepOut]
    created_at: datetime


# WebSocket event types
class WsUserMessageIn(BaseModel):
    type: Literal["user_message"]
    content: str


class WsAiSuggestionOut(BaseModel):
    type: Literal["ai_suggestion"] = "ai_suggestion"
    room_id: str
    message_id: str
    draft: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)
    trace: TraceOut


class WsUserMessageOut(BaseModel):
    type: Literal["user_message"] = "user_message"
    message: MessageOut


class WsErrorOut(BaseModel):
    type: Literal["error"] = "error"
    message: str


# Phase 14 — UX progress events（送出後到 ai_suggestion 之間的「系統正在做什麼」）
class WsAiThinkingStartOut(BaseModel):
    """workflow 開始跑時馬上送一次，讓前端立刻有反饋。"""

    type: Literal["ai_thinking_start"] = "ai_thinking_start"
    room_id: str


class WsAiStageChangedOut(BaseModel):
    """workflow 內部跨入新階段（understanding / retrieving / composing）。"""

    type: Literal["ai_stage_changed"] = "ai_stage_changed"
    room_id: str
    stage: str  # understanding | retrieving | composing
    label: str  # 已 i18n 過、給前端直接顯示的字串


class WsToolSynthesisTriggeredOut(BaseModel):
    """tool_agent 偵測到 GAP 觸發合成。可能花 10-30 秒。"""

    type: Literal["tool_synthesis_triggered"] = "tool_synthesis_triggered"
    room_id: str
    tool_name: str
