"""ToolAgent — TA3：用 gap_detector 拆 step + 命中工具呼叫；GAP 時觸發合成等審。

職責：
  1. 把 user message 餵 gap_detector：planner 拆 step → retrieval shortcut → judge
  2. 找第一個 USE step → LLM 推 args → 呼叫對應 tool
  3. 沒 USE 但有 GAP：
     - 若有 orchestrator + approval_service + session_factory 注入 → 同步觸發合成
     - 合成成功 → ApprovalService.submit → 進 AWAITING_APPROVAL（推 Telegram +
       寫 dashboard）→ composer 告知使用者「已生成工具，待審後再試」
     - 合成失敗 → 進 AWAITING_HUMAN_RESCUE
  4. 全部 no_tool_needed → 放行給下游 knowledge agent

設計重點（PLAN §22.5.7）：
- 嚴格遵守 HITL — 所有 generated tool 一定要人類按 Approve 才能進 registry。
  本層不做 auto-approve（即使 side_effect=read_only），避免「LLM 寫的 code 沒被審
  就上線」這個 Phase 6 紅線
- 一次 chat 最多 1 個 tool 呼叫 + 1 個合成觸發（不做 multi-gap）
- 註冊新工具需要人類審核 → 不會在這層內遞迴呼叫 self.run()
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, ToolAgentInput, ToolAgentOutput
from app.synthesis.approval import ApprovalService
from app.synthesis.gap_detector import GapDetector
from app.synthesis.orchestrator import SynthesisOrchestrator
from app.synthesis.schemas import DecisionType, StepDecision, ToolSpec
from app.synthesis.tool_retriever import ToolRetriever
from app.tools import registry as tool_registry
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


ARG_GEN_SYSTEM_PROMPT = """你是 tool-calling assistant。給定一個 tool 的 spec
（name / description / input fields）與使用者訊息，輸出 JSON 物件作為這個 tool 的 input。

