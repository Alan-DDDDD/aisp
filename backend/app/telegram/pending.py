"""PendingRequests — 短期的「等使用者回應」未決倉儲。

設計（PLAN §22.8）：
- Phase A 灰色區詢問 → 使用者按按鈕 → 主流程拿到結果繼續跑
- 這個倉儲只服務「短期 (< 30 min)」的請求。長期審核（Phase B）走 DB，不走這裡。
- Server restart 會遺失 pending 內容 —— 這是 acceptable 取捨（restart 後使用者重發 query）

執行緒安全：python-telegram-bot handler 與 web 主流程都會碰，用 asyncio.Lock 保護。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class PendingEntry:
    """一筆未決請求。`future` 由建立者 await，由 callback handler 完成。"""

    interaction_id: str
    purpose: str  # 例如 "gray_zone:step_id" — 給 audit 用
    future: asyncio.Future[dict[str, Any]] = field(default_factory=lambda: asyncio.get_event_loop().create_future())
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class PendingRequests:
    """Process-local store；單機 dev 用沒問題。

    用法：
        store = PendingRequests()
        entry = store.create(purpose="gray_zone:s1")
        # ...send Telegram message with entry.interaction_id...
        result = await store.wait(entry.interaction_id, timeout=600)
        # callback handler 那邊：
        store.complete(interaction_id, {"decision": "USE", "tool_id": "kb_search"})
    """

    def __init__(self) -> None:
        self._entries: dict[str, PendingEntry] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _new_id() -> str:
        # Telegram callback_data <= 64 bytes，prefix 約 6 字，留 ~55 給 id
        return uuid.uuid4().hex[:16]

    async def create(self, purpose: str, **metadata: Any) -> PendingEntry:
        async with self._lock:
            interaction_id = self._new_id()
            loop = asyncio.get_running_loop()
            entry = PendingEntry(
                interaction_id=interaction_id,
                purpose=purpose,
                future=loop.create_future(),
                metadata=metadata,
            )
            self._entries[interaction_id] = entry
            log.debug("PendingRequests.create id=%s purpose=%s", interaction_id, purpose)
            return entry

    async def complete(self, interaction_id: str, result: dict[str, Any]) -> bool:
        """callback handler 呼叫；回 True 代表確實 resolve 了 future。"""
        async with self._lock:
            entry = self._entries.get(interaction_id)
            if entry is None:
                log.warning(
                    "PendingRequests.complete: unknown interaction_id=%s", interaction_id
                )
                return False
            if entry.future.done():
                log.warning(
                    "PendingRequests.complete: future already done id=%s", interaction_id
                )
                return False
            entry.future.set_result(result)
            del self._entries[interaction_id]
            return True

    async def wait(self, interaction_id: str, timeout: float | None = None) -> dict[str, Any]:
        async with self._lock:
            entry = self._entries.get(interaction_id)
        if entry is None:
            raise KeyError(f"interaction_id not found: {interaction_id}")
        try:
            return await asyncio.wait_for(entry.future, timeout=timeout)
        except TimeoutError:
            async with self._lock:
                self._entries.pop(interaction_id, None)
            raise

    async def cancel(self, interaction_id: str) -> None:
        async with self._lock:
            entry = self._entries.pop(interaction_id, None)
        if entry and not entry.future.done():
            entry.future.cancel()

    async def gc(self, max_age_s: float = 3600.0) -> int:
        """清掉太老的 entry，避免記憶體累積。回傳清掉幾個。"""
        now = time.time()
        removed = 0
        async with self._lock:
            for iid in list(self._entries.keys()):
                if now - self._entries[iid].created_at > max_age_s:
                    e = self._entries.pop(iid)
                    if not e.future.done():
                        e.future.cancel()
                    removed += 1
        return removed

    def size(self) -> int:
        return len(self._entries)


# 預設 process-wide instance。測試可以 new 一個獨立 store。
_default = PendingRequests()


def get_default() -> PendingRequests:
    return _default
