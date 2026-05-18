"""Inline keyboard callback_data 解析與分派。

callback_data 格式（見 notifier）：
  gz:<interaction_id>:use:<tool_id>     → 灰色區選工具
  gz:<interaction_id>:gap               → 灰色區判 GAP
  ap:<task_id>:approve|reject|refine|retry|abandon

設計：parse_callback() 純函式，回 `ParsedCallback`；dispatch() 由 bot.py 接 PTB
handler 後呼叫。Approval / 灰色區的實際業務分別走 ApprovalService / PendingRequests。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)


GrayKind = Literal["use", "gap"]
ApprovalAction = Literal["approve", "reject", "refine", "retry", "abandon"]


@dataclass
class GrayCallback:
    interaction_id: str
    kind: GrayKind
    tool_id: str | None = None  # kind=="use" 時填


@dataclass
class ApprovalCallback:
    task_id: str
    action: ApprovalAction


ParsedCallback = GrayCallback | ApprovalCallback | None


def parse_callback(data: str) -> ParsedCallback:
    """解析 callback_data；無效或未知格式回 None。"""
    if not data:
        return None
    parts = data.split(":")
    if len(parts) < 2:
        return None

    head = parts[0]
    if head == "gz" and len(parts) >= 3:
        interaction_id = parts[1]
        kind = parts[2]
        if kind == "use" and len(parts) >= 4:
            return GrayCallback(
                interaction_id=interaction_id, kind="use", tool_id=parts[3]
            )
        if kind == "gap":
            return GrayCallback(interaction_id=interaction_id, kind="gap")
        return None

    if head == "ap" and len(parts) >= 3:
        task_id = parts[1]
        action = parts[2]
        if action in {"approve", "reject", "refine", "retry", "abandon"}:
            return ApprovalCallback(task_id=task_id, action=action)  # type: ignore[arg-type]
        return None

    return None
