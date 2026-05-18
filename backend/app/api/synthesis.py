"""Phase 6 — Synthesis API endpoints（PLAN §22）。

四個入口：
  POST /api/synthesis/detect-gaps         Phase A：query → 拆 steps 並判 USE/COMPOSE/GAP
  POST /api/synthesis/synthesize          Phase B：給 spec → 跑 Code Agent → submit 審核
  POST /api/synthesis/detect-and-synthesize  方便用：detect-gaps 後對所有 GAP 一鍵 synth
  POST /api/synthesis/tasks/{id}/retry-with-hint  人類 refine 後重跑

所有非同步操作仍受 Phase 6 流程約束：
- detect-gaps 在灰色區會嘗試走 TelegramReview（若 token 已設）
- synthesize 完成後一定把結果交給 ApprovalService.submit
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_session
from app.providers.factory import get_provider
from app.synthesis import integration, persistence
from app.synthesis.gap_detector import GapDetector
from app.synthesis.orchestrator import SynthesisOrchestrator
from app.synthesis.schemas import (
    DecisionType,
    EnrichedToolSpec,
    GapDetectionResult,
    ToolSpec,
)

log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/synthesis", tags=["synthesis"])


# ── /detect-gaps ────────────────────────────────────────────────────


class DetectGapsRequest(BaseModel):
    query: str
    workspace_id: str = "default"
    # 灰色區是否導到 Telegram；token 沒設時自動 fallback 為 AutoDecideReview
    use_telegram_review: bool = False


@router.post("/detect-gaps")
async def detect_gaps(
    req: DetectGapsRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    review = None
    if req.use_telegram_review and settings.tg_bot_token:
        review = integration.get_telegram_review()

    detector = GapDetector(
        provider=get_provider(),
        retriever=integration.get_retriever(),
        review=review,
    )
    result = await detector.detect(req.query, workspace_id=req.workspace_id, session=session)
    return _gap_result_to_dict(result)


# ── /synthesize ─────────────────────────────────────────────────────


class SynthesizeRequest(BaseModel):
    spec: ToolSpec
    workspace_id: str = "default"
    triggered_by_query: str = ""
    triggered_by_user: str = "api"
    triggered_by_query_id: str | None = None
    triggered_by_decision_id: str | None = None


@router.post("/synthesize")
async def synthesize(
    req: SynthesizeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    orch = SynthesisOrchestrator(provider=get_provider())
    result = await orch.synthesize(req.spec)
    task_id = await integration.get_approval_service().submit(
        session,
        result=result,
        workspace_id=req.workspace_id,
        triggered_by_query=req.triggered_by_query,
        triggered_by_user=req.triggered_by_user,
        triggered_by_query_id=req.triggered_by_query_id,
        triggered_by_decision_id=req.triggered_by_decision_id,
    )
    return {
        "task_id": task_id,
        "success": result.success,
        "attempts": result.attempt_count,
        "error": result.error,
    }


# ── /detect-and-synthesize ──────────────────────────────────────────


class DetectAndSynthesizeRequest(BaseModel):
    query: str
    workspace_id: str = "default"
    triggered_by_user: str = "api"
    use_telegram_review: bool = False
    # 安全閥：一次 query 最多合成幾個工具（避免 LLM 把 query 拆成 50 個 GAP）
    max_synthesize: int = Field(default=2, ge=1, le=5)


@router.post("/detect-and-synthesize")
async def detect_and_synthesize(
    req: DetectAndSynthesizeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """便利的「一次 query → 偵測 → 對 GAP 自動觸發合成」入口。

    回傳：gap detection 結果 + 每個被觸發合成的 task_id 列表。
    """
    review = None
    if req.use_telegram_review and settings.tg_bot_token:
        review = integration.get_telegram_review()

    detector = GapDetector(
        provider=get_provider(),
        retriever=integration.get_retriever(),
        review=review,
    )
    detection = await detector.detect(
        req.query, workspace_id=req.workspace_id, session=session
    )

    submitted: list[dict] = []
    if detection.has_gap:
        orch = SynthesisOrchestrator(provider=get_provider())
        approval = integration.get_approval_service()
        gap_steps = [s for s in detection.steps if s.decision is DecisionType.GAP]
        for step_decision in gap_steps[: req.max_synthesize]:
            if step_decision.gap_spec is None:
                continue
            try:
                result = await orch.synthesize(step_decision.gap_spec)
                task_id = await approval.submit(
                    session,
                    result=result,
                    workspace_id=req.workspace_id,
                    triggered_by_query=req.query,
                    triggered_by_user=req.triggered_by_user,
                    triggered_by_query_id=detection.query_id,
                )
                submitted.append(
                    {
                        "task_id": task_id,
                        "step_id": step_decision.step.id,
                        "spec_name": step_decision.gap_spec.name,
                        "success": result.success,
                        "attempts": result.attempt_count,
                    }
                )
            except Exception as e:  # noqa: BLE001
                log.exception("detect-and-synthesize: step=%s synth 失敗", step_decision.step.id)
                submitted.append(
                    {"step_id": step_decision.step.id, "error": str(e)}
                )

    return {
        "detection": _gap_result_to_dict(detection),
        "synthesis_tasks": submitted,
    }


# ── /tasks/{id}/retry-with-hint ─────────────────────────────────────


class RetryWithHintRequest(BaseModel):
    hint: str = ""


@router.post("/tasks/{task_id}/retry-with-hint")
async def retry_with_hint(
    task_id: str,
    req: RetryWithHintRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """人類在 Telegram 按 refine 之後（task state=CODE_GENERATING），呼叫這個 endpoint 重跑。

    M7 骨架先支援「丟掉舊 attempts 重來」；未來可改成 hint 直接餵進第一輪 feedback。
    """
    task = await persistence.get_task(session, task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")
    if task.spec is None:
        raise HTTPException(400, f"task {task_id} 沒有 spec，無法重跑")

    # 從 DB 還原 EnrichedToolSpec
    try:
        enriched = EnrichedToolSpec.model_validate(task.spec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"task {task_id} spec 損壞：{e}") from e

    # 退回成 raw ToolSpec 讓 enricher 重跑（hint 可作為 description 補充）
    desc = enriched.description
    if req.hint:
        desc = f"{desc}\n\n[人類 hint]：{req.hint}"
    raw = ToolSpec(
        name=enriched.name,
        description=desc,
        when_to_use=enriched.when_to_use,
        when_not_to_use=enriched.when_not_to_use,
    )

    orch = SynthesisOrchestrator(provider=get_provider())
    result = await orch.synthesize(raw)
    # 沿用既有 task_id，覆寫 spec / code / tests / state
    await persistence.save_synthesis_outcome(session, task_id, result)
    # 把 hint 寫進審核紀錄
    await persistence.record_review(
        session,
        task_id=task_id,
        action="refine_hint" if req.hint else "retry",
        reviewer="api",
        hint=req.hint or None,
    )

    # 重要：推一條新 Telegram 訊息（成功 → Approve 鈕；失敗 → rescue 鈕）
    # 否則使用者只看得到之前那條 stale 訊息，按不到對應動作
    try:
        notifier = integration.get_notifier()
        if result.success:
            obs_by_type: dict[str, int] = {}
            if result.sandbox_result is not None:
                for o in result.sandbox_result.observations:
                    t = o.get("type", "unknown")
                    obs_by_type[t] = obs_by_type.get(t, 0) + 1
            await notifier.notify_approval(
                task_id=task_id,
                tool_id=result.spec_enriched.name,
                description=result.spec_enriched.description,
                triggered_by_query="(retry)",
                triggered_by_user="api",
                test_passed=(result.sandbox_result.passed if result.sandbox_result else 0),
                test_failed=(result.sandbox_result.failed if result.sandbox_result else 0),
                attempt_count=result.attempt_count,
                behavior_observations_by_type=obs_by_type,
                workspace_id=task.workspace_id,
            )
        else:
            await notifier.notify_rescue(
                task_id=task_id,
                tool_id=result.spec_enriched.name,
                attempts=result.attempt_count,
                last_error=result.error or "(no detail)",
            )
    except Exception as e:  # noqa: BLE001
        log.warning("retry-with-hint Telegram 推送失敗（不擋主流程）：%s", e)

    return {
        "task_id": task_id,
        "success": result.success,
        "attempts": result.attempt_count,
    }


# ── /tasks/{id}/approve & /reject 直接 endpoint ─────────────────────


class ApproveRequest(BaseModel):
    reviewer: str = "api"


@router.post("/tasks/{task_id}/approve")
async def approve(
    task_id: str,
    req: ApproveRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """直接 approve 一個 AWAITING_APPROVAL 的 task（無需 Telegram 按鈕）。

    側 demo 跑得通的逃生口；正式版仍應走 HITL Telegram flow。
    """
    try:
        tool_id = await integration.get_approval_service().approve(
            session, task_id, reviewer=req.reviewer
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    return {"task_id": task_id, "tool_id": tool_id, "state": "REGISTERED"}


class RejectRequest(BaseModel):
    reviewer: str = "api"
    note: str = ""


@router.post("/tasks/{task_id}/reject")
async def reject(
    task_id: str,
    req: RejectRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        await integration.get_approval_service().reject(
            session, task_id, reviewer=req.reviewer, note=req.note
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"task_id": task_id, "state": "DISCARDED"}


# ── helpers ─────────────────────────────────────────────────────────


def _gap_result_to_dict(result: GapDetectionResult) -> dict:
    # Pydantic computed properties 不會進 model_dump，手動補
    d = result.model_dump(mode="json")
    d["has_gap"] = result.has_gap
    d["gap_count"] = len(result.gap_specs)
    return d
