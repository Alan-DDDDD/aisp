"""Reindex Chroma collections from SQLite — repair tool when chroma 與 SQL 不同步。

使用情境：
- 啟動時 `KB 已存在（N docs），略過 seed` 但 retrieval 0 hits
- Chroma collection 存在但 count=0
- 換過 embedding model 想全部重 embed

行為：
- 不動 SQLite — 只重建 Chroma 端
- 對每個 KB：清空現有 chroma collection → 從 chunks 表重新 push 所有 chunk

不是 app code 的一部分；是 ops script。HF Space 不會跑它。

用法：
    cd backend
    .venv/Scripts/python scripts/reindex_chroma.py            # 全部 reindex
    .venv/Scripts/python scripts/reindex_chroma.py cs hr       # 只 reindex 指定 workspace
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import Chunk, Document, KnowledgeBase
from app.km import store


async def reindex_kb(session, kb: KnowledgeBase) -> tuple[int, int]:
    """重 embed 一個 KB 的所有 chunk 進 Chroma。

    回 (docs_count, chunks_count)。
    """
    stmt = (
        select(Document)
        .options(selectinload(Document.chunks))
        .where(Document.kb_id == kb.id, Document.status == "active")
    )
    result = await session.execute(stmt)
    docs = result.scalars().all()

    # 先砍掉舊 collection 確保乾淨（同 ingest_document 的 _delete_chunks_from_chroma 行為）
    try:
        store.delete_collection(kb.collection_name)
    except Exception as e:
        print(f"  delete_collection warn: {e}")

    collection = store.get_or_create_collection(kb.collection_name)

    total_chunks = 0
    for doc in docs:
        if not doc.chunks:
            continue
        ids = [c.embedding_ref for c in doc.chunks]
        texts = [c.text for c in doc.chunks]
        metadatas = [
            {
                "workspace_id": kb.workspace_id,
                "kb": kb.name,
                "doc_id": doc.id,
                "title": doc.title,
                "chunk_index": c.chunk_index,
                **(doc.doc_metadata or {}),
            }
            for c in doc.chunks
        ]
        collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
        total_chunks += len(doc.chunks)

    return len(docs), total_chunks


async def main(filter_workspaces: list[str] | None = None) -> None:
    async with SessionLocal() as session:
        stmt = select(KnowledgeBase)
        if filter_workspaces:
            stmt = stmt.where(KnowledgeBase.workspace_id.in_(filter_workspaces))
        result = await session.execute(stmt)
        kbs = result.scalars().all()

        if not kbs:
            print("沒找到任何 KB")
            return

        for kb in kbs:
            label = f"{kb.workspace_id}/{kb.name}"
            print(f"\nreindexing {label} (collection={kb.collection_name})...")
            docs, chunks = await reindex_kb(session, kb)
            print(f"  ✓ {label}: {docs} docs / {chunks} chunks reindexed")

    print("\n== 驗證 ==")
    for kb in kbs:
        coll = store.get_or_create_collection(kb.collection_name)
        print(f"  {kb.collection_name}: {coll.count()} embeddings")


if __name__ == "__main__":
    filter_ws = sys.argv[1:] if len(sys.argv) > 1 else None
    asyncio.run(main(filter_ws))
