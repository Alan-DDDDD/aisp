"""Phase 6 M2 — Gap Detector 端到端流程（含 audit log 持久化）。

用 FakeRetriever + ScriptedProvider 避免真實 LLM 與真實 embedding 模型。
重點：
- shortcut_high / shortcut_low 路徑不該叫到 judge
- 灰色區會叫 judge；判給定區間外時 review 介入
- 每個 step 都寫到 tool_decisions_audit
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import models  # noqa: F401 — register tables
from app.db.database import Base
from app.db.models import ToolDecisionAudit
from app.synthesis.gap_detector import GapDetector
from app.synthesis.schemas import DecisionRoute, DecisionType, ToolCandidate
from tests._fakes import FakeRetriever, ScriptedProvider


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


async def test_high_similarity_shortcut_skips_judge(session: AsyncSession):
    """retrieval similarity >= 0.85 → 直接 USE，不該叫到 judge LLM。"""
    planner_resp = (
        '{"steps": [{"id": "s1", "description": "查 FAQ 看車貸資格", "requires_tool": true}]}'
    )
    provider = ScriptedProvider([planner_resp])  # 只有 planner 一次 call

    retriever = FakeRetriever()
    retriever.set(
        "查 FAQ 看車貸資格",
        [ToolCandidate(tool_id="kb_search", similarity=0.92, description="FAQ search")],
    )

    detector = GapDetector(provider=provider, retriever=retriever)
    result = await detector.detect("車貸怎麼申請", session=session)

    assert len(result.steps) == 1
    assert result.steps[0].decision is DecisionType.USE
    assert result.steps[0].tool_id == "kb_search"
    assert result.steps[0].route is DecisionRoute.SHORTCUT_HIGH
    # provider 只該被 planner 用一次，沒人叫 judge
    assert len(provider.calls) == 1


async def test_low_similarity_shortcut_produces_gap(session: AsyncSession):
    """retrieval similarity <= 0.40 → 直接 GAP，不該叫到 judge LLM。"""
    planner_resp = (
        '{"steps": [{"id": "s1", "description": "送 SMS 給客戶", "requires_tool": true}]}'
    )
    provider = ScriptedProvider([planner_resp])

    retriever = FakeRetriever()
    retriever.set(
        "送 SMS 給客戶",
        [ToolCandidate(tool_id="kb_search", similarity=0.20, description="FAQ")],
    )

    detector = GapDetector(provider=provider, retriever=retriever)
    result = await detector.detect("通知客戶", session=session)

    assert result.steps[0].decision is DecisionType.GAP
    assert result.steps[0].route is DecisionRoute.SHORTCUT_LOW
    assert result.steps[0].gap_spec is not None
    assert result.has_gap is True


async def test_gray_zone_routes_through_judge_to_use(session: AsyncSession):
    """0.40 < similarity < 0.85 → 進 judge；judge confidence >= 0.85 不問人類。"""
    planner_resp = (
        '{"steps": [{"id": "s1", "description": "查產品 FAQ", "requires_tool": true}]}'
    )
    judge_resp = (
        '{"decisions": [{"step_id": "s1", "decision": "USE", "tool_id": "kb_search",'
        ' "confidence": 0.90, "reasoning": "FAQ 用 kb_search 沒問題"}]}'
    )
    provider = ScriptedProvider([planner_resp, judge_resp])

    retriever = FakeRetriever()
    retriever.set(
        "查產品 FAQ",
        [ToolCandidate(tool_id="kb_search", similarity=0.65, description="FAQ search")],
    )

    detector = GapDetector(provider=provider, retriever=retriever)
    result = await detector.detect("問 FAQ", session=session)

    assert result.steps[0].decision is DecisionType.USE
    assert result.steps[0].route is DecisionRoute.JUDGE
    # 兩次 call：planner + judge
    assert len(provider.calls) == 2


async def test_gray_zone_with_mid_confidence_invokes_review(session: AsyncSession):
    """Judge 回 confidence 落在灰色區（0.4-0.85）→ 走 HUMAN 路徑（AutoDecideReview）。"""
    planner_resp = (
        '{"steps": [{"id": "s1", "description": "查某種模糊問題", "requires_tool": true}]}'
    )
    judge_resp = (
        '{"decisions": [{"step_id": "s1", "decision": "USE", "tool_id": "kb_search",'
        ' "confidence": 0.55}]}'
    )
    provider = ScriptedProvider([planner_resp, judge_resp])

    retriever = FakeRetriever()
    retriever.set(
        "查某種模糊問題",
        [ToolCandidate(tool_id="kb_search", similarity=0.55, description="x")],
    )

    detector = GapDetector(provider=provider, retriever=retriever)
    result = await detector.detect("?", session=session)

    # AutoDecideReview 會直接採信 judge 既有決策，但 route 標記為 HUMAN
    assert result.steps[0].route is DecisionRoute.HUMAN
    assert result.steps[0].decision is DecisionType.USE


async def test_no_tool_needed_step_short_circuits(session: AsyncSession):
    """planner 標 requires_tool=false 的 step 不該觸發 retrieval / judge。"""
    planner_resp = (
        '{"steps": ['
        '{"id": "s1", "description": "查 FAQ", "requires_tool": true},'
        '{"id": "s2", "description": "把答案組成回覆", "requires_tool": false}'
        ']}'
    )
    provider = ScriptedProvider([planner_resp])  # 沒有 judge call

    retriever = FakeRetriever()
    retriever.set(
        "查 FAQ",
        [ToolCandidate(tool_id="kb_search", similarity=0.92, description="x")],
    )

    detector = GapDetector(provider=provider, retriever=retriever)
    result = await detector.detect("?", session=session)

    assert result.steps[1].route is DecisionRoute.NO_TOOL_NEEDED
    assert result.steps[1].tool_id is None


async def test_audit_log_written_for_every_step(session: AsyncSession):
    planner_resp = (
        '{"steps": ['
        '{"id": "s1", "description": "查 FAQ", "requires_tool": true},'
        '{"id": "s2", "description": "回覆", "requires_tool": false}'
        ']}'
    )
    provider = ScriptedProvider([planner_resp])

    retriever = FakeRetriever()
    retriever.set(
        "查 FAQ",
        [ToolCandidate(tool_id="kb_search", similarity=0.95, description="x")],
    )

    detector = GapDetector(provider=provider, retriever=retriever)
    result = await detector.detect("?", workspace_id="cs", session=session)

    rows = (await session.execute(select(ToolDecisionAudit))).scalars().all()
    assert len(rows) == 2
    assert {r.step_id for r in rows} == {"s1", "s2"}
    # query_id 一致
    assert {r.query_id for r in rows} == {result.query_id}
    # workspace 帶下來
    assert {r.workspace_id for r in rows} == {"cs"}
