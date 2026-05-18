from typing import Any

from app.agents.base import BaseAgent
from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, ComposerInput, ComposerOutput
from app.workflow import workspace_registry


def _is_effectively_empty(value: Any) -> bool:
    """判斷 tool_result 是否「實質為空」— 沒有任何 LLM 可引用的內容。

    例如 kb_search 回 `{"docs": [], "kb_name": "faq", "query": "..."}` — 雖然
    dict 有 3 個 key，但實質「我搜了什麼都沒找到」應視為無資料。
    遞迴定義：None / 0 長度 collection / 空字串 / 全部 value 都遞迴為空的 dict
    被視為空。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    if isinstance(value, dict):
        if not value:
            return True
        # 忽略 metadata-like 欄位（query 是 echo 不算 evidence）
        IGNORE_KEYS = {"query", "kb_name", "workspace_id"}
        meaningful = {k: v for k, v in value.items() if k not in IGNORE_KEYS}
        if not meaningful:
            # 整個 dict 都是 metadata（沒有實質 payload）→ 視為空
            return True
        return all(_is_effectively_empty(v) for v in meaningful.values())
    # number / bool / 其他 scalar → 視為有值
    return False

SYSTEM_PROMPT = """你是一個企業客服 Composer agent。
依據使用者訊息、上游 agent 提供的意圖、工具結果、知識來源與語氣建議，
撰寫專業、同理且具體的客服回覆。

【最重要的守則 — 違反等同產出錯誤資訊】

**規則 A — 無依據絕對不答**：
若上下文中 **沒有 `[TOOL_RESULT]` 區塊** 且 **沒有 `[KNOWLEDGE]` 區塊**，
你**只准輸出**這段話（一字不差）：
「目前知識庫中沒有相關資訊，建議改詢問人工客服或對應部門。」

不准補充、不准舉例、不准用常識填空、不准做計算、不准做單位轉換、
不准估算、不准提及「我算了」「我查了」「依據」等暗示有依據的字眼。
即使使用者問題很簡單（例如「1+1 等於多少」「攝氏 0 度是幾度華氏」），
只要上下文沒明確證據，也一律輸出規則 A 那段話。

**規則 B — 有 `[TOOL_RESULT]` 區塊就用工具結果**：
依該結果回覆使用者，並自然地告訴他你呼叫了哪個工具。
工具結果是程式計算的事實，直接採用，不要質疑或反推。

**規則 C — 有 `[KNOWLEDGE]` 區塊才能引用其內容**：
回覆時只能用該區塊內出現的事實（具體數字、時間、流程、辦法名稱、聯絡方式等）。
引用要自然融入。

