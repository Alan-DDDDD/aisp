"""Spec Enricher — Phase B 的 [C1]，把 sparse ToolSpec 補成 EnrichedToolSpec。

為什麼這一步要存在（PLAN §22.5.2）：
- Code generator [C2] 需要結構化的 input/output field
- Test generator [C3] 需要具體的 example input/output dict 才能寫測試
- 人類審核 [C7] 需要看 when_NOT_to_use 才能判斷風險
- 補一次受益三處，比每個 step 各自補省成本
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.agents._json_util import parse_json_loose
from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.synthesis.schemas import (
    ConcreteExample,
    EnrichedToolSpec,
    FieldSpec,
    ToolSpec,
)

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是 tool spec enricher。輸入是一份不完整的 tool 規格，請補完成可實作的版本。

補完原則：
1. when_NOT_to_use：必填，列出至少一個「相關但不該用」的反例情境
2. examples：至少 2 個具體範例（input/output 是真正的 dict，欄位要對得上 input/output_fields）
3. input_fields / output_fields：用 Pydantic 能直接組裝的 type；只能用 str / int / float / bool / list / dict
4. side_effect：判斷 read_only（純查詢）/ write_local（寫自家 DB）/ write_external（外呼 API / 寄信）
5. tags：1-3 個分類字串，如 ["customer", "orders"]

【關於 examples 的數字 — 違反等同 spec 錯誤】

如果工具是「計算 / 轉換 / 公式」類（單位轉換、數學運算、利率/匯率/百分比、
日期計算等任何 output 由 input 透過確定式公式推導的場景）：

A. **先在腦中寫下公式**，例如「ping = m² / 3.305785」、「F = C * 9/5 + 32」
B. **再對每個 example.input 用公式逐一算 output**，把結果填進 example.output
C. **特別小心轉換方向**：常見錯誤是把因子算反
   - 例：1 坪 = 3.305785 m² → 1 m² = 0.3025 坪（不是 3.305785）
   - 例：1 inch = 2.54 cm → 1 cm = 0.3937 inch（不是 2.54）
   - 例：1 mile = 1.609 km → 1 km = 0.621 mile（不是 1.609）
D. **驗算一次**：把你算出的 output 套回去看 input 是否合理
E. 數字小數點可保留 4-6 位即可

若有任何一個 example 的數字「看起來只是把因子 copy 過去」（例如 input=100、
output=3.305 — 100 的因子怎麼會剛好是 3.305），那一定是搞錯方向，要重算。

務必輸出**嚴格 JSON**，不要 markdown 圍欄。範例 schema：
{
  "name": "get_customer_orders_recent",
  "description": "查單一客戶最近 N 天的訂單清單",
  "when_to_use": "需要單一客戶在特定時間範圍內的訂單時",
  "when_not_to_use": "不要用於跨客戶彙總統計（請用 analytics_query）",
  "examples": [
    {
      "scenario": "查客戶 C-123 最近 30 天的訂單",
      "input": {"customer_id": "C-123", "days": 30},
      "output": {"orders": [{"id": "O-1", "amount": 1200}], "total": 1}
    }
  ],
  "input_fields": [
    {"name": "customer_id", "type": "str", "description": "客戶 ID", "required": true},
    {"name": "days", "type": "int", "description": "回溯天數", "required": false, "default": 30}
  ],
  "output_fields": [
    {"name": "orders", "type": "list", "description": "訂單列表"},
    {"name": "total", "type": "int", "description": "筆數"}
  ],
  "side_effect": "read_only",
  "tags": ["customer", "orders"]
}

計算類範例（攝氏轉華氏，注意 example.output 用 F = C * 9/5 + 32 算過）：
{
  "name": "celsius_to_fahrenheit",
  "examples": [
    {"scenario": "冰點", "input": {"celsius": 0},   "output": {"fahrenheit": 32.0}},
    {"scenario": "體溫", "input": {"celsius": 37},  "output": {"fahrenheit": 98.6}},
    {"scenario": "沸點", "input": {"celsius": 100}, "output": {"fahrenheit": 212.0}}
  ],
  ...
}"""


def _format_input_spec(spec: ToolSpec) -> str:
    """把輸入 spec 格式化進 user prompt。"""
    parts = [
        f"name: {spec.name}",
        f"description: {spec.description}",
        f"when_to_use: {spec.when_to_use or '(空)'}",
        f"when_not_to_use: {spec.when_not_to_use or '(空)'}",
        f"input_hint: {spec.input_hint or '(空)'}",
        f"output_hint: {spec.output_hint or '(空)'}",
    ]
    if spec.examples:
        parts.append(f"提示範例（粗略）: {spec.examples}")
    return "\n".join(parts)


class SpecEnricher:
    def __init__(self, provider: LLMProvider, model: str | None = None) -> None:
        self.provider = provider
        # 補完是創造題，用 70B（同 planner）
        self.model = model or settings.gap_planner_model

    async def enrich(self, raw: ToolSpec) -> EnrichedToolSpec:
        user_content = (
            "請把以下這份 tool 規格補完：\n\n" + _format_input_spec(raw) + "\n\n"
            "確保 examples 至少 2 個，input_fields / output_fields 結構化。"
        )
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.2,
            max_tokens=2048,
            model=self.model,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text)

        if data is None:
            log.warning("SpecEnricher JSON 無法解析 | raw=%r", resp.text[:400])
            return self._minimal_fallback(raw)

        # 確保 name 與 description 至少保留 raw 提供的版本
        data.setdefault("name", raw.name)
        data.setdefault("description", raw.description)
        data.setdefault("when_to_use", raw.when_to_use or raw.description)

        try:
            return EnrichedToolSpec.model_validate(data)
        except ValidationError as e:
            log.warning("EnrichedToolSpec schema 驗證失敗：%s | raw=%r", e, resp.text[:400])
            return self._minimal_fallback(raw)

    @staticmethod
    def _minimal_fallback(raw: ToolSpec) -> EnrichedToolSpec:
        """LLM 整批失敗時的最小可用版本 —— 仍然有效，但人類審核會看出空洞。"""
        return EnrichedToolSpec(
            name=raw.name,
            description=raw.description,
            when_to_use=raw.when_to_use or raw.description,
            when_not_to_use=raw.when_not_to_use or "（spec enricher 失敗，請人類補上）",
            examples=[
                ConcreteExample(scenario=raw.description, input={}, output={}),
            ],
            input_fields=[FieldSpec(name="query", type="str", description="自然語言查詢")],
            output_fields=[FieldSpec(name="result", type="dict", description="結果")],
            side_effect="read_only",
            tags=[],
        )
