"""ToolAgent — TA1：從 registry 選工具呼叫（無 synthesis 整合，TA2 才接）。

職責：
  1. 對使用者訊息做 retrieval，找 top-k tools
  2. 若最大相似度 >= threshold → 用 LLM 推 args → 呼叫 tool
  3. 否則回 tool_called=None（讓下游 knowledge agent 接手 RAG）

設計重點：
- TA1 只看「即時 user message」對 tool；TA2 起改成 plan → step 粒度
- 不負責 synthesis（沒命中就放行）
- 對 generated tool 與 builtin tool 一視同仁，靠 retriever workspace scoping 區分
- 呼叫失敗時不擋整條 pipeline — 把 error 寫進 output 給下游 composer 決定怎麼回覆
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, ToolAgentInput, ToolAgentOutput
from app.synthesis.tool_retriever import ToolRetriever
from app.synthesis.tool_retriever import get_default as get_default_retriever
from app.tools import registry as tool_registry
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


# 進工具的相似度門檻 — 比 gap_detector shortcut_high (0.85) 低，因為這裡用「整句 user msg」
# 而非 step description，語意密度不同；太高會錯失合理呼叫，太低會誤觸發。
DEFAULT_USE_THRESHOLD = 0.55


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
        use_threshold: float = DEFAULT_USE_THRESHOLD,
    ) -> None:
        self.provider = provider
        self.retriever = retriever or get_default_retriever()
        self.use_threshold = use_threshold

    async def run(  # type: ignore[override]
        self, ctx: AgentContext, payload: ToolAgentInput
    ) -> ToolAgentOutput:
        candidates = self.retriever.retrieve(
            payload.message,
            top_k=3,
            workspace_id=ctx.workspace_id,
        )
        cands_summary = [
            {"tool_id": c.tool_id, "similarity": round(c.similarity, 3)}
            for c in candidates
        ]

        if not candidates:
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason="no_candidates",
            )
        top = candidates[0]
        if top.similarity < self.use_threshold:
            return ToolAgentOutput(
                candidates=cands_summary,
                skipped_reason=f"low_similarity({top.similarity:.2f}<{self.use_threshold:.2f})",
            )

        try:
            tool = tool_registry.get(top.tool_id)
        except KeyError:
            log.warning(
                "tool_agent: retriever 命中 %s 但 registry 沒有 — index 與 registry 不同步",
                top.tool_id,
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
        except Exception as e:  # noqa: BLE001 — tool 出錯不擋整條 pipeline
            log.exception("tool_agent: tool %s call failed", top.tool_id)
            return ToolAgentOutput(
                tool_called=top.tool_id,
                candidates=cands_summary,
                error=f"tool_call_failed:{e}",
            )

        return ToolAgentOutput(
            tool_called=top.tool_id,
            tool_result=_as_dict(result),
            candidates=cands_summary,
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
