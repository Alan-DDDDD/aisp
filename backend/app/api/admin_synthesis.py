"""Phase 6 — Admin 觀測 endpoints（PLAN §22 audit trail）。

獨立成 module 避免 admin.py 越長越胖。掛在同個 /api/admin 前綴下。

設計：
- 回傳資料保留 raw 結構（dict / list），給 admin UI 任意展開
- 都帶分頁與 workspace filter（多租戶觀測）
- 不暴露完整 source code（要看 code 走 /tasks/{id}/source）—— 避免列表太肥
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.db.models import (
    GeneratedTool,
    ToolDecisionAudit,
    ToolReviewHistory,
    ToolSynthesisTask,
)

router = APIRouter(prefix="/api/admin", tags=["admin", "synthesis"])


# ── Synthesis tasks ─────────────────────────────────────────────────


def _task_to_summary(t: ToolSynthesisTask) -> dict:
    spec = t.spec or {}
    return {
        "id": t.id,
        "workspace_id": t.workspace_id,
        "state": t.state,
        "tool_name": spec.get("name"),
        "description": spec.get("description"),
        "attempts": t.attempts,
        "model_used": t.model_used,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _task_to_detail(t: ToolSynthesisTask) -> dict:
    base = _task_to_summary(t)
    base.update(
        {
            "spec": t.spec,
            "attempt_history": t.attempt_history,
            "last_error": t.last_error,
            "behavior_observation": t.behavior_observation,
            "triggered_by_query_id": t.triggered_by_query_id,
            "triggered_by_decision_id": t.triggered_by_decision_id,
            "has_code": bool(t.code),
            "has_tests": bool(t.tests),
        }
    )
    return base


@router.get("/synthesis-tasks")
async def list_synthesis_tasks(
    workspace_id: str | None = None,
    state: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    stmt = (
        select(ToolSynthesisTask)
        .order_by(ToolSynthesisTask.created_at.desc())
        .limit(limit)
    )
    if workspace_id:
        stmt = stmt.where(ToolSynthesisTask.workspace_id == workspace_id)
    if state:
        stmt = stmt.where(ToolSynthesisTask.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    return [_task_to_summary(t) for t in rows]


@router.get("/synthesis-tasks/{task_id}")
async def get_synthesis_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    t = await session.get(ToolSynthesisTask, task_id)
    if t is None:
        raise HTTPException(404, f"task {task_id} not found")
    return _task_to_detail(t)


@router.get("/synthesis-tasks/{task_id}/source")
async def get_synthesis_source(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """單獨取 code/tests，避免列表 / detail 太肥。"""
    t = await session.get(ToolSynthesisTask, task_id)
    if t is None:
        raise HTTPException(404, f"task {task_id} not found")
    return {"task_id": task_id, "code": t.code or "", "tests": t.tests or ""}


@router.get("/synthesis-tasks/{task_id}/reviews")
async def get_synthesis_reviews(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    stmt = (
        select(ToolReviewHistory)
        .where(ToolReviewHistory.task_id == task_id)
        .order_by(ToolReviewHistory.created_at)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "reviewer": r.reviewer,
            "hint": r.hint,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── Decision audit ─────────────────────────────────────────────────


@router.get("/decision-audit")
async def list_decision_audit(
    workspace_id: str | None = None,
    decision: str | None = None,
    route: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Phase A 每次 USE/COMPOSE/GAP 決策的 log。"""
    stmt = (
        select(ToolDecisionAudit)
        .order_by(ToolDecisionAudit.created_at.desc())
        .limit(limit)
    )
    if workspace_id:
        stmt = stmt.where(ToolDecisionAudit.workspace_id == workspace_id)
    if decision:
        stmt = stmt.where(ToolDecisionAudit.decision == decision)
    if route:
        stmt = stmt.where(ToolDecisionAudit.route == route)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "query_id": r.query_id,
            "step_id": r.step_id,
            "step_description": r.step_description,
            "workspace_id": r.workspace_id,
            "decision": r.decision,
            "tool_id": r.tool_id,
            "compose_chain": r.compose_chain,
            "gap_spec_name": (r.gap_spec or {}).get("name") if r.gap_spec else None,
            "confidence": r.confidence,
            "max_similarity": r.max_similarity,
            "route": r.route,
            "model_used": r.model_used,
            "reasoning": r.reasoning,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── Generated tools ────────────────────────────────────────────────


@router.get("/generated-tools")
async def list_generated_tools(
    workspace_id: str | None = None,
    status: str | None = Query(default="active"),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    stmt = (
        select(GeneratedTool)
        .order_by(GeneratedTool.approved_at.desc())
        .limit(limit)
    )
    if workspace_id:
        stmt = stmt.where(GeneratedTool.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(GeneratedTool.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "version": r.version,
            "workspace_id": r.workspace_id,
            "scope": r.scope,
            "status": r.status,
            "description": r.description,
            "side_effect": r.side_effect,
            "requires_approval": r.requires_approval,
            "tags": r.tags,
            "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "synthesis_task_id": r.synthesis_task_id,
        }
        for r in rows
    ]


@router.post("/generated-tools/{tool_id}/promote-global")
async def promote_to_global(
    tool_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把 workspace-scoped tool 升級為 global（PLAN §22.5.8）。

    M7 骨架：只改 DB scope 與 registry workspace；不重新 reindex retriever
    （現有 entry 仍可工作，重啟後 load_all_active 會帶新 scope 進來）。
    """
    from app.tools import registry as tool_registry

    row = await session.get(GeneratedTool, tool_id)
    if row is None:
        raise HTTPException(404, f"generated tool {tool_id} not found")
    row.scope = "global"
    row.workspace_id = None
    await session.commit()

    # 同步 process 內 registry（unregister + 重新 register 為 global）
    if tool_id in tool_registry.list_ids():
        tool_obj = tool_registry.get(tool_id)
        tool_registry.unregister(tool_id)
        tool_registry.register(tool_obj, workspace_id=None)

    return {"tool_id": tool_id, "scope": "global"}


@router.post("/generated-tools/{tool_id}/deprecate")
async def deprecate_tool(
    tool_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """標 deprecated（不會再 hot-reload，但既有 process 仍可呼叫）。"""
    row = await session.get(GeneratedTool, tool_id)
    if row is None:
        raise HTTPException(404, f"generated tool {tool_id} not found")
    row.status = "deprecated"
    await session.commit()
    return {"tool_id": tool_id, "status": "deprecated"}
