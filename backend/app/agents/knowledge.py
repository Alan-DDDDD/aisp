"""KnowledgeAgent — Phase 3 起接 KBSearchTool。

職責：依 Router 給的 intent 決定要查哪個 KB，呼叫 tool 拿結果，把 hits 回傳給下游 Composer。
Phase 5 起：可加 query rewriting、multi-hop retrieval、結合 reranker。
"""

from __future__ import annotations

import logging

from app.agents.base import BaseAgent
from app.schemas.agent import AgentContext
from app.schemas.knowledge import KnowledgeAgentInput, KnowledgeAgentOutput
from app.tools import registry as tool_registry

log = logging.getLogger(__name__)


class KnowledgeAgent(BaseAgent):
    id = "knowledge"
    input_schema = KnowledgeAgentInput
    output_schema = KnowledgeAgentOutput

    async def run(  # type: ignore[override]
        self, ctx: AgentContext, payload: KnowledgeAgentInput
    ) -> KnowledgeAgentOutput:
        # Phase 3：直接代理給 KBSearchTool；未來這裡可以加意圖過濾、查詢改寫等
        kb_search = tool_registry.get("kb_search")
        try:
            result = await kb_search.call(ctx, payload)
        except Exception as e:  # noqa: BLE001 — 失敗時不該中斷整條 pipeline
            log.warning("KBSearchTool failed: %s", e)
            return KnowledgeAgentOutput(docs=[], kb_name=payload.kb_name, query=payload.query)

        log.info(
            "KnowledgeAgent: workspace=%s kb=%s query=%r → %d hits",
            payload.workspace_id,
            payload.kb_name,
            payload.query[:50],
            len(result.docs),
        )
        return result
