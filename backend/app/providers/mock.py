import asyncio
import json
import random
import time

from app.providers.base import GenerationRequest, GenerationResponse, LLMProvider

_INTENT_KEYWORDS: list[tuple[str, str, str]] = [
    # (keyword, category, intent)
    ("車貸", "loan", "loan_inquiry"),
    ("信貸", "loan", "loan_inquiry"),
    ("貸款", "loan", "loan_inquiry"),
    ("利率", "loan", "rate_inquiry"),
    ("申請", "loan", "application_inquiry"),
    ("投訴", "complaint", "complaint"),
    ("抱怨", "complaint", "complaint"),
    ("特休", "hr", "leave_inquiry"),
    ("請假", "hr", "leave_inquiry"),
    ("薪資", "hr", "salary_inquiry"),
    ("VPN", "it", "vpn_issue"),
    ("無法連線", "it", "connectivity_issue"),
    ("密碼", "it", "credential_issue"),
    ("合約", "legal", "contract_review"),
    ("NDA", "legal", "contract_review"),
]

_ALL_CATEGORIES = ["loan", "complaint", "hr", "it", "legal", "general"]


class MockProvider(LLMProvider):
    """Phase 1 用的可預測 provider。

    模式：
    - req.logprobs=True：類別 token-only 輸出 + 合成 logprobs（給 Router Stage A 用）
    - req.response_format == "json"：依關鍵字回傳 RouterOutput 結構（Router Stage B 用）
    - 其他：回傳一段引用使用者訊息的友善範本
    """

    name = "mock"

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        start = time.perf_counter()
        await asyncio.sleep(random.uniform(0.05, 0.15))  # 模擬網路延遲

        last_user = self._last_user_message(req)
        matched = self._match_category(last_user)

        logprobs_content: list[dict] | None = None
        if req.logprobs:
            category = matched[0] if matched else "general"
            text = category
            logprobs_content = self._synth_logprobs(
                top_category=category,
                confident=matched is not None,
            )
        elif req.response_format == "json":
            text = self._classify(last_user, matched)
        else:
            text = self._reply(last_user)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return GenerationResponse(
            text=text,
            # 若呼叫端指定了 model 就回傳該名稱，方便測試驗證 routing
            model=req.model or "mock-v1",
            usage={"prompt_tokens": len(last_user), "completion_tokens": len(text)},
            latency_ms=latency_ms,
            logprobs_content=logprobs_content,
        )

    @staticmethod
    def _last_user_message(req: GenerationRequest) -> str:
        for msg in reversed(req.messages):
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return ""

    @staticmethod
    def _match_category(message: str) -> tuple[str, str] | None:
        for keyword, category, intent in _INTENT_KEYWORDS:
            if keyword.lower() in message.lower():
                return (category, intent)
        return None

    @staticmethod
    def _classify(message: str, matched: tuple[str, str] | None) -> str:
        if matched:
            category, intent = matched
            return json.dumps(
                {"intent": intent, "category": category},
                ensure_ascii=False,
            )
        return json.dumps(
            {"intent": "general_inquiry", "category": "general"},
            ensure_ascii=False,
        )

    @staticmethod
    def _synth_logprobs(top_category: str, confident: bool) -> list[dict]:
        """產生合成 logprobs：top_category 給高機率，其他類別給低機率。

        - confident=True → top ~ 0.86，其他平均 ~ 0.028（softmax 後）
        - confident=False → top ~ 0.36，其他平均 ~ 0.13（softmax 後）
        """
        target_lp = -0.15 if confident else -1.0
        other_lp = -3.5 if confident else -2.0
        top_logprobs = [
            {
                "token": cat,
                "logprob": target_lp if cat == top_category else other_lp,
            }
            for cat in _ALL_CATEGORIES
        ]
        return [
            {
                "token": top_category,
                "logprob": target_lp,
                "top_logprobs": top_logprobs,
            }
        ]

    @staticmethod
    def _reply(message: str) -> str:
        snippet = message.strip()
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."
        return (
            f"您好，關於您提到的「{snippet}」，"
            f"我們目前以 mock provider 回覆 — 等 Phase 2 接上真實 LLM 後，"
            f"這裡會是 Composer agent 整合知識來源與語氣建議的最終草稿。"
        )
