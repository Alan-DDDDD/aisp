import logging

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, ClauseAnalyzerInput, ClauseAnalyzerOutput

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是法務條款分析 agent。
給你一段法律問題或條文敘述，回傳結構化分析。

clause_type 常見：
- NDA：保密相關
- liability_cap：損害賠償上限
- termination：終止條款
- ip_assignment：智慧財產權歸屬
- data_processing：個資處理 / GDPR / PDPA
- indemnification：賠償保證
- non_compete：競業禁止
- employment：雇傭契約相關
- compliance：合規查詢
- general_inquiry：一般詢問

risk_level：
- high：影響重大、需特別審閱、可能違法
- medium：標準商業風險、需確認對方條款
- low：常規條款、無顯著風險

輸出嚴格 JSON：
{
  "clause_type": "<上述其一>",
  "risk_level": "low|medium|high",
  "suggestion": "<給律師/業務一句行動建議>",
  "key_points": ["<關鍵點 1>", "<2>", "<3>"]
}"""


_VALID_RISK = {"low", "medium", "high"}


class ClauseAnalyzerAgent(BaseAgent):
    id = "clause_analyzer"
    input_schema = ClauseAnalyzerInput
    output_schema = ClauseAnalyzerOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(  # type: ignore[override]
        self, ctx: AgentContext, payload: ClauseAnalyzerInput
    ) -> ClauseAnalyzerOutput:
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload.message}],
            response_format="json",
            temperature=0.2,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text) or {}
        risk = str(data.get("risk_level") or "low").lower()
        if risk not in _VALID_RISK:
            risk = "low"
        return ClauseAnalyzerOutput(
            clause_type=str(data.get("clause_type") or "general_inquiry"),
            risk_level=risk,
            suggestion=str(data.get("suggestion") or ""),
            key_points=[str(p) for p in (data.get("key_points") or [])],
        )
