from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    embedding_model: str
    version: int
    created_at: datetime
    collection_name: str
    doc_count: int = 0


class DocumentOut(BaseModel):
    id: str
    kb_id: str
    source_type: str
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int
    status: str
    updated_at: datetime
    chunk_count: int = 0


class ChunkOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    text: str


class DocumentIngest(BaseModel):
    title: str
    content: str
    source_type: str = "faq"
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchHit(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAgentInput(BaseModel):
    query: str
    workspace_id: str = "default"
    kb_name: str = "faq"
    top_k: int = 5
    metadata_filter: dict[str, Any] | None = None


class KnowledgeAgentOutput(BaseModel):
    docs: list[KnowledgeSearchHit] = Field(default_factory=list)
    kb_name: str
    query: str
