"""BaseTool — 所有 tool 的共同契約。

Phase 6 起 schema 擴充（PLAN §22.6），目的是讓：
  - Retrieval 拿 description + when_to_use + when_NOT_to_use + examples 做 embedding
  - Judge LLM 看 examples / side_effect 判斷適用性
  - Code Agent 用 examples 當 ground truth 生成 test
  - 審核流程透過 source / approved_by / requires_approval 區分 builtin vs generated

設計原則：Agent 是「決策」，Tool 是「動作」。Tool 由 agent 主動呼叫，
且每次呼叫都會被 orchestrator 紀錄到 tool_invocations。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.agent import AgentContext


class SideEffect(StrEnum):
    """工具是否會改變外部狀態。

    - READ_ONLY：純查詢，不改變任何狀態（例如 kb_search）
    - WRITE_LOCAL：寫入自己的 DB（例如 ticket_create 寫 SQLite）
    - WRITE_EXTERNAL：呼外部 API、寄信、付款等（高風險，預設 requires_approval=True）
    """

    READ_ONLY = "read_only"
    WRITE_LOCAL = "write_local"
    WRITE_EXTERNAL = "write_external"


class ToolExample(BaseModel):
    """一個工具範例：給 retrieval / few-shot / test generation 三處用。"""

    scenario: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    # ── 識別 ───────────────────────────
    id: str
    version: str = "1.0.0"
    source: Literal["builtin", "generated"] = "builtin"

    # ── 給 LLM 看的描述 ────────────────
    description: str
    when_to_use: str = ""
    when_NOT_to_use: str = ""  # 抑制誤用最有效的單一欄位
    examples: list[ToolExample] = []

    # ── 結構約束 ───────────────────────
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    # ── 治理 metadata ──────────────────
    side_effect: SideEffect = SideEffect.READ_ONLY
    requires_approval: bool = False  # 高風險工具執行前是否再問人類
    tags: list[str] = []
    # tool_agent 對 user message 做 retrieval 時是否該看見這個工具。
    # False = 「agent-internal」工具，只有特定 agent（如 knowledge_agent 之於
    # kb_search、ticket_decision_agent 之於 ticket_create）主動呼叫；tool_agent
    # 不該誤選它們。True = 一般 user-facing 工具（含所有 generated tool）。
    discoverable: bool = True

    # ── Generated tool 才有 ────────────
    approved_by: str | None = None
    approved_at: datetime | None = None
    source_path: str | None = None  # 例如 tools/generated/<id>.py

    @abstractmethod
    async def call(self, ctx: AgentContext, payload: BaseModel) -> BaseModel:
        raise NotImplementedError

    @classmethod
    def embedding_text(cls) -> str:
        """產出給 retrieval 用的工具文字表徵。

        format 刻意對 LLM 友善：標題 + 條列，避免 JSON / dict 結構讓 embedding 失真。
        """
        lines: list[str] = [f"[Tool: {cls.id}]", f"Description: {cls.description}"]
        if cls.when_to_use:
            lines.append(f"Use when: {cls.when_to_use}")
        if cls.when_NOT_to_use:
            lines.append(f"Don't use when: {cls.when_NOT_to_use}")
        if cls.examples:
            lines.append("Examples:")
            for ex in cls.examples:
                lines.append(f"  - {ex.scenario}")
        if cls.tags:
            lines.append(f"Tags: {', '.join(cls.tags)}")
        lines.append(f"Side effect: {cls.side_effect.value}")
        return "\n".join(lines)
