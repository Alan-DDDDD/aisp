"""YAML-driven workflow runtime（Phase 5）。

執行流程：
1. 從 step inputs 推導依賴（誰引用了誰的輸出）
2. Topological 分層；同層的 step 並行（asyncio.gather）
3. 每步：解析 input → 用 agent.input_schema 驗證 → agent.run → 寫回 scope
4. 全部跑完後解析 emit dict → 回傳給呼叫端組 ai_suggestion 事件
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.agents import registry as agent_registry
from app.agents.base import BaseAgent
from app.schemas.agent import AgentContext, AgentStepResult
from app.workflow.resolver import collect_refs, resolve
from app.workflow.spec import WorkflowDef, WorkflowStep

log = logging.getLogger(__name__)


_BUILTIN_SCOPES = {"event", "context", "trace", "vars"}


class WorkflowResult(BaseModel):
    trace_id: str
    workflow_id: str
    steps: list[AgentStepResult]
    emit: dict[str, Any] = Field(default_factory=dict)
    total_latency_ms: int = 0


async def run_workflow(
    workflow: WorkflowDef,
    *,
    event: dict[str, Any],
    workspace_id: str,
    room_id: str,
    history: list[dict] | None = None,
) -> WorkflowResult:
    trace_id = uuid.uuid4().hex
    ctx = AgentContext(
        workspace_id=workspace_id,
        room_id=room_id,
        trace_id=trace_id,
        history=history or [],
    )
    scope: dict[str, Any] = {
        "event": dict(event),
        "context": {
            "workspace_id": workspace_id,
            "room_id": room_id,
            "trace_id": trace_id,
            "history": history or [],
        },
        "trace": {"id": trace_id, "workflow_id": workflow.id},
    }

    step_by_id = {s.id: s for s in workflow.steps}
    deps = _build_deps(workflow.steps)
    steps_done: list[AgentStepResult] = []
    aborted = False

    start = time.perf_counter()
    remaining = set(step_by_id.keys())

    while remaining and not aborted:
        # 找出依賴都已就緒的 step
        batch = [sid for sid in remaining if deps[sid].issubset(set(scope.keys()) | {sid for sid in step_by_id if sid in scope})]
        # 化簡：deps[sid] 內所有元素都已存在 scope
        batch = [sid for sid in remaining if deps[sid].issubset(set(scope.keys()))]

        if not batch:
            # 無解 — 可能有循環或依賴缺失
            unresolved_deps = {sid: list(deps[sid] - set(scope.keys())) for sid in remaining}
            log.error("Workflow %s cannot proceed; unresolved deps: %s", workflow.id, unresolved_deps)
            break

        # 同層並行
        results = await asyncio.gather(
            *(_run_step(step_by_id[sid], ctx, scope) for sid in batch),
            return_exceptions=False,
        )
        for sid, step_result in zip(batch, results, strict=True):
            steps_done.append(step_result)
            # 即使 error 也寫一個 scope 條目（值為 None），讓下游 resolver 不會 KeyError
            scope[sid] = step_result.output if step_result.output is not None else None
            if step_result.error and step_by_id[sid].on_error == "abort":
                log.warning("Workflow %s aborted at step %s", workflow.id, sid)
                aborted = True
            remaining.remove(sid)

    emit = resolve(workflow.emit, scope) if workflow.emit else {}
    total = int((time.perf_counter() - start) * 1000)

    return WorkflowResult(
        trace_id=trace_id,
        workflow_id=workflow.id,
        steps=steps_done,
        emit=emit if isinstance(emit, dict) else {},
        total_latency_ms=total,
    )


def _build_deps(steps: list[WorkflowStep]) -> dict[str, set[str]]:
    """從每個 step 的 input 引用推導其依賴的 step ids。"""
    step_ids = {s.id for s in steps}
    deps: dict[str, set[str]] = {}
    for s in steps:
        refs = collect_refs(s.input)
        # 把非 step 的命名空間（event/context/...）排除
        deps[s.id] = {r for r in refs if r in step_ids and r != s.id}
        # 加入 parallel_with 的反向：parallel_with 通常代表「允許並行」，不是依賴 — 這裡不加 dep
    return deps


async def _run_step(
    step: WorkflowStep,
    ctx: AgentContext,
    scope: dict[str, Any],
) -> AgentStepResult:
    start = time.perf_counter()
    try:
        agent: BaseAgent = agent_registry.get(step.agent)
    except KeyError as e:
        latency = int((time.perf_counter() - start) * 1000)
        return AgentStepResult(
            step_id=step.id,
            agent_id=step.agent,
            input={},
            output=None,
            error=f"AgentNotFound: {e}",
            latency_ms=latency,
        )

    try:
        resolved_input = resolve(step.input, scope) or {}
        if not isinstance(resolved_input, dict):
            raise TypeError(f"step {step.id}: input must resolve to dict, got {type(resolved_input).__name__}")
        validated = agent.input_schema.model_validate(resolved_input)
        output = await agent.run(ctx, validated)
        latency = int((time.perf_counter() - start) * 1000)
        return AgentStepResult(
            step_id=step.id,
            agent_id=step.agent,
            input=resolved_input,
            output=output.model_dump() if isinstance(output, BaseModel) else dict(output),
            latency_ms=latency,
        )
    except Exception as e:  # noqa: BLE001 — runtime 必須隔離 agent 錯誤
        latency = int((time.perf_counter() - start) * 1000)
        log.exception("Step %s (%s) failed", step.id, step.agent)
        return AgentStepResult(
            step_id=step.id,
            agent_id=step.agent,
            input=resolve(step.input, scope) if isinstance(step.input, dict) else {},
            output=None,
            error=f"{type(e).__name__}: {e}",
            latency_ms=latency,
        )
