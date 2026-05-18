from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "cs"
    display_name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    default_kb: Mapped[str] = mapped_column(String(64), default="faq")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|archived
    color: Mapped[str] = mapped_column(String(16), default="#5b6cff")
    icon: Mapped[str] = mapped_column(String(8), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("chat_rooms.id"), index=True)
    sender_role: Mapped[str] = mapped_column(String(32))  # user | ai | operator | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    trace_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_traces.id"), nullable=True
    )

    room: Mapped["ChatRoom"] = relationship(back_populates="messages")
    trace: Mapped["AgentTrace | None"] = relationship(foreign_keys=[trace_id])


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow_id: Mapped[str] = mapped_column(String(64), default="phase1_default")
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    name: Mapped[str] = mapped_column(String(128))  # e.g. "faq", "sop"
    embedding_model: Mapped[str] = mapped_column(String(128), default="chroma-default")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
    )

    @property
    def collection_name(self) -> str:
        """ChromaDB collection 名稱，跨 workspace 強制隔離。"""
        return f"ws_{self.workspace_id}__{self.name}"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="faq")  # faq|sop|pdf|md|url
    title: Mapped[str] = mapped_column(String(256))
    raw_text: Mapped[str] = mapped_column(Text)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|archived
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    kb: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    # embedding 存在 ChromaDB，這裡只記 id 對應
    embedding_ref: Mapped[str] = mapped_column(String(64))

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Phase 6 — Self-Extending Agent / Tool Synthesis ───────────────────
# 詳見 PLAN §22.7。四張表分別對應：
#   tool_decisions_audit — Phase A 每次 USE/COMPOSE/GAP 決策的 log
#   tool_synthesis_tasks — Phase B 的 state machine 持久化
#   generated_tools      — Phase B 註冊成功的 tool metadata
#   tool_review_history  — 每次審核動作（approve/reject/refine）的 log


class ToolDecisionAudit(Base):
    """Phase A Gap Detection 每個 step 的決策紀錄。

    可用來事後分析「為什麼當時選了 USE 而不是 GAP」、tuning similarity threshold、
    以及判斷 LLM judge 的準確度。
    """

    __tablename__ = "tool_decisions_audit"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query_id: Mapped[str] = mapped_column(String(64), index=True)
    step_id: Mapped[str] = mapped_column(String(64))
    step_description: Mapped[str] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)

    decision: Mapped[str] = mapped_column(String(16))  # USE | COMPOSE | GAP
    tool_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # USE 時填
    compose_chain: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)  # COMPOSE 時填
    gap_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GAP 時填

    confidence: Mapped[float] = mapped_column(default=0.0)
    candidates: Mapped[list[dict]] = mapped_column(JSON, default=list)  # retrieval top-K
    max_similarity: Mapped[float] = mapped_column(default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")

    # 路由訊號：哪一段決策路徑（shortcut_high / shortcut_low / judge / human）
    route: Mapped[str] = mapped_column(String(32), default="judge")
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ToolSynthesisTask(Base):
    """Phase B Code Agent 流程的 state machine 持久化。

    流程詳見 PLAN §22.8。Server restart / 人類長時間未回覆都靠這張表 resume。
    """

    __tablename__ = "tool_synthesis_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 觸發來源（追溯）
    triggered_by_query_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    triggered_by_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_decisions_audit.id"), nullable=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)

    # State machine
    state: Mapped[str] = mapped_column(String(32), index=True)
    # GAP_DETECTED | SPEC_GENERATING | CODE_GENERATING | TESTS_GENERATING |
    # STATIC_CHECK | SANDBOX_RUNNING | AWAITING_HUMAN_RESCUE | AWAITING_APPROVAL |
    # REGISTERED | DISCARDED | FAILED

    # 產物
    spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    tests: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 修正迴圈
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempt_history: Mapped[list[dict]] = mapped_column(JSON, default=list)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sandbox 行為觀察結果（PLAN §22.5.5）
    behavior_observation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 模型紀錄（用了哪個 model 生成）
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GeneratedTool(Base):
    """Phase B 註冊成功的 tool metadata（source code 存在 source_path 指定的檔案）。"""

    __tablename__ = "generated_tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 工具的 unique id
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    synthesis_task_id: Mapped[str] = mapped_column(ForeignKey("tool_synthesis_tasks.id"), index=True)

    # Scoping
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # null = global，被 promote 過；否則只給該 workspace 用（PLAN §22.5.8）
    scope: Mapped[str] = mapped_column(String(16), default="workspace")  # workspace | global

    # Tool spec snapshot（給 retrieval / judge 用）
    description: Mapped[str] = mapped_column(Text)
    when_to_use: Mapped[str] = mapped_column(Text, default="")
    when_not_to_use: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list[dict]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    side_effect: Mapped[str] = mapped_column(String(32), default="read_only")
    requires_approval: Mapped[bool] = mapped_column(default=False)

    # 程式碼位置（檔案路徑由 registry loader 載入）
    source_path: Mapped[str] = mapped_column(String(256))

    # 審核 metadata
    approved_by: Mapped[str] = mapped_column(String(128))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | deprecated | revoked


class ToolReviewHistory(Base):
    """每次審核動作的 log（approve / reject / refine_hint / abandon）。"""

    __tablename__ = "tool_review_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tool_synthesis_tasks.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))  # approve | reject | refine_hint | abandon | retry
    reviewer: Mapped[str] = mapped_column(String(128))  # Telegram chat_id 或使用者識別
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)  # refine_hint 時填
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
