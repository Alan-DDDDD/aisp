"""Tool registry — process 內的工具表。

M6 起加上 workspace scoping（PLAN §22.5.8）：
- workspace_id=None    → global，所有 workspace 可見
- workspace_id="cs"    → 只給 cs workspace 用
- 既有的 `register(tool)` 呼叫保持 backward compatible（預設 None = global）
- 新介面：`list_for_workspace(ws_id)` 回該 workspace 看得到的 tool_ids
"""

from __future__ import annotations

from dataclasses import dataclass

from app.tools.base import BaseTool


@dataclass
class _Entry:
    tool: BaseTool
    workspace_id: str | None = None


_registry: dict[str, _Entry] = {}


def register(tool: BaseTool, *, workspace_id: str | None = None) -> None:
    """workspace_id=None 代表 global tool（builtin 工具預設）。"""
    if tool.id in _registry:
        raise ValueError(f"Tool already registered: {tool.id}")
    _registry[tool.id] = _Entry(tool=tool, workspace_id=workspace_id)


def unregister(tool_id: str) -> bool:
    """M6 之後 generated tool 可能被 deprecate / revoke。回 True 代表確實刪掉。"""
    return _registry.pop(tool_id, None) is not None


def get(tool_id: str) -> BaseTool:
    if tool_id not in _registry:
        raise KeyError(f"Tool not found: {tool_id}")
    return _registry[tool_id].tool


def workspace_of(tool_id: str) -> str | None:
    if tool_id not in _registry:
        raise KeyError(f"Tool not found: {tool_id}")
    return _registry[tool_id].workspace_id


def list_ids() -> list[str]:
    """所有註冊的 tool（無 scope 過濾，給 admin / retriever rebuild 用）。"""
    return list(_registry.keys())


def list_for_workspace(workspace_id: str | None) -> list[str]:
    """workspace 看得到的 tool：global + 自己 scope 的。

    workspace_id=None 視為 admin / 跨 workspace 場景，回所有 global tool（不含 scoped）。
    """
    if workspace_id is None:
        return [tid for tid, e in _registry.items() if e.workspace_id is None]
    return [
        tid
        for tid, e in _registry.items()
        if e.workspace_id is None or e.workspace_id == workspace_id
    ]


def clear() -> None:
    _registry.clear()
