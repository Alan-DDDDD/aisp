import logging

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, RouterInput, RouterOutput

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一個企業客服系統的意圖路由 agent。
讀取使用者訊息與最近的對話歷史，分類出意圖並輸出 JSON。

category 必須是以下其中之一：
- "loan"：所有貸款相關（車貸、信貸、房貸、利率、申貸資格、對保、信用評分等）
- "complaint"：客戶投訴、抱怨服務、要求退款
- "hr"：員工提問薪資、特休、請假、福利
- "it"：IT 故障、密碼、VPN、權限申請
- "legal"：合約審閱、合規、NDA、條款
- "general"：以上都不符合

輸出格式（嚴格 JSON，無 markdown 標籤、無註解、無前後贅字）：
{"intent": "<short_snake_case>", "category": "<上面六選一>"}

注意：不要輸出 confidence 或機率欄位。"""


_VALID_CATEGORIES = {"loan", "complaint", "hr", "it", "legal", "general"}


class RouterAgent(BaseAgent):
    id = "router"
    input_schema = RouterInput
    output_schema = RouterOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, ctx: AgentContext, payload: RouterInput) -> RouterOutput:  # type: ignore[override]
        history_str = self._format_history(payload.history)
        user_content = (
            f"訊息：{payload.message}\n\n最近對話：\n{history_str}"
            if history_str
            else payload.message
        )

        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.1,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text)
        if data is None:
            log.warning("RouterAgent: cannot parse output → fallback (raw=%r)", resp.text[:200])
            return RouterOutput(intent="general_inquiry", category="general")

        category = str(data.get("category", "general")).lower()
        if category not in _VALID_CATEGORIES:
            category = "general"

        return RouterOutput(
            intent=str(data.get("intent", "general_inquiry")),
            category=category,
        )

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        if not history:
            return ""
        lines = []
        for msg in history[-5:]:
            role = msg.get("role") or msg.get("sender_role", "user")
            content = msg.get("content", "")
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)
