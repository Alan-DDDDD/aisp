import logging

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, PolicyInput, PolicyOutput

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是企業合規檢核 agent。給你客戶意圖（category, intent）與訊息，判斷有沒有合規風險。

各 category 常見合規參考：
- loan：金管會「揭露利率與還款條件」「對保需本人」「個資保護」「DBR 22 倍上限」
- complaint：「30 日內回覆」「金融消費評議機制」
- hr：「勞基法 38 條（特休）」「勞基法 16 條（離職預告）」「個資保護法（員工資料）」
- it：「資安事件 72 小時通報」「資料外洩通報」「BYOD 設備管控」
- legal：「契約自由原則」「公平交易法」「個資法 GDPR」
- general：通常無特定合規條款

只在「明確涉及合規風險」時列出 violations；單純詢問通常 violations 為空、compliance_note 提示注意點即可。

輸出嚴格 JSON：
{
  "violations": ["<若有，明確違規條款 ID>"],
  "citations": ["<相關法規/內規 ID>"],
  "compliance_note": "<一句話提示客服需注意什麼，可空字串>"
}"""


class PolicyAgent(BaseAgent):
    id = "policy"
    input_schema = PolicyInput
    output_schema = PolicyOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, ctx: AgentContext, payload: PolicyInput) -> PolicyOutput:  # type: ignore[override]
        intent_str = (
            f"intent={payload.intent.intent}, category={payload.intent.category}"
            if payload.intent
            else f"category={payload.category}"
        )
        user_content = f"客戶訊息：{payload.message}\n\n{intent_str}"
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.2,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text) or {}
        return PolicyOutput(
            violations=[str(v) for v in (data.get("violations") or [])],
            citations=[str(c) for c in (data.get("citations") or [])],
            compliance_note=str(data.get("compliance_note") or ""),
        )
