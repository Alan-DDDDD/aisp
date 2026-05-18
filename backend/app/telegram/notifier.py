"""Notifier — 高階訊息組裝（PLAN §22.4.4、§22.5.7）。

職責：把 domain 物件（StepDecision / SynthesisResult）轉成 Telegram 訊息。
不關心 Sender 怎麼寄出 —— 那是 Sender 的事。

訊息格式採 HTML，因為使用者資料（description、query、error message）可能含 `*`/`_`/`` ` ``
等 legacy Markdown 控制字元，會讓 Telegram parser 400。HTML 只需處理 `< > &`，
`html.escape()` 即可一網打盡。
"""

from __future__ import annotations

import html
import logging

from app.synthesis.schemas import PlannerStep, ToolCandidate
from app.telegram.sender import InlineButton, Sender, SentMessage

log = logging.getLogger(__name__)


def _h(text: str) -> str:
    """HTML-escape 使用者資料；空字串保持空字串。"""
    return html.escape(text or "", quote=False)


# ── callback_data 編碼 ───────────────────────────────────────────────
# Telegram 限制：純 ASCII 且 <= 64 bytes。我們用「短鍵 + interaction_id」格式：
#   gz:<interaction_id>:use:<tool_id>     灰色區選某個既有工具
#   gz:<interaction_id>:gap                灰色區判給 GAP
#   ap:<task_id>:approve                   approval：通過
#   ap:<task_id>:reject                    approval：拒絕
#   ap:<task_id>:refine                    approval：請使用者給 hint


def _truncate(text: str, n: int = 80) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


# ── Phase A：灰色區詢問 ─────────────────────────────────────────────


def render_gray_zone_message(
    query: str,
    step: PlannerStep,
    candidates: list[ToolCandidate],
) -> str:
    lines = [
        "🤔 <b>請協助判斷工具選擇</b>",
        "",
        f"<b>Query</b>: {_h(_truncate(query, 120))}",
        f"<b>Step</b>: {_h(step.description)}",
        "",
        "<b>候選工具</b>：",
    ]
    if not candidates:
        lines.append("  <i>（無候選工具，極可能是 GAP）</i>")
    else:
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"  <b>{i}.</b> <code>{_h(c.tool_id)}</code> (相似度 {c.similarity:.2f})"
            )
            if c.description:
                lines.append(f"      <i>{_h(_truncate(c.description, 100))}</i>")
            if c.when_not_to_use:
                lines.append(f"      ⚠️ {_h(_truncate(c.when_not_to_use, 100))}")
    return "\n".join(lines)


def render_gray_zone_buttons(
    interaction_id: str,
    candidates: list[ToolCandidate],
    max_buttons: int = 4,
) -> list[list[InlineButton]]:
    rows: list[list[InlineButton]] = []
    # 每個候選一顆按鈕（每行兩個，最多 max_buttons 個）
    use_buttons = [
        InlineButton(
            text=f"✅ 用 {c.tool_id}",
            callback_data=f"gz:{interaction_id}:use:{c.tool_id}"[:64],
        )
        for c in candidates[:max_buttons]
    ]
    while use_buttons:
        rows.append(use_buttons[:2])
        use_buttons = use_buttons[2:]

    # 加上「都不合適 → 做新工具」按鈕
    rows.append(
        [
            InlineButton(
                text="🛠 做新工具 (GAP)",
                callback_data=f"gz:{interaction_id}:gap",
            )
        ]
    )
    return rows


# ── Phase B：審核請求 ───────────────────────────────────────────────


def render_approval_message(
    task_id: str,
    tool_id: str,
    description: str,
    triggered_by_query: str,
    triggered_by_user: str,
    test_passed: int,
    test_failed: int,
    attempt_count: int,
    behavior_observations_by_type: dict[str, int],
    workspace_id: str,
) -> str:
    obs_lines: list[str] = []
    if behavior_observations_by_type:
        for k, v in behavior_observations_by_type.items():
            obs_lines.append(f"  • <code>{_h(k)}</code> × {v}")
    else:
        obs_lines.append("  • <i>無</i>")

    lines = [
        "🔍 <b>新工具待審核</b>",
        "",
        f"<b>Tool</b>: <code>{_h(tool_id)}</code> (workspace: <code>{_h(workspace_id)}</code>)",
        f"<b>目的</b>: {_h(_truncate(description, 200))}",
        "",
        "<b>觸發來源</b>",
        f"  • User: <code>{_h(triggered_by_user)}</code>",
        f"  • Query: <i>{_h(_truncate(triggered_by_query, 120))}</i>",
        "",
        "<b>測試結果</b>",
        f"  • ✅ {test_passed} passed",
    ]
    if test_failed:
        lines.append(f"  • ❌ {test_failed} failed")
    lines.append(f"  • 嘗試 round: {attempt_count}")
    lines.append("")
    lines.append("<b>Sandbox 觀察行為</b>")
    lines.extend(obs_lines)
    return "\n".join(lines)


