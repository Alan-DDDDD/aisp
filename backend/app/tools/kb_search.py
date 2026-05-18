"""KBSearchTool — workspace-scoped KB 檢索 (Knowledge agent 的主要工具)。"""

from __future__ import annotations

from app.db.database import SessionLocal
from app.km import retriever
from app.schemas.agent import AgentContext
from app.schemas.knowledge import KnowledgeAgentInput, KnowledgeAgentOutput
from app.tools.base import BaseTool, SideEffect, ToolExample


class KBSearchTool(BaseTool):
    id = "kb_search"
    version = "1.0.0"
    source = "builtin"

    description = "Search a workspace-scoped knowledge base for relevant chunks."
    when_to_use = (
        "需要從 workspace 的知識庫（FAQ / SOP / policy / 合約範本等）找出與 query 相關的段落時。"
        "支援 metadata filter（例如限定文件型態、版本）。"
    )
    when_NOT_to_use = (
        "不要用於跨 workspace 的全域搜尋（KB 是 workspace-scoped）。"
        "不要用於結構化資料查詢（例如「最近 7 天訂單數」這種應該用 SQL / analytics tool）。"
        "不要在沒有 KB 設定的 workspace 上呼叫。"
    )
    examples = [
        ToolExample(
            scenario="客服查 FAQ：「70 歲可以申請車貸嗎？」",
            input={"query": "70 歲可以申請車貸嗎？", "workspace_id": "cs", "kb_name": "faq", "top_k": 5},
            output={"docs": [{"title": "車貸資格", "text": "...", "score": 0.82}], "kb_name": "faq"},
        ),
        ToolExample(
            scenario="HR 查 policy：「特休過期會結算嗎？」",
            input={"query": "特休過期會結算嗎？", "workspace_id": "hr", "kb_name": "policy"},
            output={"docs": [{"title": "特休管理辦法", "text": "...", "score": 0.79}], "kb_name": "policy"},
        ),
    ]

    input_schema = KnowledgeAgentInput
    output_schema = KnowledgeAgentOutput

    side_effect = SideEffect.READ_ONLY
    requires_approval = False
    tags = ["knowledge", "rag", "retrieval"]

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
