"""Planner — Phase A 的第一步：把 query 拆成 steps。

設計（PLAN §22.4.2 / §22.4.5）：
- 不給 planner 看 tool registry。它只負責拆解與標記 requires_tool。
- 工具匹配由 retrieval + judge 處理（職責分離，避免 planner 幻覺出 tool id）。
- 用 70B 模型（structured output）；MockProvider 在測試環境用樸素規則。
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.agents._json_util import parse_json_loose
from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.synthesis.schemas import PlannerOutput, PlannerStep

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一個 task planner。把使用者 query 拆成可執行的 step 序列。

判斷規則：
- 每個 step 必須是「能由單一 agent / tool 完成的最小單位」
- requires_tool=true：需要呼叫外部 API、查資料庫、檢索知識、寫入紀錄、計算等
- requires_tool=false：純文字組合、回覆使用者、解釋、摘要等不需要工具的工作

step.id 用 "s1", "s2", ... 由 1 開始。step.description 用中文，一句話講清楚。

務必輸出**嚴格 JSON**，不要 markdown 圍欄：
{
  "steps": [
    {"id": "s1", "description": "...", "requires_tool": true},
    {"id": "s2", "description": "...", "requires_tool": false}
  ]
}"""


class Planner:
    def __init__(self, provider: LLMProvider, model: str | None = None) -> None:
        self.provider = provider
        self.model = model or settings.gap_planner_model

    async def plan(self, query: str) -> PlannerOutput:
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
            response_format="json",
            temperature=0.1,
            model=self.model,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text)

        if data is None:
            log.warning("Planner JSON 無法解析 | raw=%r", resp.text[:300])
            return self._fallback(query)

        try:
            parsed = PlannerOutput.model_validate(data)
        except ValidationError as e:
            log.warning("Planner JSON schema 驗證失敗：%s | raw=%r", e, resp.text[:300])
            return self._fallback(query)

        if not parsed.steps:
            log.warning("Planner 回了空 plan，採 fallback | raw=%r", resp.text[:300])
            return self._fallback(query)

        return parsed

    @staticmethod
    def _fallback(query: str) -> PlannerOutput:
        """整句當一個 step，requires_tool=true 讓後續流程繼續跑。"""
        return PlannerOutput(
            steps=[PlannerStep(id="s1", description=query, requires_tool=True)]
        )
