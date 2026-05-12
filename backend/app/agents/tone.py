import logging

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, ToneInput, ToneOutput

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是企業客服語氣建議 agent。
依使用者訊息與對話歷史，建議客服回覆應採取的語氣。

可選 tone：
- empathetic：投訴、情緒激動、客戶受困
- professional：一般詢問，禮貌中性
- direct：技術問題、需具體步驟
- cautious：法務、合規、敏感議題
- apologetic：本公司有錯需致歉

輸出嚴格 JSON：
{"tone": "<上面五選一>", "rationale": "<一句話原因>"}"""


_VALID = {"empathetic", "professional", "direct", "cautious", "apologetic"}


class ToneAgent(BaseAgent):
    id = "tone"
    input_schema = ToneInput
    output_schema = ToneOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, ctx: AgentContext, payload: ToneInput) -> ToneOutput:  # type: ignore[override]
        history_str = "\n".join(
            f"[{m.get('role') or m.get('sender_role', 'user')}] {m.get('content', '')}"
            for m in payload.history[-4:]
        )
        intent_str = (
            f"category={payload.intent.category}, intent={payload.intent.intent}"
            if payload.intent
            else ""
        )
        user_content = (
            f"使用者訊息：{payload.message}\n\n"
            + (f"意圖：{intent_str}\n\n" if intent_str else "")
            + (f"最近對話：\n{history_str}" if history_str else "")
        )
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.2,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text) or {}
        tone = str(data.get("tone") or "professional").lower()
        if tone not in _VALID:
            tone = "professional"
        return ToneOutput(tone=tone, rationale=str(data.get("rationale") or ""))
