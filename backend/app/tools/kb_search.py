"""KBSearchTool — workspace-scoped KB 檢索 (Knowledge agent 的主要工具)。"""

from __future__ import annotations

from app.db.database import SessionLocal
from app.km import retriever
from app.schemas.agent import AgentContext
from app.schemas.knowledge import KnowledgeAgentInput, KnowledgeAgentOutput
from app.tools.base import BaseTool


class KBSearchTool(BaseTool):
    id = "kb_search"
    description = "Search a workspace-scoped knowledge base for relevant chunks."
    input_schema = KnowledgeAgentInput
    output_schema = KnowledgeAgentOutput

    async def call(  # type: ignore[override]
        self, ctx: AgentContext, payload: KnowledgeAgentInput
    ) -> KnowledgeAgentOutput:
        async with SessionLocal() as session:
            hits = await retriever.search(
                session,
                workspace_id=payload.workspace_id,
                kb_name=payload.kb_name,
                query=payload.query,
                top_k=payload.top_k,
                metadata_filter=payload.metadata_filter,
            )
        return KnowledgeAgentOutput(docs=hits, kb_name=payload.kb_name, query=payload.query)
