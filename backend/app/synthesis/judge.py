"""Judge — 對 retrieval 灰色地帶的 step 做 USE / COMPOSE / GAP 判決。

設計（PLAN §22.4.2、§22.4.5）：
- 用較便宜的 8B 模型（分類題不是創造題）
- Batched：把多個灰色 step + 它們的候選一次丟給 LLM
- 結構化 JSON 輸出，含 confidence。若 LLM 自己給的 confidence 不可信，
  未來可改成從 logprobs 反推（GenerationRequest 已支援 logprobs）
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.agents._json_util import parse_json_loose
from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.synthesis.schemas import (
    DecisionType,
    JudgeBatchOutput,
    JudgeStepDecision,
    PlannerStep,
    ToolCandidate,
)

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一個 tool selection judge。對每個 step + 候選工具，判定一個 decision：

- USE：某個候選工具完全能解這個 step → 填 tool_id
- COMPOSE：多個候選工具串起來能解 → 填 compose_chain (依執行順序)
- GAP：沒有合適工具，需要造一個新工具 → 填 gap_spec

判斷依據：
1. 候選工具的 description 與 when_to_use 是否覆蓋 step
2. 候選工具的 when_not_to_use 是否明確排除 step（最強訊號）
3. 既有工具的 side_effect 是否合理

confidence 區間：
- 0.85+：非常確定
- 0.40-0.85：不太確定（系統會問人類）
- 0-0.40：幾乎確定要 GAP

GAP 時的 gap_spec 必填欄位：
- name: 建議的 tool_id（snake_case，例如 get_orders_by_date_range）
- description: 一句話，這工具做什麼
- when_to_use: 什麼情境用
- input_hint: 自然語言寫需要哪些 input
- output_hint: 自然語言寫要回什麼

務必輸出**嚴格 JSON**，不要 markdown 圍欄：
{
  "decisions": [
    {
      "step_id": "s1",
      "decision": "USE",
      "tool_id": "kb_search",
      "confidence": 0.9,
      "reasoning": "..."
    }
  ]
}"""


def _format_step_block(step: PlannerStep, candidates: list[ToolCandidate]) -> str:
    """把 step + 候選工具序列化成 LLM prompt 內容。"""
    lines = [f"### Step {step.id}", f"Description: {step.description}", "", "候選工具："]
    for i, c in enumerate(candidates, 1):
        lines.append(f"  [{i}] {c.tool_id} (similarity={c.similarity:.2f})")
        lines.append(f"      description: {c.description}")
        if c.when_to_use:
            lines.append(f"      when_to_use: {c.when_to_use}")
        if c.when_not_to_use:
            lines.append(f"      when_not_to_use: {c.when_not_to_use}")
        lines.append(f"      side_effect: {c.side_effect}")
    if not candidates:
        lines.append("  （沒有候選，極可能是 GAP）")
    return "\n".join(lines)


class Judge:
    def __init__(self, provider: LLMProvider, model: str | None = None) -> None:
        self.provider = provider
        self.model = model or settings.gap_judge_model

    async def judge(
        self,
        items: list[tuple[PlannerStep, list[ToolCandidate]]],
    ) -> dict[str, JudgeStepDecision]:
        """一次處理多個 step，回傳 step_id → JudgeStepDecision。"""
        if not items:
            return {}

        blocks = [_format_step_block(step, cands) for step, cands in items]
        user_content = "請對以下每個 step 做判決：\n\n" + "\n\n".join(blocks)

        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.0,
            model=self.model,
        )
        resp = await self.provider.generate(req)
        data: dict[str, Any] | None = parse_json_loose(resp.text)

        if data is None:
            log.warning("Judge JSON 無法解析，走 fallback | raw=%r", resp.text[:400])
            return self._fallback_decisions(items)

        try:
            parsed = JudgeBatchOutput.model_validate(data)
        except ValidationError as e:
            log.warning("Judge JSON schema 驗證失敗：%s | raw=%r", e, resp.text[:400])
            return self._fallback_decisions(items)

        if not parsed.decisions:
            log.warning("Judge 回了空 decisions，走 fallback | raw=%r", resp.text[:400])
            return self._fallback_decisions(items)

        decisions = {d.step_id: d for d in parsed.decisions}
        # 任何缺漏的 step 補上保守 fallback（視為 GAP）
        for step, _ in items:
            if step.id not in decisions:
                decisions[step.id] = JudgeStepDecision(
                    step_id=step.id,
                    decision=DecisionType.GAP,
                    confidence=0.0,
                    reasoning="judge 未對此 step 給出決策，保守判 GAP",
                )
        return decisions

    @staticmethod
    def _fallback_decisions(
        items: list[tuple[PlannerStep, list[ToolCandidate]]],
    ) -> dict[str, JudgeStepDecision]:
        """LLM 整批失敗時：信任 retrieval top-1，confidence 設成 similarity。"""
        out: dict[str, JudgeStepDecision] = {}
        for step, cands in items:
            if cands:
                top = cands[0]
                out[step.id] = JudgeStepDecision(
                    step_id=step.id,
                    decision=DecisionType.USE,
                    tool_id=top.tool_id,
                    confidence=top.similarity,
                    reasoning="judge LLM 解析失敗，fallback 採用 retrieval top-1",
                )
            else:
                out[step.id] = JudgeStepDecision(
                    step_id=step.id,
                    decision=DecisionType.GAP,
                    confidence=0.0,
                    reasoning="judge LLM 解析失敗且無候選工具",
                )
        return out


# 便於 prompt 除錯
def debug_dump_prompt(
    items: list[tuple[PlannerStep, list[ToolCandidate]]],
) -> str:  # pragma: no cover
    return json.dumps(
        {"system": SYSTEM_PROMPT, "blocks": [_format_step_block(s, c) for s, c in items]},
        ensure_ascii=False,
        indent=2,
    )
