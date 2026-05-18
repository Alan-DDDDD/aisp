"""Phase 6 M1 — 新增 DB tables 能正確建立且可寫入。

只測「建表 + insert + select」的 contract，不測業務邏輯（M2 之後的事）。
用 in-memory SQLite 避免污染本機 dev DB。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import models  # noqa: F401 — register tables before create_all
from app.db.database import Base
from app.db.models import (
    GeneratedTool,
    ToolDecisionAudit,
    ToolReviewHistory,
    ToolSynthesisTask,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


async def test_tool_decisions_audit_roundtrip(session: AsyncSession):
    row = ToolDecisionAudit(
        id="dec-1",
        query_id="q-1",
        step_id="s-1",
        step_description="從 customer_id 取得最近 30 天的訂單",
        workspace_id="cs",
        decision="GAP",
        confidence=0.32,
        candidates=[{"id": "kb_search", "score": 0.61}],
        max_similarity=0.61,
        reasoning="既有工具無法做時間範圍篩選",
        route="shortcut_low",
        model_used="llama-3.1-8b-instant",
        gap_spec={"name": "get_customer_orders_recent", "description": "..."},
    )
    session.add(row)
    await session.commit()

    fetched = await session.get(ToolDecisionAudit, "dec-1")
    assert fetched is not None
    assert fetched.decision == "GAP"
    assert fetched.candidates[0]["id"] == "kb_search"
    assert fetched.gap_spec["name"] == "get_customer_orders_recent"


async def test_synthesis_task_state_machine_columns(session: AsyncSession):
    task = ToolSynthesisTask(
        id="task-1",
        workspace_id="cs",
        state="CODE_GENERATING",
        spec={"id": "foo", "description": "bar"},
        attempts=1,
        attempt_history=[{"round": 1, "error": "ImportError"}],
        last_error="ImportError: requests",
    )
    session.add(task)
    await session.commit()

    fetched = await session.get(ToolSynthesisTask, "task-1")
    assert fetched is not None
    assert fetched.state == "CODE_GENERATING"
    assert fetched.attempts == 1
    assert fetched.attempt_history[0]["round"] == 1


async def test_generated_tool_default_scope_is_workspace(session: AsyncSession):
    task = ToolSynthesisTask(
        id="task-2",
        workspace_id="hr",
        state="REGISTERED",
    )
    session.add(task)
    await session.flush()

    tool = GeneratedTool(
        id="get_leave_balance",
        synthesis_task_id="task-2",
        workspace_id="hr",
        description="查員工剩餘特休",
        source_path="tools/generated/get_leave_balance.py",
        approved_by="alan",
        approved_at=datetime.now(UTC),
    )
    session.add(tool)
    await session.commit()

    fetched = await session.get(GeneratedTool, "get_leave_balance")
    assert fetched is not None
    assert fetched.scope == "workspace"  # 預設 scoped，需明確 promote 才 global
    assert fetched.status == "active"


async def test_tool_review_history_roundtrip(session: AsyncSession):
    task = ToolSynthesisTask(id="task-3", workspace_id="it", state="AWAITING_APPROVAL")
    session.add(task)
    await session.flush()

    review = ToolReviewHistory(
        id="rev-1",
        task_id="task-3",
        action="refine_hint",
        reviewer="telegram:12345",
        hint="請改用 httpx 而不是 requests",
    )
    session.add(review)
    await session.commit()

    fetched = await session.get(ToolReviewHistory, "rev-1")
    assert fetched is not None
    assert fetched.action == "refine_hint"
    assert "httpx" in fetched.hint
