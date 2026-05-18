"""ApprovalService — Phase B 審核流程協調者（PLAN §22.5.7 / §22.5.8）。

職責：
- submit(synthesis_result, ...) → 把 SynthesisResult 持久化、推 Telegram 等審
- approve()  → 寫檔 + 註冊 + 標 REGISTERED + 寫 GeneratedTool row
- reject()   → 標 DISCARDED
- refine_with_hint(hint) → 標回 CODE_GENERATING，由上游 re-run synthesizer
- abandon()  → 標 FAILED
- handle_callback() → 提供給 bot.py 的 ApprovalHandler 入口

設計重點：
- 不直接呼叫 SynthesisOrchestrator（避免循環依賴）；refine 後 re-run 由上游組裝
- DB 一定先寫，再寄 Telegram；avoid 訊息發出但狀態沒更新
- 所有公開方法接 AsyncSession，呼叫方控制 transaction 邊界
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GeneratedTool
from app.synthesis import persistence
from app.synthesis.orchestrator import SynthesisResult
from app.synthesis.registry_loader import install_from_source
from app.synthesis.tool_retriever import ToolRetriever, get_default
from app.telegram.callback_router import ApprovalCallback
from app.telegram.notifier import Notifier

log = logging.getLogger(__name__)


ApprovalDecision = Literal["approve", "reject", "refine", "retry", "abandon"]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _now() -> datetime:
    return datetime.now(UTC)


class ApprovalService:
    """所有審核相關業務集中於此。"""

    def __init__(
        self,
        notifier: Notifier,
        *,
        retriever: ToolRetriever | None = None,
        default_chat_id: str | None = None,
    ) -> None:
        self.notifier = notifier
        self.retriever = retriever or get_default()
        self.default_chat_id = default_chat_id

    # ── 提交 ────────────────────────────────────────────────────

    async def submit(
        self,
        session: AsyncSession,
        *,
        result: SynthesisResult,
        workspace_id: str,
        triggered_by_query: str,
        triggered_by_user: str,
        triggered_by_query_id: str | None = None,
        triggered_by_decision_id: str | None = None,
    ) -> str:
        """把 synthesis result 推給人類審核；回 task_id。

        成功 path：建 ToolSynthesisTask（AWAITING_APPROVAL / AWAITING_HUMAN_RESCUE）
        → 寄 Telegram。
        """
        # 寫 DB：先 create_task，再 save_outcome 一次完成（簡化路徑）
        task = await persistence.create_task(
            session,
            spec=result.spec_enriched.model_dump(),
            workspace_id=workspace_id,
            triggered_by_query_id=triggered_by_query_id,
            triggered_by_decision_id=triggered_by_decision_id,
        )
        await persistence.save_synthesis_outcome(session, task.id, result)

        # 寄 Telegram
        if result.success:
            obs_by_type: dict[str, int] = {}
            if result.sandbox_result is not None:
                for o in result.sandbox_result.observations:
                    t = o.get("type", "unknown")
                    obs_by_type[t] = obs_by_type.get(t, 0) + 1
            await self.notifier.notify_approval(
                task_id=task.id,
                tool_id=result.spec_enriched.name,
                description=result.spec_enriched.description,
                triggered_by_query=triggered_by_query,
                triggered_by_user=triggered_by_user,
                test_passed=(result.sandbox_result.passed if result.sandbox_result else 0),
                test_failed=(result.sandbox_result.failed if result.sandbox_result else 0),
                attempt_count=result.attempt_count,
                behavior_observations_by_type=obs_by_type,
                workspace_id=workspace_id,
                chat_id=self.default_chat_id,
            )
        else:
            await self.notifier.notify_rescue(
                task_id=task.id,
                tool_id=result.spec_enriched.name,
                attempts=result.attempt_count,
                last_error=result.error or "（無詳細錯誤）",
                chat_id=self.default_chat_id,
            )
        return task.id

    # ── 動作 ────────────────────────────────────────────────────

    async def approve(
        self,
        session: AsyncSession,
        task_id: str,
        reviewer: str,
    ) -> str:
        """通過審核：寫檔 + 註冊 + 標 REGISTERED + 寫 GeneratedTool row。"""
        task = await persistence.get_task(session, task_id)
        if task is None:
            raise KeyError(f"approve: task {task_id} 不存在")
        if task.state != persistence.STATE_AWAITING_APPROVAL:
            raise RuntimeError(
                f"approve: task {task_id} 狀態為 {task.state}，無法 approve"
            )
        if not task.code:
            raise RuntimeError(f"approve: task {task_id} 沒有 code")

        spec = task.spec or {}
        tool_id = spec.get("name") or f"generated_{task.id}"

        # 寫檔 + 註冊（含 retriever rebuild）
        path = install_from_source(
            tool_id,
            task.code,
            workspace_id=task.workspace_id,
            retriever=self.retriever,
        )

        # 寫 GeneratedTool row
        row = GeneratedTool(
            id=tool_id,
            version=spec.get("version", "1.0.0"),
            synthesis_task_id=task.id,
            workspace_id=task.workspace_id,
            scope="workspace",  # 預設 scoped；admin 之後可 promote
            description=spec.get("description", ""),
            when_to_use=spec.get("when_to_use", ""),
            when_not_to_use=spec.get("when_not_to_use", ""),
            examples=spec.get("examples", []),
            tags=spec.get("tags", []),
            side_effect=spec.get("side_effect", "read_only"),
            requires_approval=False,
            source_path=str(path),
            approved_by=reviewer,
            approved_at=_now(),
            status="active",
        )
        session.add(row)

        # 狀態轉移 + 審核紀錄
        await persistence.transition(session, task.id, persistence.STATE_REGISTERED)
        await persistence.record_review(
            session, task_id=task.id, action="approve", reviewer=reviewer
        )
        await session.commit()
        log.info("Approval: tool=%s registered (workspace=%s)", tool_id, task.workspace_id)
        return tool_id

    async def reject(
        self,
        session: AsyncSession,
        task_id: str,
        reviewer: str,
        note: str = "",
    ) -> None:
        task = await persistence.get_task(session, task_id)
        if task is None:
            raise KeyError(f"reject: task {task_id} 不存在")
        await persistence.transition(session, task.id, persistence.STATE_DISCARDED)
        await persistence.record_review(
            session, task_id=task.id, action="reject", reviewer=reviewer, note=note
        )

    async def queue_refine(
        self,
        session: AsyncSession,
        task_id: str,
        reviewer: str,
        hint: str,
    ) -> None:
        """收到 hint：標回 CODE_GENERATING，由上游（M7 整合層）重新呼叫 orchestrator。

        本服務不直接觸發 re-synth — 那是 SynthesisOrchestrator 的責任。
        """
        task = await persistence.get_task(session, task_id)
        if task is None:
            raise KeyError(f"queue_refine: task {task_id} 不存在")
        await persistence.transition(
            session, task.id, persistence.STATE_CODE_GENERATING
        )
        await persistence.record_review(
            session,
            task_id=task.id,
            action="refine_hint",
            reviewer=reviewer,
            hint=hint,
        )

    async def abandon(
        self,
        session: AsyncSession,
        task_id: str,
        reviewer: str,
    ) -> None:
        task = await persistence.get_task(session, task_id)
        if task is None:
            raise KeyError(f"abandon: task {task_id} 不存在")
        await persistence.transition(session, task.id, persistence.STATE_FAILED)
        await persistence.record_review(
            session, task_id=task.id, action="abandon", reviewer=reviewer
        )

    # ── Telegram callback 入口 ─────────────────────────────────

    def make_callback_handler(self, session_factory):
        """回一個 bot.register_approval_handler 可用的 callable。

        session_factory：no-arg callable，回 AsyncSession（典型用 SessionLocal）。
        """

        async def handler(callback: ApprovalCallback, chat_id: str, message_id: int) -> None:
            reviewer = f"telegram:{chat_id}"
            async with session_factory() as session:
                try:
                    if callback.action == "approve":
                        await self.approve(session, callback.task_id, reviewer)
                    elif callback.action == "reject":
                        await self.reject(session, callback.task_id, reviewer)
                    elif callback.action == "refine":
                        # 簡化骨架：M7 接 conversation flow 再支援多輪 hint 收集；
                        # 現在先 queue 一個空 hint 並把 task 標回 CODE_GENERATING
                        await self.queue_refine(
                            session, callback.task_id, reviewer, hint=""
                        )
                    elif callback.action == "retry":
                        # rescue 場景：直接標回 CODE_GENERATING 等上游重跑
                        await persistence.transition(
                            session,
                            callback.task_id,
                            persistence.STATE_CODE_GENERATING,
                        )
                        await persistence.record_review(
                            session,
                            task_id=callback.task_id,
                            action="retry",
                            reviewer=reviewer,
                        )
                    elif callback.action == "abandon":
                        await self.abandon(session, callback.task_id, reviewer)
                except Exception as e:  # noqa: BLE001
                    log.exception("approval handler 失敗 callback=%s", callback)
                    # edit 訊息告知失敗 — text 純文字（不過 parser），避免 exception 內含 HTML/MD 控制字
                    with contextlib.suppress(Exception):
                        await self.notifier.sender.edit(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=f"⚠️ 處理失敗：{e}",
                            parse_mode=None,
                        )
                    return

            # 成功：edit 訊息標記已處理
            try:
                await self.notifier.sender.edit(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"✅ 已處理 ({callback.action})。",
                    parse_mode=None,
                )
            except Exception as e:  # noqa: BLE001
                log.debug("edit message 失敗（可忽略）：%s", e)

        return handler