def render_approval_buttons(task_id: str) -> list[list[InlineButton]]:
    return [
        [
            InlineButton(text="✅ Approve", callback_data=f"ap:{task_id}:approve"),
            InlineButton(text="❌ Reject", callback_data=f"ap:{task_id}:reject"),
        ],
        [
            InlineButton(text="📝 Refine with hint", callback_data=f"ap:{task_id}:refine"),
        ],
    ]


# ── Phase B：rescue（N 次失敗）─────────────────────────────────────


def render_rescue_message(
    task_id: str,
    tool_id: str,
    attempts: int,
    last_error: str,
) -> str:
    return (
        "❌ <b>自動合成失敗</b>\n\n"
        f"<b>Tool</b>: <code>{_h(tool_id)}</code>\n"
        f"<b>Attempts</b>: {attempts}/{attempts}\n"
        f"<b>Last error</b>: <i>{_h(_truncate(last_error, 300))}</i>\n\n"
        "請選擇下一步："
    )


def render_rescue_buttons(task_id: str) -> list[list[InlineButton]]:
    return [
        [
            InlineButton(text="🤖 再試一次", callback_data=f"ap:{task_id}:retry"),
            InlineButton(text="📝 我給 hint", callback_data=f"ap:{task_id}:refine"),
        ],
        [InlineButton(text="❌ 放棄", callback_data=f"ap:{task_id}:abandon")],
    ]


# ── Notifier 高階介面 ───────────────────────────────────────────────


class Notifier:
    """每個介面只負責「組訊息 + 呼叫 sender」，不持有狀態。"""

    def __init__(self, sender: Sender, default_chat_id: str = "") -> None:
        self.sender = sender
        self.default_chat_id = default_chat_id

    def _chat(self, chat_id: str | None) -> str:
        return chat_id or self.default_chat_id

    async def notify_gray_zone(
        self,
        *,
        interaction_id: str,
        query: str,
        step: PlannerStep,
        candidates: list[ToolCandidate],
        chat_id: str | None = None,
    ) -> SentMessage:
        text = render_gray_zone_message(query, step, candidates)
        buttons = render_gray_zone_buttons(interaction_id, candidates)
        return await self.sender.send(self._chat(chat_id), text, buttons=buttons)

    async def notify_approval(
        self,
        *,
        task_id: str,
        tool_id: str,
        description: str,
        triggered_by_query: str,
        triggered_by_user: str,
        test_passed: int,
        test_failed: int,
        attempt_count: int,
        behavior_observations_by_type: dict[str, int],
        workspace_id: str,
        chat_id: str | None = None,
    ) -> SentMessage:
        text = render_approval_message(
            task_id=task_id,
            tool_id=tool_id,
            description=description,
            triggered_by_query=triggered_by_query,
            triggered_by_user=triggered_by_user,
            test_passed=test_passed,
            test_failed=test_failed,
            attempt_count=attempt_count,
            behavior_observations_by_type=behavior_observations_by_type,
            workspace_id=workspace_id,
        )
        buttons = render_approval_buttons(task_id)
        return await self.sender.send(self._chat(chat_id), text, buttons=buttons)

    async def notify_rescue(
        self,
        *,
        task_id: str,
        tool_id: str,
        attempts: int,
        last_error: str,
        chat_id: str | None = None,
    ) -> SentMessage:
        text = render_rescue_message(task_id, tool_id, attempts, last_error)
        buttons = render_rescue_buttons(task_id)
        return await self.sender.send(self._chat(chat_id), text, buttons=buttons)
