"""Phase 6 M7 — Admin observability endpoints。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.models import (
    GeneratedTool,
    ToolDecisionAudit,
    ToolReviewHistory,
    ToolSynthesisTask,
)
from tests._api import api_ctx  # noqa: F401 — fixture import


@pytest.mark.asyncio
async def test_list_synthesis_tasks_filters(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    async with SessionLocal() as session:
        session.add_all(
            [
                ToolSynthesisTask(
                    id="t1",
                    workspace_id="cs",
                    state="AWAITING_APPROVAL",
                    spec={"name": "tool_a", "description": "x"},
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                ToolSynthesisTask(
                    id="t2",
                    workspace_id="hr",
                    state="REGISTERED",
                    spec={"name": "tool_b", "description": "y"},
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

    r = await client.get("/api/admin/synthesis-tasks")
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = await client.get("/api/admin/synthesis-tasks", params={"workspace_id": "cs"})
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == ["t1"]

    r = await client.get(
        "/api/admin/synthesis-tasks", params={"state": "REGISTERED"}
    )
    assert [t["id"] for t in r.json()] == ["t2"]


@pytest.mark.asyncio
async def test_synthesis_task_detail_and_source(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    async with SessionLocal() as session:
        session.add(
            ToolSynthesisTask(
                id="t1",
                workspace_id="cs",
                state="AWAITING_APPROVAL",
                spec={"name": "tool_a"},
                code="class X: pass",
                tests="def test_x(): pass",
                attempts=2,
                attempt_history=[{"round": 1}],
                last_error=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    r = await client.get("/api/admin/synthesis-tasks/t1")
    assert r.status_code == 200
    detail = r.json()
    assert detail["tool_name"] == "tool_a"
    assert detail["has_code"] is True
    assert detail["has_tests"] is True
    assert detail["attempts"] == 2

    r = await client.get("/api/admin/synthesis-tasks/t1/source")
    assert r.status_code == 200
    assert r.json()["code"] == "class X: pass"

    r = await client.get("/api/admin/synthesis-tasks/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reviews_endpoint(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    async with SessionLocal() as session:
        session.add(
            ToolSynthesisTask(id="t1", workspace_id="cs", state="REGISTERED")
        )
        session.add_all(
            [
                ToolReviewHistory(
                    id="r1",
                    task_id="t1",
                    action="approve",
                    reviewer="telegram:1",
                    created_at=datetime.now(UTC),
                ),
                ToolReviewHistory(
                    id="r2",
                    task_id="t1",
                    action="refine_hint",
                    reviewer="telegram:1",
                    hint="改用 httpx",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

    r = await client.get("/api/admin/synthesis-tasks/t1/reviews")
    assert r.status_code == 200
    actions = [x["action"] for x in r.json()]
    assert set(actions) == {"approve", "refine_hint"}


@pytest.mark.asyncio
async def test_decision_audit_filters(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    async with SessionLocal() as session:
        session.add_all(
            [
                ToolDecisionAudit(
                    id="d1",
                    query_id="q1",
                    step_id="s1",
                    step_description="x",
                    workspace_id="cs",
                    decision="USE",
                    tool_id="kb_search",
                    confidence=0.9,
                    max_similarity=0.9,
                    route="shortcut_high",
                    created_at=datetime.now(UTC),
                ),
                ToolDecisionAudit(
                    id="d2",
                    query_id="q2",
                    step_id="s2",
                    step_description="x",
                    workspace_id="hr",
                    decision="GAP",
                    gap_spec={"name": "new_tool"},
                    confidence=0.3,
                    max_similarity=0.3,
                    route="shortcut_low",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

    r = await client.get("/api/admin/decision-audit")
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = await client.get(
        "/api/admin/decision-audit", params={"decision": "GAP"}
    )
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["gap_spec_name"] == "new_tool"
    assert rows[0]["route"] == "shortcut_low"


@pytest.mark.asyncio
async def test_generated_tools_list_and_promote(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    async with SessionLocal() as session:
        session.add(
            ToolSynthesisTask(id="t1", workspace_id="cs", state="REGISTERED")
        )
        session.add(
            GeneratedTool(
                id="my_tool",
                version="1.0.0",
                synthesis_task_id="t1",
                workspace_id="cs",
                scope="workspace",
                description="d",
                source_path="/tmp/x.py",
                approved_by="telegram:1",
                approved_at=datetime.now(UTC),
                status="active",
            )
        )
        await session.commit()

    r = await client.get("/api/admin/generated-tools")
    assert r.status_code == 200
    tools = r.json()
    assert len(tools) == 1
    assert tools[0]["scope"] == "workspace"

    # promote 至 global
    r = await client.post("/api/admin/generated-tools/my_tool/promote-global")
    assert r.status_code == 200
    assert r.json()["scope"] == "global"

    # 確認 DB 同步
    async with SessionLocal() as session:
        row = await session.get(GeneratedTool, "my_tool")
        assert row.scope == "global"
        assert row.workspace_id is None


@pytest.mark.asyncio
async def test_generated_tool_deprecate(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    async with SessionLocal() as session:
        session.add(
            ToolSynthesisTask(id="t1", workspace_id="cs", state="REGISTERED")
        )
        session.add(
            GeneratedTool(
                id="my_tool",
                synthesis_task_id="t1",
                workspace_id="cs",
                description="d",
                source_path="/tmp/x.py",
                approved_by="x",
                approved_at=datetime.now(UTC),
                status="active",
            )
        )
        await session.commit()

    r = await client.post("/api/admin/generated-tools/my_tool/deprecate")
    assert r.status_code == 200
    assert r.json()["status"] == "deprecated"

    r = await client.get(
        "/api/admin/generated-tools", params={"status": "active"}
    )
    assert r.json() == []
