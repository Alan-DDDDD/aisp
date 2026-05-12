"""Workflow YAML 的 Pydantic schema。

Phase 5 支援：linear pipeline + 隱式並行（由變數依賴推導）。
Phase 6+ 會加：parallel_with 顯式提示、條件分支（when）、loop。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class WorkflowStep(BaseModel):
    id: str = Field(..., description="step 唯一識別；同時是輸出變數名稱")
    agent: str = Field(..., description="agent registry id")
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="agent input；值可為 literal、$event.x、$context.x、$<step>.x",
    )
    parallel_with: list[str] = Field(
        default_factory=list,
        description="可與這些 step 平行（runtime 僅作 hint，依賴主要靠變數推導）",
    )
    on_error: str = Field(
        default="continue",
        description="continue（記錯但繼續下游）| abort（整條 workflow 中止）",
    )

    @field_validator("on_error")
    @classmethod
    def _validate_on_error(cls, v: str) -> str:
        if v not in {"continue", "abort"}:
            raise ValueError(f"on_error must be 'continue' or 'abort', got {v!r}")
        return v


class WorkflowDef(BaseModel):
    id: str
    workspace: str
    description: str = ""
    trigger: str = "on_user_message"
    steps: list[WorkflowStep]
    emit: dict[str, Any] = Field(
        default_factory=dict,
        description="最終要送出的 payload；值可帶 $<step>.field 引用",
    )

    @field_validator("steps")
    @classmethod
    def _validate_steps_unique(cls, v: list[WorkflowStep]) -> list[WorkflowStep]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError(f"workflow steps must have unique ids: {ids}")
        return v
