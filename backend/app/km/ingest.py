"""KB / Document 寫入流程。

呼叫者責任：保證 KB 已建立。本模組只負責把 Document（連同 chunks 與 embedding）寫進
SQLite + ChromaDB，並維持兩邊一致。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Chunk, Document, KnowledgeBase
from app.km import store
from app.km.chunker import ChunkResult, chunk_faq_entry, chunk_structured

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_kb(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    embedding_model: str = "chroma-default",
) -> KnowledgeBase:
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.workspace_id == workspace_id,
        KnowledgeBase.name == name,
    )
    result = await session.execute(stmt)
    kb = result.scalar_one_or_none()
    if kb:
        return kb

    kb = KnowledgeBase(
        id=uuid.uuid4().hex,
        workspace_id=workspace_id,
        name=name,
        embedding_model=embedding_model,
        version=1,
        created_at=_now(),
    )
    session.add(kb)
    await session.flush()  # 取得 kb.id 但暫不 commit；caller 決定 commit 時機

    # 建好對應的 Chroma collection（lazy 也行，預先建立可確認 embedding 模型可用）
    store.get_or_create_collection(kb.collection_name)
    log.info("Created KB %s/%s -> %s", workspace_id, name, kb.collection_name)
    return kb


async def upsert_document(
    session: AsyncSession,
    *,
    kb: KnowledgeBase,
    title: str,
    content: str,
    source_type: str = "faq",
    metadata: dict[str, Any] | None = None,
    is_faq_qa: bool = False,
    question: str | None = None,
    answer: str | None = None,
) -> Document:
    """Upsert by (kb_id, title)。

    is_faq_qa=True 且提供 question/answer 時，把 Q&A 合成單一 chunk（不依字數切）。
    其他情況用 chunk_text 切。
    """
    # 先刪舊 document（若存在），重新建立以保證 chunks 同步
    stmt = (
        select(Document)
        .options(selectinload(Document.chunks))
        .where(Document.kb_id == kb.id, Document.title == title)
    )
    result = await session.execute(stmt)
    old = result.scalar_one_or_none()
    if old:
        await _delete_chunks_from_chroma(kb, [c.embedding_ref for c in old.chunks])
        await session.delete(old)
        await session.flush()

    doc = Document(
        id=uuid.uuid4().hex,
        kb_id=kb.id,
        source_type=source_type,
        title=title,
        raw_text=content,
        doc_metadata=metadata or {},
        version=1,
        status="active",
        updated_at=_now(),
    )
    session.add(doc)
    await session.flush()

    # 切塊
    if is_faq_qa and question and answer:
        chunk_objs: list[ChunkResult] = [
            ChunkResult(text=chunk_faq_entry(question, answer))
        ]
    else:
        chunk_objs = chunk_structured(content) or [ChunkResult(text=content)]

    # 寫進 Chroma + 同步 SQLite
    collection = store.get_or_create_collection(kb.collection_name)
    ids: list[str] = []
    metadatas: list[dict] = []
    docs_for_chroma: list[str] = []
    for i, c in enumerate(chunk_objs):
        chunk_id = uuid.uuid4().hex
        ids.append(chunk_id)
        docs_for_chroma.append(c.text)
        meta = {
            "workspace_id": kb.workspace_id,
            "kb": kb.name,
            "doc_id": doc.id,
            "title": title,
            "chunk_index": i,
            **c.structural_metadata,
            **(metadata or {}),
        }
        metadatas.append(meta)
        session.add(
            Chunk(
                id=chunk_id,
                document_id=doc.id,
                chunk_index=i,
                text=c.text,
                embedding_ref=chunk_id,
            )
        )

    collection.upsert(ids=ids, documents=docs_for_chroma, metadatas=metadatas)
    await session.flush()
    log.info("Upserted document %s (%d chunks) to %s", title, len(chunk_objs), kb.collection_name)
    return doc


async def _delete_chunks_from_chroma(kb: KnowledgeBase, ids: list[str]) -> None:
    if not ids:
        return
    collection = store.get_or_create_collection(kb.collection_name)
    try:
        collection.delete(ids=ids)
    except Exception as e:  # noqa: BLE001
        log.warning("Chroma delete failed (%s): %s", kb.collection_name, e)


async def ingest_faq_json(
    session: AsyncSession,
    *,
    workspace_id: str,
    kb_name: str,
    items: list[dict],
) -> tuple[KnowledgeBase, int]:
    """格式：[{"title":..., "question":..., "answer":..., "metadata": {...}}, ...]"""
    kb = await ensure_kb(session=session, workspace_id=workspace_id, name=kb_name)
    count = 0
    for item in items:
        title = item.get("title") or item.get("question", "")[:60]
        q = item.get("question", "")
        a = item.get("answer", "")
        if not q or not a:
            continue
        await upsert_document(
            session,
            kb=kb,
            title=title,
            content=f"{q}\n\n{a}",
            source_type="faq",
            metadata=item.get("metadata", {}),
            is_faq_qa=True,
            question=q,
            answer=a,
        )
        count += 1
    return kb, count
