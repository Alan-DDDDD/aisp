"""KB 檢索 — 給 KBSearchTool / KnowledgeAgent 用。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase
from app.km import store
from app.schemas.knowledge import KnowledgeSearchHit

log = logging.getLogger(__name__)


async def search(
    session: AsyncSession,
    *,
    workspace_id: str,
    kb_name: str,
    query: str,
    top_k: int = 5,
    metadata_filter: dict[str, Any] | None = None,
) -> list[KnowledgeSearchHit]:
    if not (query or "").strip():
        return []

    stmt = select(KnowledgeBase).where(
        KnowledgeBase.workspace_id == workspace_id,
        KnowledgeBase.name == kb_name,
    )
    result = await session.execute(stmt)
    kb = result.scalar_one_or_none()
    if not kb:
        log.info("No KB found for %s/%s", workspace_id, kb_name)
        return []

    collection = store.get_or_create_collection(kb.collection_name)

    where = {"workspace_id": workspace_id}
    if metadata_filter:
        where = {"$and": [where, *[{k: v} for k, v in metadata_filter.items()]]}

    try:
        raw = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where if metadata_filter else {"workspace_id": workspace_id},
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Chroma query failed for %s: %s", kb.collection_name, e)
        return []

    hits: list[KnowledgeSearchHit] = []
    docs_lists = raw.get("documents") or [[]]
    ids_lists = raw.get("ids") or [[]]
    metas_lists = raw.get("metadatas") or [[]]
    dists_lists = raw.get("distances") or [[]]

    if not docs_lists:
        return []

    for chunk_id, text, meta, dist in zip(
        ids_lists[0], docs_lists[0], metas_lists[0], dists_lists[0], strict=False
    ):
        meta = meta or {}
        # cosine distance ∈ [0, 2]，轉成 similarity ∈ [-1, 1]，再 clamp 到 [0, 1] 顯示
        similarity = max(0.0, 1.0 - float(dist))
        hits.append(
            KnowledgeSearchHit(
                chunk_id=chunk_id,
                document_id=meta.get("doc_id", ""),
                title=meta.get("title", ""),
                text=text,
                score=similarity,
                metadata=meta,
            )
        )
    return hits