【其他】
- 回覆要直接、不要重複問題
- 不確定時承諾後續跟進，不要編造"""


class ComposerAgent(BaseAgent):
    id = "composer"
    input_schema = ComposerInput
    output_schema = ComposerOutput

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, ctx: AgentContext, payload: ComposerInput) -> ComposerOutput:  # type: ignore[override]
        # ── Scope guard：intent.category 不在本 workspace 允許範圍內，直接拒答。
        scope_refusal = self._scope_refusal(ctx, payload)
        if scope_refusal is not None:
            return ComposerOutput(text=scope_refusal, citations=[])

        # ── 相關性過濾：低於門檻的 doc 視為雜訊，不傳給 LLM、也不放 citation。
        relevant_docs = [
            d for d in payload.docs
            if (d.get("score") or 0.0) >= settings.composer_min_doc_score
        ]

        # ── HARD anti-hallucination guard：完全沒任何依據時，**不呼叫 LLM**，
        # 直接 return 固定句子。8B 模型對嚴格 prompt 不夠服從（多次實測會幻覺
        # 「我用工具算了 X」即使 tool_called=null），這條 guard 才是真正可靠的
        # 保險絲。
        has_tool_result = (
            payload.tool_called
            and payload.tool_result
            and not _is_effectively_empty(payload.tool_result)
        )
        has_docs = bool(relevant_docs)
        if not has_tool_result and not has_docs:
            return ComposerOutput(
                text="目前知識庫中沒有相關資訊，建議改詢問人工客服或對應部門。",
                citations=[],
            )

        context_block = self._build_context(payload, relevant_docs)
        system = SYSTEM_PROMPT + ("\n\n上下文：\n" + context_block if context_block else "")
        req = GenerationRequest(
            system=system,
            messages=[{"role": "user", "content": payload.message}],
            temperature=0.4,
        )
        resp = await self.provider.generate(req)

        citations = []
        for d in relevant_docs:
            meta = d.get("metadata") or {}
            citations.append(
                {
                    "title": d.get("title") or meta.get("title"),
                    "source": d.get("source") or d.get("document_id") or meta.get("doc_id"),
                    "score": d.get("score"),
                }
            )
        return ComposerOutput(text=resp.text.strip(), citations=citations)

    @staticmethod
    def _scope_refusal(ctx: AgentContext, payload: ComposerInput) -> str | None:
        """若 intent 顯示問題不屬於本 workspace 範圍，回傳婉拒文字；否則 None。"""
        if not payload.intent or not payload.intent.category:
            return None
        allowed = workspace_registry.get_allowed_categories(ctx.workspace_id)
        if not allowed:  # 未設定允許清單 → 視為不限制
            return None
        category = payload.intent.category.lower()
        if category in allowed:
            return None
        ws_name = workspace_registry.display_name(ctx.workspace_id)
        return (
            f"您詢問的內容看起來屬於「{category}」領域，本部門（{ws_name}）"
            "僅處理特定範圍的問題。建議您切換到對應部門的聊天室再次提問，"
            "以取得最精準的協助。"
        )

    @staticmethod
    def _build_context(payload: ComposerInput, relevant_docs: list[dict]) -> str:
        parts = []
        if payload.intent:
            parts.append(
                f"意圖：{payload.intent.intent}（類別：{payload.intent.category}）"
            )
        # TA5：tool 命中時優先；用 [TOOL_RESULT] 標籤跟 system prompt 內提到的
        # 「工具結果」字眼區隔，避免 LLM 看到 prompt 規則就以為有資料。
        # 若 tool_result「實質為空」（所有 value 都是空 list/dict/None/空字串），
        # 也跳過 inject — 否則 composer 看到 {"docs":[]} 還是會幻覺生內容
        if (
            payload.tool_called
            and payload.tool_result
            and not _is_effectively_empty(payload.tool_result)
        ):
            parts.append(
                f"[TOOL_RESULT]\ntool: {payload.tool_called}\noutput: {payload.tool_result}\n[/TOOL_RESULT]"
            )
        if payload.tone:
            tone_line = f"建議語氣：{payload.tone}"
            if payload.tone_rationale:
                tone_line += f"（{payload.tone_rationale}）"
            parts.append(tone_line)
        if payload.policy:
            note = payload.policy.get("compliance_note") or ""
            cits = payload.policy.get("citations") or []
            vios = payload.policy.get("violations") or []
            policy_lines = []
            if note:
                policy_lines.append(f"合規提示：{note}")
            if cits:
                policy_lines.append(f"相關規範：{', '.join(cits)}")
            if vios:
                policy_lines.append(f"潛在違規：{', '.join(vios)}")
            if policy_lines:
                parts.append("\n".join(policy_lines))
        if payload.risk:
            level = payload.risk.get("risk_level", "low")
            reasons = payload.risk.get("reasons") or []
            risk_line = f"風險等級：{level}"
            if reasons:
                risk_line += f"（{'；'.join(reasons[:2])}）"
            parts.append(risk_line)
        if payload.clause_analysis:
            ca = payload.clause_analysis
            kp = ca.get("key_points") or []
            parts.append(
                f"條款分析：{ca.get('clause_type', '?')} / 風險 {ca.get('risk_level', '?')}\n"
                f"建議：{ca.get('suggestion', '')}"
                + (f"\n重點：{'；'.join(kp[:3])}" if kp else "")
            )
        if payload.ticket and payload.ticket.get("ticket_id"):
            parts.append(
                f"系統已為此事件建立工單 {payload.ticket['ticket_id']}，"
                f"請於回覆中告知客戶並承諾 IT 同仁將儘速跟進。"
            )
        if relevant_docs:
            doc_lines = []
            for i, d in enumerate(relevant_docs, 1):
                title = d.get("title") or (d.get("metadata") or {}).get("title") or "未命名"
                chunk = (d.get("text") or d.get("chunk") or d.get("content") or "")[:240]
                score = d.get("score")
                score_str = f"score={score:.2f}" if isinstance(score, (int, float)) else ""
                doc_lines.append(f"  [{i}] {title}{f' ({score_str})' if score_str else ''}: {chunk}")
            parts.append("[KNOWLEDGE]\n" + "\n".join(doc_lines) + "\n[/KNOWLEDGE]")
        # 若 retrieval 沒結果，刻意 **省略整個** [KNOWLEDGE] 區塊，
        # 讓 LLM 在 prompt 上下文看不到任何「來源」字眼 → 強制走規則 A 的
        # 「無依據絕對不答」路徑。之前版本會塞一行「（無）」反而讓 LLM 把
        # 區塊當成存在、然後幻想出答案。
        return "\n\n".join(parts)
