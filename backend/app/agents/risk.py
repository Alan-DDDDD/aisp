import logging

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, RiskInput, RiskOutput

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是企業風險檢核 agent。
依客戶意圖、訊息、知識來源，判斷處理風險等級。

判定原則：
- high：明確違法、客訴升高、客戶人身安全、資料外洩、財務重大損害
- medium：合規邊界、需主管裁量、需特殊揭露、高齡或弱勢客戶
- low：一般詢問、自助可解、無敏感資訊

輸出嚴格 JSON：
{"risk_level": "low|medium|high", "reasons": ["<原因短句 1>", "<2>"]}"""


_VALID = {"low", "medium", "high"}


class RiskAgent(BaseAgent):
    id = "risk"
    input_schema = RiskInput
    output_schema = RiskOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, ctx: AgentContext, payload: RiskInput) -> RiskOutput:  # type: ignore[override]
        intent_str = (
            f"category={payload.intent.category}, intent={payload.intent.intent}"
            if payload.intent
            else ""
        )
        doc_lines = "\n".join(
            f"- {d.get('title', '')[:30]}: {(d.get('text') or d.get('chunk') or '')[:120]}"
            for d in payload.docs[:3]
        )
        user_content = (
            f"客戶訊息：{payload.message}\n\n"
            + (f"意圖：{intent_str}\n\n" if intent_str else "")
            + (f"知識來源摘要：\n{doc_lines}" if doc_lines else "")
        )
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.2,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text) or {}
        level = str(data.get("risk_level") or "low").lower()
        if level not in _VALID:
            level = "low"
        return RiskOutput(
            risk_level=level,
            reasons=[str(r) for r in (data.get("reasons") or [])],
        )
