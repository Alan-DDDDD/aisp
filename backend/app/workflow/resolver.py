"""變數解析 — workflow YAML 的 $event.x / $context.x / $<step>.x 語法。

設計原則：
- 純字串 `"$xxx"` → 整段被替換為解析值（可為 dict / list / None / scalar）
- 內嵌 `"prefix $x suffix"` → 字串內插，引用值用 str() 轉
- dict / list 遞迴處理
- 引用不存在時回傳 None，並由呼叫端決定如何處理
"""

from __future__ import annotations

import re
from typing import Any

_REF_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)")
_PURE_REF_RE = re.compile(r"^\$([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)$")


def collect_refs(value: Any) -> set[str]:
    """掃出所有 $xxx 引用的「根 namespace」（第一段）— 用於推依賴。

    例如 $router.intent → 'router'，$event.message → 'event'。
    """
    roots: set[str] = set()
    _walk(value, roots)
    return roots


def _walk(value: Any, roots: set[str]) -> None:
    if isinstance(value, str):
        for m in _REF_RE.finditer(value):
            roots.add(m.group(1).split(".", 1)[0])
    elif isinstance(value, dict):
        for v in value.values():
            _walk(v, roots)
    elif isinstance(value, list):
        for v in value:
            _walk(v, roots)


def resolve(value: Any, scope: dict[str, Any]) -> Any:
    """依 scope 解析 value。

    scope 結構：{'event': {...}, 'context': {...}, '<step_id>': {...}, ...}
    """
    if isinstance(value, str):
        pure = _PURE_REF_RE.match(value)
        if pure:
            return _lookup(pure.group(1), scope)
        # 內嵌字串：把每個 $xxx 替換為 str()
        def _sub(m: re.Match) -> str:
            v = _lookup(m.group(1), scope)
            return "" if v is None else str(v)

        return _REF_RE.sub(_sub, value)

    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value


def _lookup(path: str, scope: dict[str, Any]) -> Any:
    parts = path.split(".")
    cur: Any = scope
    for p in parts:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
    return cur
