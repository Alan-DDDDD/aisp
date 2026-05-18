"""Synthesis state persistence — tool_synthesis_tasks 的 CRUD（PLAN §22.8）。

職責：把 SynthesisResult / 每輪 attempt / state machine 轉移寫進 DB。
所有 task 的長期狀態都靠這個 module；in-process 變數只用於短期協調（PendingRequests）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolReviewHistory, ToolSynthesisTask
from app.synthesis.orchestrator import SynthesisResult

log = logging.getLogger(__name__)


# State machine state 名稱（PLAN §22.8）。文字寫死避免 enum / DB 不同步。
STATE_GAP_DETECTED = "GAP_DETECTED"
STATE_SPEC_GENERATING = "SPEC_GENERATING"
STATE_CODE_GENERATING = "CODE_GENERATING"
STATE_TESTS_GENERATING = "TESTS_GENERATING"
STATE_STATIC_CHECK = "STATIC_CHECK"
STATE_SANDBOX_RUNNING = "SANDBOX_RUNNING"
STATE_AWAITING_HUMAN_RESCUE = "AWAITING_HUMAN_RESCUE"
STATE_AWAITING_APPROVAL = "AWAITING_APPROVAL"
STATE_REGISTERED = "REGISTERED"
STATE_DISCARDED = "DISCARDED"
STATE_FAILED = "FAILED"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _now() -> datetime:
    return datetime.now(UTC)


# ── 主要寫入點 ───────────────────────────────────────────────────────


async def create_task(
    session: AsyncSession,
    *,
    spec: dict,
    workspace_id: str,
    triggered_by_query_id: str | None = None,
    triggered_by_decision_id: str | None = None,
    model_used: str | None = None,
) -> ToolSynthesisTask:
    task = ToolSynthesisTask(
        id=_new_id("syn"),
        triggered_by_query_id=triggered_by_query_id,
        triggered_by_decision_id=triggered_by_decision_id,
        workspace_id=workspace_id,
        state=STATE_GAP_DETECTED,
        spec=spec,
        attempts=0,
        attempt_history=[],
        model_used=model_used,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(task)
    await session.commit()
    return task


async def save_synthesis_outcome(
    session: AsyncSession,
    task_id: str,
    result: SynthesisResult,
) -> ToolSynthesisTask:
    """把 SynthesisOrchestrator 的 final result 寫進 DB。

    - success=True  → AWAITING_APPROVAL（等人類審）
    - success=False → AWAITING_HUMAN_RESCUE（給人選 retry/hint/abandon）
    """
    task = await _require(session, task_id)
    task.spec = result.spec_enriched.model_dump()
    task.code = result.final_code
    task.tests = result.tests
    task.attempts = result.attempt_count
    task.attempt_history = [_attempt_to_dict(a) for a in result.attempts]
    task.last_error = result.error
    if result.sandbox_result is not None:
        task.behavior_observation = {
            "observations": result.sandbox_result.observations,
            "passed": result.sandbox_result.passed,
            "failed": result.sandbox_result.failed,
        }
    task.state = STATE_AWAITING_APPROVAL if result.success else STATE_AWAITING_HUMAN_RESCUE
    task.updated_at = _now()
    await session.commit()
    return task


async def transition(
    session: AsyncSession,
    task_id: str,
    new_state: str,
    *,
    last_error: str | None = None,
) -> ToolSynthesisTask:
    task = await _require(session, task_id)
    task.state = new_state
    if last_error is not None:
        task.last_error = last_error
    task.updated_at = _now()
    await session.commit()
    return task


async def record_review(
    session: AsyncSession,
    *,
    task_id: str,
    action: str,
    reviewer: str,
    hint: str | None = None,
    note: str = "",
) -> ToolReviewHistory:
    row = ToolReviewHistory(
        id=_new_id("rev"),
        task_id=task_id,
        action=action,
        reviewer=reviewer,
        hint=hint,
        note=note,
        created_at=_now(),
    )
    session.add(row)
    await session.commit()
    return row


# ── 讀取 ─────────────────────────────────────────────────────────────


async def get_task(session: AsyncSession, task_id: str) -> ToolSynthesisTask | None:
    return await session.get(ToolSynthesisTask, task_id)


async def list_awaiting_approval(
    session: AsyncSession,
    workspace_id: str | None = None,
) -> list[ToolSynthesisTask]:
    """app 啟動時、admin 介面可用。"""
    stmt = select(ToolSynthesisTask).where(
        ToolSynthesisTask.state == STATE_AWAITING_APPROVAL
    )
    if workspace_id is not None:
        stmt = stmt.where(ToolSynthesisTask.workspace_id == workspace_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


# ── 工具函式 ────────────────────────────────────────────────────────


async def _require(session: AsyncSession, task_id: str) -> ToolSynthesisTask:
    task = await session.get(ToolSynthesisTask, task_id)
    if task is None:
        raise KeyError(f"ToolSynthesisTask not found: {task_id}")
    return task


def _attempt_to_dict(attempt) -> dict:
    """SynthesisAttempt → JSON-safe dict（attempt_history 是 JSON column）。

    包含 exit_code 與 stderr/stdout tail 方便事後 audit；無需另跑 debug script。
    """
    sandbox = attempt.sandbox
    return {
        "round": attempt.round,
        "static_ok": attempt.static_ok,
        "static_errors": list(attempt.static_errors),
        "feedback_used": attempt.feedback_used,
        "sandbox_exit_code": sandbox.exit_code if sandbox else None,
        "sandbox_passed": sandbox.passed if sandbox else None,
        "sandbox_failed": sandbox.failed if sandbox else None,
        "sandbox_errors": sandbox.errors if sandbox else None,
        "sandbox_failure_messages": (
            list(sandbox.failure_messages)[:5] if sandbox else []
        ),
        # 截 2KB 通常夠看 ImportError / collection error
        "sandbox_stderr_tail": (sandbox.stderr or "")[-2000:] if sandbox else "",
        "sandbox_stdout_tail": (sandbox.stdout or "")[-2000:] if sandbox else "",
    }


def attempt_history_summary(attempts: Iterable[dict]) -> str:
    """給 rescue 訊息用：把 attempt_history 格式化成短列表。"""
    parts: list[str] = []
    for a in attempts:
        rd = a.get("round")
        if not a.get("static_ok"):
            errs = ", ".join(a.get("static_errors", [])[:2])
            parts.append(f"R{rd}: static failed - {errs}")
        elif a.get("sandbox_failed"):
            msgs = a.get("sandbox_failure_messages") or []
            parts.append(f"R{rd}: {a.get('sandbox_failed')} test(s) failed{' - ' + msgs[0] if msgs else ''}")
        else:
            parts.append(f"R{rd}: 通過")
    return "\n".join(parts)
