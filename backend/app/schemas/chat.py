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
