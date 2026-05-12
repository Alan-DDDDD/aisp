"""KM 整合測試：ingest → retrieve 端到端，用 in-memory SQLite + tempdir Chroma。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.km import ingest, retriever, store


@pytest.fixture
async def session(monkeypatch):
    tmp_chroma = tempfile.mkdtemp(prefix="aisp_chroma_")
    monkeypatch.setattr("app.config.settings.chroma_persist_dir", tmp_chroma)
    store.reset_client()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s

    await engine.dispose()
    store.reset_client()


async def test_ingest_and_search(session):
    items = [
        {
            "title": "車貸高齡",
            "question": "70 歲可以申請車貸嗎？",
            "answer": "70 歲以上可以申請，但需要保人。",
            "metadata": {"category": "loan"},
        },
        {
            "title": "客訴管道",
            "question": "怎麼提出客訴？",
            "answer": "請撥打 24 小時客服專線。",
            "metadata": {"category": "complaint"},
        },
    ]
    kb, count = await ingest.ingest_faq_json(
        session, workspace_id="test", kb_name="faq", items=items
    )
    await session.commit()

    assert count == 2
    assert kb.collection_name == "ws_test__faq"

    hits = await retriever.search(
        session,
        workspace_id="test",
        kb_name="faq",
        query="高齡車貸",
        top_k=3,
    )
    assert len(hits) >= 1
    # 高齡相關問題應該排第一
    assert "高齡" in hits[0].title or "70" in hits[0].text


async def test_workspace_isolation(session):
    """workspace_id 隔離：A workspace 看不到 B workspace 的 docs。"""
    await ingest.ingest_faq_json(
        session,
        workspace_id="ws_a",
        kb_name="faq",
        items=[
            {"title": "A doc", "question": "Q1", "answer": "Answer for A only."},
        ],
    )
    await ingest.ingest_faq_json(
        session,
        workspace_id="ws_b",
        kb_name="faq",
        items=[
            {"title": "B doc", "question": "Q1", "answer": "Answer for B only."},
        ],
    )
    await session.commit()

    hits = await retriever.search(
        session, workspace_id="ws_a", kb_name="faq", query="answer", top_k=5
    )
    titles = [h.title for h in hits]
    assert "A doc" in titles
    assert "B doc" not in titles
