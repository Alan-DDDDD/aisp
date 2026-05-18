"""Phase 6 M3 — Notifier 組訊息 + 把對 sender 的呼叫驗證一遍。"""

from __future__ import annotations

from app.synthesis.schemas import PlannerStep, ToolCandidate
from app.telegram.notifier import Notifier
from app.telegram.sender import FakeSender


def _step() -> PlannerStep:
    return PlannerStep(id="s1", description="從 C-123 拿訂單", requires_tool=True)


async def test_notify_gray_zone_with_candidates():
    sender = FakeSender()
    notifier = Notifier(sender, default_chat_id="chat-1")

    candidates = [
        ToolCandidate(
            tool_id="get_orders",
            similarity=0.72,
            description="取得客戶訂單",
            when_not_to_use="不要用於跨客戶彙總",
        ),
        ToolCandidate(tool_id="query_db", similarity=0.55, description="通用查詢"),
    ]
    await notifier.notify_gray_zone(
        interaction_id="iid-x",
        query="客戶 C-123 上個月買了什麼？",
        step=_step(),
        candidates=candidates,
    )

    assert len(sender.sent) == 1
    msg = sender.sent[0]
    assert msg["chat_id"] == "chat-1"
    assert "get_orders" in msg["text"]
    assert "0.72" in msg["text"]
    # callback_data 帶 interaction_id
    flat = [b for row in msg["buttons"] for b in row]
    assert all(b.callback_data.startswith("gz:iid-x:") for b in flat)
    # 一定要有「做新工具」逃生口
    assert any("gap" in b.callback_data for b in flat)


async def test_notify_gray_zone_no_candidates():
    sender = FakeSender()
    notifier = Notifier(sender, default_chat_id="chat-1")
    await notifier.notify_gray_zone(
        interaction_id="iid",
        query="x",
        step=_step(),
        candidates=[],
    )
    msg = sender.sent[0]
    # 無候選只剩 GAP 按鈕
    flat = [b for row in msg["buttons"] for b in row]
    assert len(flat) == 1
    assert flat[0].callback_data == "gz:iid:gap"


async def test_notify_approval_includes_behavior_summary():
    sender = FakeSender()
    notifier = Notifier(sender, default_chat_id="chat-1")
    await notifier.notify_approval(
        task_id="syn-1",
        tool_id="get_orders",
        description="取得客戶訂單",
        triggered_by_query="客戶 C-123 上個月買了什麼？",
        triggered_by_user="alan",
        test_passed=4,
        test_failed=0,
        attempt_count=2,
        behavior_observations_by_type={"socket": 1, "open": 3},
        workspace_id="cs",
    )
    msg = sender.sent[0]
    assert "get_orders" in msg["text"]
    assert "socket" in msg["text"]
    assert "4 passed" in msg["text"]
    # 三個 action 按鈕都在
    flat = [b for row in msg["buttons"] for b in row]
    actions = {b.callback_data.split(":")[2] for b in flat}
    assert actions == {"approve", "reject", "refine"}


async def test_notify_rescue_buttons():
    sender = FakeSender()
    notifier = Notifier(sender, default_chat_id="chat-1")
    await notifier.notify_rescue(
        task_id="syn-1", tool_id="get_orders", attempts=3, last_error="ImportError"
    )
    flat = [b for row in sender.sent[0]["buttons"] for b in row]
    actions = {b.callback_data.split(":")[2] for b in flat}
    assert actions == {"retry", "refine", "abandon"}
