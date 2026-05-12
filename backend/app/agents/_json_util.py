"""LLM JSON 輸出容錯解析 — 給所有 JSON-mode agent 共用。"""

from __future__ import annotations

import json
import re

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_loose(text: str | None) -> dict | None:
    """容錯解析 LLM 輸出的 JSON。

    嘗試順序：
    1. 直接 json.loads
    2. 剝掉 ```json ... ``` 圍欄後重試
    3. 用 regex 抓出第一個 {...} 區塊後重試
    """
    text = (text or "").strip()
    if not text:
        return None

    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    stripped = _CODE_FENCE_RE.sub("", text).strip()
    if stripped and stripped != text:
        try:
            result = json.loads(stripped)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            pass

    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            result = json.loads(match.group(0))
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            pass

    return None
