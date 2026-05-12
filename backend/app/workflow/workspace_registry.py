"""Workspace 設定的 in-memory registry。

啟動時把每個 workspaces/<id>/workspace.json 載入記憶體，供 agent 在 runtime
不打 DB 即可查 `allowed_categories`、`display_name` 等設定。

與 seeder 的分工：
- seeder 把 workspace 寫進 SQLite，供 list / detail API 用。
- 本 registry 留純 config，供 agent runtime 用（避免每次 ctx 都 SELECT workspaces）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

_REGISTRY: dict[str, dict] = {}


def load_all() -> dict[str, dict]:
    base = Path(settings.workspaces_dir).resolve()
    if not base.exists():
        log.warning("workspaces dir not found: %s", base)
        return {}

    _REGISTRY.clear()
    for ws_dir in sorted(base.iterdir()):
        if not ws_dir.is_dir():
            continue
        config_path = ws_dir / "workspace.json"
        if not config_path.exists():
            continue
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.exception("讀取 %s 失敗：%s", config_path, e)
            continue
        ws_id = config.get("id") or ws_dir.name
        _REGISTRY[ws_id] = config
    log.info("Loaded %d workspace configs: %s", len(_REGISTRY), list(_REGISTRY.keys()))
    return _REGISTRY


def get(workspace_id: str) -> dict | None:
    return _REGISTRY.get(workspace_id)


def get_allowed_categories(workspace_id: str) -> set[str] | None:
    """回傳 workspace 設定的 allowed_categories（set）。未設定或不存在則回 None
    （= 不施加 scope 限制，向後相容）。"""
    config = _REGISTRY.get(workspace_id)
    if not config:
        return None
    raw = config.get("allowed_categories")
    if not raw:
        return None
    return {str(c).lower() for c in raw}


def display_name(workspace_id: str) -> str:
    config = _REGISTRY.get(workspace_id)
    return (config or {}).get("display_name") or workspace_id
