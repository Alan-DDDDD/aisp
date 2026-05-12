import logging

from app.agents._json_util import parse_json_loose
from app.agents.base import BaseAgent
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, TicketDecisionInput, TicketDecisionOutput
from app.tools import registry as tool_registry
from app.tools.ticket_create import TicketCreateInput

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是 IT helpdesk 工單決策 agent。
判斷使用者的 IT 問題是否需要開單追蹤。

開單原則：
- 一般 FAQ 可解、使用者可自助 → 不開
- 需 IT 親自介入（密碼重設驗證失敗、權限申請、硬體故障、軟體採購）→ 開
- 安全事件（資料外洩、裝置遺失、可疑連線）→ 必開（並標為 high priority）

輸出嚴格 JSON：
{
  "should_create_ticket": true/false,
  "summary": "<10-30 字工單摘要>",
  "rationale": "<為什麼開或不開>"
}"""


class TicketDecisionAgent(BaseAgent):
    id = "ticket_decision"
    input_schema = TicketDecisionInput
    output_schema = TicketDecisionOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(  # type: ignore[override]
        self, ctx: AgentContext, payload: TicketDecisionInput
    ) -> TicketDecisionOutput:
        intent_str = (
            f"category={payload.intent.category}, intent={payload.intent.intent}"
            if payload.intent
            else ""
        )
        user_content = (
            f"使用者訊息：{payload.message}\n\n"
            + (f"意圖：{intent_str}\n\n" if intent_str else "")
            + (f"預定解答：{payload.solution_text[:300]}" if payload.solution_text else "")
        )
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            response_format="json",
            temperature=0.1,
        )
        resp = await self.provider.generate(req)
        data = parse_json_loose(resp.text) or {}

        should = bool(data.get("should_create_ticket"))
        summary = str(data.get("summary") or payload.message[:40])
        rationale = str(data.get("rationale") or "")

        ticket_id: str | None = None
        if should:
            try:
                tool = tool_registry.get("ticket_create")
                tool_out = await tool.call(
                    ctx, TicketCreateInput(summary=summary, rationale=rationale)
                )
                ticket_id = tool_out.ticket_id
            except Exception as e:  # noqa: BLE001
                log.warning("TicketCreateTool failed: %s", e)

        return TicketDecisionOutput(
            should_create_ticket=should,
            summary=summary,
            rationale=rationale,
            ticket_id=ticket_id,
        )
