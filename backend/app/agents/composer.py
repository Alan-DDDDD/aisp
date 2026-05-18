from app.agents.base import BaseAgent
from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.schemas.agent import AgentContext, ComposerInput, ComposerOutput
from app.workflow import workspace_registry

SYSTEM_PROMPT = """你是一個企業客服 Composer agent。
依據使用者訊息、上游 agent 提供的意圖、工具結果、知識來源與語氣建議，
撰寫專業、同理且具體的客服回覆。

寫作守則（優先級由高至低）：
1. **嚴禁編造事實。** 任何具體數字、時間、流程步驟、聯絡電話、辦法名稱，
   都必須能在「工具結果」或「可引用的知識來源」中找到對應依據。
2. 若有「工具結果」，**請優先依據工具結果回覆**，並自然地告訴使用者你做了什麼動作
   （例如：「我用 calculator 算了一下，結果是 89.6」）。工具結果是經過程式
   計算的事實，請直接採用，不要質疑或反推。
3. 若沒有「工具結果」且「可引用的知識來源」為空或明顯無關，**請直接告知
   使用者「目前知識庫中沒有相關資訊，建議改詢問人工客服或對應部門」**，
   不要套用其他常識或經驗來填補答案。
4. 不確定時要承諾後續跟進，不要編造資訊。
5. 回覆要直接、不要重複問題；若有引用文件，請自然地融入回覆。"""


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
        # TA5：tool 命中時優先；若有錯誤把錯誤透露給 composer
        if payload.tool_called and payload.tool_result:
            parts.append(
                f"工具結果（{payload.tool_called}）：\n{payload.tool_result}"
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
            parts.append("可引用的知識來源：\n" + "\n".join(doc_lines))
        else:
            parts.append(
                "可引用的知識來源：（無，retrieval 沒有找到足夠相關的文件 — "
                "請按守則 #2 處理）"
            )
        return "\n\n".join(parts)
