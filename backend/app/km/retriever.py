"""KB 檢索 — 給 KBSearchTool / KnowledgeAgent 用。

支援三種模式（由 settings.retrieval_mode 控制）：
- "dense"：純 ChromaDB cosine
- "bm25"：純 BM25 關鍵字
- "hybrid"（預設）：兩者並跑，用 Reciprocal Rank Fusion 合併

啟用 settings.rerank_model 時，融合後再走 cross-encoder 精排。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase
from app.km import bm25_index, reranker, store
from app.schemas.knowledge import KnowledgeSearchHit

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Dense (Chroma) search
# ──────────────────────────────────────────────────────────────────────────


def _build_where(workspace_id: str, metadata_filter: dict[str, Any] | None) -> dict:
    base = {"workspace_id": workspace_id}
    if not metadata_filter:
        return base
    return {"$and": [base, *[{k: v} for k, v in metadata_filter.items()]]}


def _dense_search(
    collection_name: str,
    query: str,
    *,
    workspace_id: str,
    top_k: int,
    metadata_filter: dict[str, Any] | None = None,
) -> list[KnowledgeSearchHit]:
    collection = store.get_or_create_collection(collection_name)
    where = _build_where(workspace_id, metadata_filter)
    try:
        raw = collection.query(query_texts=[query], n_results=top_k, where=where)
    except Exception as e:  # noqa: BLE001
        log.exception("Chroma query failed for %s: %s", collection_name, e)
        return []

    docs_lists = raw.get("documents") or [[]]
    ids_lists = raw.get("ids") or [[]]
    metas_lists = raw.get("metadatas") or [[]]
    dists_lists = raw.get("distances") or [[]]
    if not docs_lists:
        return []

    hits: list[KnowledgeSearchHit] = []
    for chunk_id, text, meta, dist in zip(
        ids_lists[0], docs_lists[0], metas_lists[0], dists_lists[0], strict=False
    ):
        meta = meta or {}
        similarity = max(0.0, 1.0 - float(dist))
        hits.append(
            KnowledgeSearchHit(
                chunk_id=chunk_id,
                document_id=meta.get("doc_id", ""),
                title=meta.get("title", ""),
                text=text,
                score=similarity,
                metadata={**meta, "retriever": "dense"},
            )
        )
    return hits


# ──────────────────────────────────────────────────────────────────────────
# BM25 search
# ──────────────────────────────────────────────────────────────────────────


def _bm25_search(
    collection_name: str,
    query: str,
    *,
    workspace_id: str,
    top_k: int,
    metadata_filter: dict[str, Any] | None = None,
) -> list[KnowledgeSearchHit]:
    raw = bm25_index.search(
        collection_name, query, top_k=top_k * 2, workspace_id=workspace_id
    )
    hits: list[KnowledgeSearchHit] = []
    for chunk_id, text, meta, bm25_score in raw:
        if metadata_filter and not all(
            meta.get(k) == v for k, v in metadata_filter.items()
        ):
            continue
        hits.append(
            KnowledgeSearchHit(
                chunk_id=chunk_id,
                document_id=meta.get("doc_id", ""),
                title=meta.get("title", ""),
                text=text,
                score=settings.bm25_only_default_score,  # placeholder（無 cosine 可用）
                metadata={**meta, "retriever": "bm25", "bm25_score": round(bm25_score, 4)},
            )
        )
        if len(hits) >= top_k:
            break
    return hits


# ──────────────────────────────────────────────────────────────────────────
# RRF fusion
# ──────────────────────────────────────────────────────────────────────────


def _rrf_fuse(
    rankings: list[list[KnowledgeSearchHit]],
    *,
    k: int,
    top_k: int,
) -> list[KnowledgeSearchHit]:
    """以 Reciprocal Rank Fusion 合併多個 ranking。

    score(d) = sum(1 / (k + rank_i(d)))，rank 從 1 起算。
    回傳的 hit 取「該文件在第一個出現它的 ranking 裡的版本」，分數欄改為 RRF 值。
    """
    fused_scores: dict[str, float] = {}
    repr_hit: dict[str, KnowledgeSearchHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            fused_scores[hit.chunk_id] = (
                fused_scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            )
            if hit.chunk_id not in repr_hit:
                repr_hit[hit.chunk_id] = hit

    ordered = sorted(fused_scores.items(), key=lambda kv: kv[1], reverse=True)

    out: list[KnowledgeSearchHit] = []
    for chunk_id, rrf_score in ordered[:top_k]:
        h = repr_hit[chunk_id]
        new_meta = dict(h.metadata or {})
        new_meta["rrf_score"] = round(rrf_score, 6)
        # 顯示分數仍維持 dense cosine（若有），不被 RRF 蓋掉
        out.append(
            KnowledgeSearchHit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                title=h.title,
                text=h.text,
                score=h.score,
                metadata=new_meta,
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


async def search(
    session: AsyncSession,
    *,
    workspace_id: str,
    kb_name: str,
    query: str,
    top_k: int = 5,
    metadata_filter: dict[str, Any] | None = None,
    mode: str | None = None,
) -> list[KnowledgeSearchHit]:
    """主要查詢入口。

    mode：dense / bm25 / hybrid（None = 採用 settings.retrieval_mode）。
    啟用 reranker 時自動於最後加一道精排。
    """
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

    mode = (mode or settings.retrieval_mode or "hybrid").lower()
    collection_name = kb.collection_name

    if mode == "dense":
        hits = _dense_search(
            collection_name,
            query,
            workspace_id=workspace_id,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
    elif mode == "bm25":
        hits = _bm25_search(
            collection_name,
            query,
            workspace_id=workspace_id,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
    else:  # hybrid
        dense = _dense_search(
            collection_name,
            query,
            workspace_id=workspace_id,
            top_k=settings.retrieval_top_k_dense,
            metadata_filter=metadata_filter,
        )
        sparse = _bm25_search(
            collection_name,
            query,
            workspace_id=workspace_id,
            top_k=settings.retrieval_top_k_bm25,
            metadata_filter=metadata_filter,
        )
        hits = _rrf_fuse([dense, sparse], k=settings.hybrid_rrf_k, top_k=top_k)

    if reranker.is_enabled():
        hits = reranker.rerank(query, hits, top_n=top_k)

    return hits
