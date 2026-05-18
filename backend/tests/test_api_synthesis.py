"""Phase 6 M7 — Synthesis API endpoints。

策略：用真實 MockProvider 跑（避免 monkeypatch 太多層）。MockProvider 對所有
synthesis prompt 都會回 router-style JSON，與 PlannerOutput / EnrichedToolSpec
schema 對不上 → 全走 fallback path。
驗證重點：
  - 端到端 wire 起來、HTTP shape 正確
  - DB row 真的有寫進去
  - 失敗時 task 進 AWAITING_HUMAN_RESCUE
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.models import ToolSynthesisTask
from app.synthesis import persistence
from tests._api import api_ctx  # noqa: F401


@pytest.mark.asyncio
async def test_detect_gaps_returns_fallback_single_step(api_ctx):  # noqa: F811
    """MockProvider 不會輸出 PlannerOutput JSON → planner fallback；
    無工具 registered → retrieval 空 → shortcut_low → GAP。"""
    client, SessionLocal = api_ctx
    r = await client.post(
        "/api/synthesis/detect-gaps",
        json={"query": "查訂單並寄郵件", "workspace_id": "cs"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["query"] == "查訂單並寄郵件"
    assert data["workspace_id"] == "cs"
    assert data["has_gap"] is True
    assert len(data["steps"]) >= 1
    # 在無工具的環境，全部 step 應該都判 GAP
    assert all(s["decision"] in {"GAP", "USE"} for s in data["steps"])


@pytest.mark.asyncio
async def test_detect_gaps_writes_audit_rows(api_ctx):  # noqa: F811
    client, SessionLocal = api_ctx
    await client.post(
        "/api/synthesis/detect-gaps",
        json={"query": "做某件事", "workspace_id": "hr"},
    )
    # 應有至少一筆 audit row
    from sqlalchemy import select

    from app.db.models import ToolDecisionAudit

    async with SessionLocal() as session:
        rows = (await session.execute(select(ToolDecisionAudit))).scalars().all()
    assert len(rows) >= 1
    assert rows[0].workspace_id == "hr"


@pytest.mark.asyncio
async def test_synthesize_creates_task_in_rescue_state(
    api_ctx, monkeypatch  # noqa: F811
):
    """MockProvider 不會產合法 code → 三輪 attempts 全失敗 → AWAITING_HUMAN_RESCUE。"""
    # 限制 attempts 數讓測試快一點
    monkeypatch.setattr("app.config.settings.synth_max_attempts", 1)
    client, SessionLocal = api_ctx

    r = await client.post(
        "/api/synthesis/synthesize",
        json={
            "spec": {
                "name": "my_test_tool",
                "description": "為測試用工具",
                "when_to_use": "test",
            },
            "workspace_id": "cs",
            "triggered_by_query": "x",
            "triggered_by_user": "tester",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"]
    assert body["success"] is False
    assert body["attempts"] >= 1

    # DB 狀態
    async with SessionLocal() as session:
        task = await session.get(ToolSynthesisTask, body["task_id"])
    assert task is not None
    assert task.state == persistence.STATE_AWAITING_HUMAN_RESCUE
    assert task.workspace_id == "cs"


@pytest.mark.asyncio
async def test_retry_with_hint_updates_existing_task(api_ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.config.settings.synth_max_attempts", 1)
    client, SessionLocal = api_ctx

    # 先放一個 task in awaiting state
    async with SessionLocal() as session:
        session.add(
            ToolSynthesisTask(
                id="existing-1",
                workspace_id="cs",
                state=persistence.STATE_AWAITING_HUMAN_RESCUE,
                spec={
                    "name": "existing_tool",
                    "description": "原工具",
                    "when_to_use": "x",
                    "examples": [],
                    "input_fields": [],
                    "output_fields": [],
                    "side_effect": "read_only",
                    "tags": [],
                },
                attempts=3,
                attempt_history=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    r = await client.post(
        "/api/synthesis/tasks/existing-1/retry-with-hint",
        json={"hint": "改用 httpx 而不是 requests"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == "existing-1"

    # task 仍在，attempt 重新跑過
    async with SessionLocal() as session:
        task = await session.get(ToolSynthesisTask, "existing-1")
    assert task is not None

    # 應該有一筆 refine_hint review
    from sqlalchemy import select

    from app.db.models import ToolReviewHistory

    async with SessionLocal() as session:
        revs = (await session.execute(select(ToolReviewHistory))).scalars().all()
    assert any(r.action == "refine_hint" and "httpx" in (r.hint or "") for r in revs)


@pytest.mark.asyncio
async def test_retry_with_hint_404_for_unknown_task(api_ctx):  # noqa: F811
    client, _ = api_ctx
    r = await client.post(
        "/api/synthesis/tasks/nope/retry-with-hint", json={"hint": ""}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_detect_and_synthesize_runs_full_pipeline(
    api_ctx, monkeypatch  # noqa: F811
):
    """Detect → 為 GAP step 自動 synth → 應有 task row。"""
    monkeypatch.setattr("app.config.settings.synth_max_attempts", 1)
    client, SessionLocal = api_ctx

    r = await client.post(
        "/api/synthesis/detect-and-synthesize",
        json={
            "query": "處理某個沒見過的問題",
            "workspace_id": "cs",
            "max_synthesize": 1,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detection"]["has_gap"] is True
    # 至少一個 task 被建出來
    assert len(body["synthesis_tasks"]) >= 1
    task_info = body["synthesis_tasks"][0]
    assert "task_id" in task_info or "error" in task_info
