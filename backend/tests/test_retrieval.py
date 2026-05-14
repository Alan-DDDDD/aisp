"""Hybrid retrieval、BM25 索引、RRF 融合、eval 度量單元測試。"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base
from app.km import bm25_index, eval as eval_mod, ingest, retriever, store
from app.km.retriever import _rrf_fuse
from app.schemas.knowledge import KnowledgeSearchHit


# ──────────────────────────────────────────────────────────────────────────
# BM25 tokenization
# ──────────────────────────────────────────────────────────────────────────


def test_tokenize_chinese_uses_jieba_words():
    tokens = bm25_index.tokenize("70歲申請車貸")
    # jieba 至少會切出「車貸」「申請」這類詞，不是純單字
    assert "車貸" in tokens
    assert any(t == "申請" for t in tokens)
    # 數字保留
    assert "70" in tokens


def test_tokenize_english_lowercase():
    tokens = bm25_index.tokenize("VPN AnyConnect Login")
    assert "vpn" in tokens
    assert "anyconnect" in tokens
    assert "login" in tokens


def test_tokenize_mixed():
    tokens = bm25_index.tokenize("申請 AWS 權限")
    assert "申請" in tokens
    assert "aws" in tokens
    assert "權限" in tokens


def test_tokenize_empty():
    assert bm25_index.tokenize("") == []
    assert bm25_index.tokenize("   ") == []


# ──────────────────────────────────────────────────────────────────────────
# RRF fusion
# ──────────────────────────────────────────────────────────────────────────


def _hit(chunk_id: str, title: str = "", score: float = 0.5) -> KnowledgeSearchHit:
    return KnowledgeSearchHit(
        chunk_id=chunk_id,
        document_id="d",
        title=title,
        text=f"text for {chunk_id}",
        score=score,
        metadata={},
    )


def test_rrf_fuse_combines_two_rankings():
    dense = [_hit("a"), _hit("b"), _hit("c")]
    sparse = [_hit("c"), _hit("a"), _hit("d")]
    fused = _rrf_fuse([dense, sparse], k=60, top_k=10)
    ids = [h.chunk_id for h in fused]
    # a 與 c 都被兩個 ranking 排在前面，應該名列前茅
    assert ids[0] in {"a", "c"}
    assert ids[1] in {"a", "c"}
    # 全部 unique
    assert len(ids) == len(set(ids))
    # 每個 hit 的 metadata 應該帶 rrf_score
    for h in fused:
        assert "rrf_score" in h.metadata


def test_rrf_higher_rank_gets_higher_score():
    dense = [_hit("a"), _hit("b")]
    sparse: list = []
    fused = _rrf_fuse([dense, sparse], k=60, top_k=10)
    # a 在 rank 1 應該分數高於 rank 2 的 b
    a_score = next(h.metadata["rrf_score"] for h in fused if h.chunk_id == "a")
    b_score = next(h.metadata["rrf_score"] for h in fused if h.chunk_id == "b")
    assert a_score > b_score


def test_rrf_respects_top_k():
    dense = [_hit(str(i)) for i in range(10)]
    fused = _rrf_fuse([dense], k=60, top_k=3)
    assert len(fused) == 3


# ──────────────────────────────────────────────────────────────────────────
# Eval metrics
# ──────────────────────────────────────────────────────────────────────────


def _result_hit(title: str) -> SimpleNamespace:
    return SimpleNamespace(title=title)


def test_recall_at_k_partial():
    hits = [_result_hit("車貸高齡客戶處理"), _result_hit("無關")]
    expected = ["車貸高齡客戶處理", "另一個答案"]
    # 命中 1/2 期望
    assert eval_mod.recall_at_k(hits, expected, 5) == 0.5


def test_precision_at_k():
    hits = [_result_hit("命中"), _result_hit("無關"), _result_hit("命中")]
    expected = ["命中"]
    # 前 3 筆中有 2 筆 title 含「命中」→ 2/3
    assert round(eval_mod.precision_at_k(hits, expected, 3), 3) == round(2 / 3, 3)


def test_mrr_first_hit_rank_2():
    hits = [_result_hit("漏掉"), _result_hit("命中"), _result_hit("漏掉")]
    expected = ["命中"]
    assert eval_mod.mrr(hits, expected) == 0.5  # 1/2


def test_mrr_no_hit_returns_zero():
    hits = [_result_hit("a"), _result_hit("b")]
    expected = ["c"]
    assert eval_mod.mrr(hits, expected) == 0.0


def test_hit_rate_at_k_binary():
    hits = [_result_hit("a"), _result_hit("命中")]
    assert eval_mod.hit_rate_at_k(hits, ["命中"], 5) == 1.0
    assert eval_mod.hit_rate_at_k(hits, ["不存在"], 5) == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Hybrid e2e（in-memory SQLite + tempdir Chroma）
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def session(monkeypatch):
    tmp_chroma = tempfile.mkdtemp(prefix="aisp_chroma_")
    monkeypatch.setattr("app.config.settings.chroma_persist_dir", tmp_chroma)
    store.reset_client()
    bm25_index.reset()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s

    await engine.dispose()
    store.reset_client()
    bm25_index.reset()


async def test_hybrid_retrieval_returns_results(session):
    items = [
        {
            "title": "車貸高齡",
            "question": "70 歲可以申請車貸嗎？",
            "answer": "70 歲以上可以申請，但需要保人。",
        },
        {
            "title": "客訴管道",
            "question": "怎麼提出客訴？",
            "answer": "請撥打 24 小時客服專線。",
        },
        {
            "title": "車貸利率",
            "question": "車貸利率多少？",
            "answer": "新車貸款利率為 3.5%–8.5%。",
        },
    ]
    await ingest.ingest_faq_json(
        session, workspace_id="test", kb_name="faq", items=items
    )
    await session.commit()

    # dense
    dense_hits = await retriever.search(
        session,
        workspace_id="test",
        kb_name="faq",
        query="高齡車貸",
        top_k=3,
        mode="dense",
    )
    assert len(dense_hits) >= 1

    # bm25
    bm25_hits = await retriever.search(
        session,
        workspace_id="test",
        kb_name="faq",
        query="客訴",
        top_k=3,
        mode="bm25",
    )
    assert any("客訴" in h.title for h in bm25_hits)
    # BM25-only hit 的 metadata 應該含 bm25_score
    assert any("bm25_score" in (h.metadata or {}) for h in bm25_hits)

    # hybrid
    hybrid_hits = await retriever.search(
        session,
        workspace_id="test",
        kb_name="faq",
        query="高齡車貸",
        top_k=3,
        mode="hybrid",
    )
    assert len(hybrid_hits) >= 1
    # hybrid 結果應該有 rrf_score
    assert any("rrf_score" in (h.metadata or {}) for h in hybrid_hits)


async def test_hybrid_respects_workspace_isolation(session):
    await ingest.ingest_faq_json(
        session,
        workspace_id="ws_a",
        kb_name="faq",
        items=[{"title": "A doc", "question": "Q1", "answer": "Only A."}],
    )
    await ingest.ingest_faq_json(
        session,
        workspace_id="ws_b",
        kb_name="faq",
        items=[{"title": "B doc", "question": "Q1", "answer": "Only B."}],
    )
    await session.commit()

    hits = await retriever.search(
        session,
        workspace_id="ws_a",
        kb_name="faq",
        query="answer",
        top_k=5,
        mode="hybrid",
    )
    titles = [h.title for h in hits]
    assert "A doc" in titles
    assert "B doc" not in titles
