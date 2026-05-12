from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