規則：
- 欄位嚴格對應 input fields 的 name 與 type
- 只輸出純 JSON，不要 markdown 圍欄、不要解釋
- 若無法從使用者訊息抽出某 required 欄位，輸出 {"_error": "missing field: <name>"}"""


class ToolAgent(BaseAgent):
    id = "tool_agent"
    input_schema = ToolAgentInput
    output_schema = ToolAgentOutput

    def __init__(
        self,
        provider: LLMProvider,
        retriever: ToolRetriever | None = None,
        gap_detector: GapDetector | None = None,
        # TA3 — 可選注入合成 + 審核能力。三者要嘛都有，要嘛都無；
        # 都無時行為退回 TA2（GAP 只 report，不合成）
        orchestrator: SynthesisOrchestrator | None = None,
        approval_service: ApprovalService | None = None,
        session_factory: Any = None,  # Callable[[], AsyncContextManager[AsyncSession]]
    ) -> None:
        self.provider = provider
        if gap_detector is None:
            gap_detector = GapDetector(provider=provider, retriever=retriever)
        self.gap_detector = gap_detector
        self.orchestrator = orchestrator
        self.approval_service = approval_service
        self.session_factory = session_factory

    def _can_synthesize(self) -> bool:
        return (
            self.orchestrator is not None
            and self.approval_service is not None
            and self.session_factory is not None
        )

    async def run(  # type: ignore[override]
        self, ctx: AgentContext, payload: ToolAgentInput
    ) -> ToolAgentOutput:
        detection = await self.gap_detector.detect(
            payload.message, workspace_id=ctx.workspace_id
        )
        cands_summary = _flatten_candidates(detection)

        # 找第一個 USE step（最早出現的 step 優先 — 通常是 query 主要意圖）
        use_step = next(
            (s for s in detection.steps if s.decision is DecisionType.USE and s.tool_id),
            None,
        )

        if use_step is None:
            gap_steps = [
                s for s in detection.steps if s.decision is DecisionType.GAP
            ]
            if gap_steps:
                return await self._handle_gap(
                    ctx, payload, gap_steps, cands_summary
                )
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason="no_tool_needed",
            )

        # 有 USE step — 嘗試呼叫
        try:
            tool = tool_registry.get(use_step.tool_id)
        except KeyError:
            log.warning(
                "tool_agent: gap_detector 命中 %s 但 registry 沒有（index 不同步）",
                use_step.tool_id,
            )
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason="tool_missing_from_registry",
            )

        args = await self._generate_args(tool, payload.message)
        if args is None:
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason="arg_gen_unparseable",
            )
        if "_error" in args:
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason=f"arg_gen_missing:{args['_error']}",
            )

        try:
            payload_obj = tool.input_schema(**args)
        except ValidationError as e:
            err_brief = "; ".join(
                f"{'.'.join(map(str, e_item['loc']))}: {e_item['msg']}"
                for e_item in e.errors()[:2]
            )
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason=f"input_validation:{err_brief}",
            )

        try:
            result = await tool.call(ctx, payload_obj)
        except Exception as e:  # noqa: BLE001 — tool 出錯不擋 pipeline
            log.exception("tool_agent: tool %s call failed", use_step.tool_id)
            return ToolAgentOutput(
                tool_called=use_step.tool_id,
                candidates=cands_summary,
                error=f"tool_call_failed:{e}",
            )

        return ToolAgentOutput(
            tool_called=use_step.tool_id,
            tool_result=_as_dict(result),
            candidates=cands_summary,
        )

    async def _handle_gap(
        self,
        ctx: AgentContext,
        payload: ToolAgentInput,
        gap_steps: list[StepDecision],
        cands_summary: list[dict[str, Any]],
    ) -> ToolAgentOutput:
        """GAP path：可合成就觸發 → submit 等審；不在這層自動 approve。"""
        gap_specs_dump = [s.gap_spec.model_dump() for s in gap_steps if s.gap_spec]

        # 沒注入合成能力 → 退回 TA2 行為（report only）
        if not self._can_synthesize():
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason="gap_detected",
                gap_specs=gap_specs_dump,
            )

        # 合成第一個有效 gap_spec
        first_with_spec = next((s for s in gap_steps if s.gap_spec is not None), None)
        if first_with_spec is None or first_with_spec.gap_spec is None:
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason="gap_detected_but_no_spec",
                gap_specs=gap_specs_dump,
            )

        spec: ToolSpec = first_with_spec.gap_spec
        try:
            result = await self.orchestrator.synthesize(spec)  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001
            log.exception("tool_agent: orchestrator.synthesize 失敗")
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason=f"synthesis_exception:{e}",
                gap_specs=gap_specs_dump,
            )

        async with self.session_factory() as session:  # type: ignore[misc]
            try:
                await self.approval_service.submit(  # type: ignore[union-attr]
                    session,
                    result=result,
                    workspace_id=ctx.workspace_id,
                    triggered_by_query=payload.message,
                    triggered_by_user="chat",
                )
            except Exception as e:  # noqa: BLE001
                log.exception("tool_agent: ApprovalService.submit 失敗")
                return ToolAgentOutput(
                    candidates=cands_summary,
                    skipped_reason=f"submit_failed:{e}",
                    gap_specs=gap_specs_dump,
                )

        new_tool_name = result.spec_enriched.name

        if not result.success:
            # 合成失敗 — task 已是 AWAITING_HUMAN_RESCUE 等待 refine/abandon
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason=f"synthesis_failed:{result.error or 'unknown'}",
                gap_specs=gap_specs_dump,
            )

        # 合成成功 — 一律走 HITL，等管理員按 Approve 才會註冊
        return ToolAgentOutput(
            candidates=cands_summary,
            skipped_reason=f"awaiting_approval:{new_tool_name}",
            gap_specs=gap_specs_dump,
        )

    async def _generate_args(self, tool: BaseTool, message: str) -> dict[str, Any] | None:
        spec = _format_tool_spec(tool)
        req = GenerationRequest(
            system=ARG_GEN_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"tool spec:\n{spec}\n\n使用者訊息：{message}",
                }
            ],
            response_format="json",
            temperature=0.1,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text)
        if data is None:
            log.warning("tool_agent arg_gen: cannot parse %r", resp.text[:200])
        return data


def _flatten_candidates(detection) -> list[dict[str, Any]]:
    """把 detection.steps 所有 candidates 攤平成單一 list 給 trace 看。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in detection.steps:
        for c in step.candidates:
            if c.tool_id in seen:
                continue
            seen.add(c.tool_id)
            out.append({"tool_id": c.tool_id, "similarity": round(c.similarity, 3)})
    return out


def _format_tool_spec(tool: BaseTool) -> str:
    """把 tool input_schema 攤平成 LLM 容易讀的純文字。"""
    lines: list[str] = [
        f"name: {tool.id}",
        f"description: {tool.description}",
        "input fields:",
    ]
    for f_name, field in tool.input_schema.model_fields.items():
        annot = getattr(field.annotation, "__name__", str(field.annotation))
        req_tag = " (required)" if field.is_required() else f" (optional, default={field.default!r})"
        desc = f" — {field.description}" if field.description else ""
        lines.append(f"  - {f_name}: {annot}{req_tag}{desc}")
    if tool.examples:
        lines.append("examples:")
        for ex in tool.examples[:2]:
            lines.append(f"  scenario: {ex.scenario}")
            lines.append(f"  input: {ex.input}")
    return "\n".join(lines)


def _as_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if isinstance(result, dict):
        return result
    return {"value": result}
