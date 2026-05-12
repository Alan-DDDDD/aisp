"""讀取與快取 workspaces/<id>/workflow.yaml。

啟動時批次預載；之後 cache 在記憶體（process-wide）。
Phase 6+ admin 編輯後可呼叫 reload() 重新讀取。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.config import settings
from app.workflow.spec import WorkflowDef

log = logging.getLogger(__name__)


_cache: dict[str, WorkflowDef] = {}


def workflow_path(workspace_id: str) -> Path:
    return Path(settings.workspaces_dir).resolve() / workspace_id / "workflow.yaml"


def load(workspace_id: str) -> WorkflowDef:
    """強制重新讀取單一 workspace 的 workflow.yaml；回傳並更新快取。"""
    path = workflow_path(workspace_id)
    if not path.exists():
        raise FileNotFoundError(f"workflow.yaml not found for workspace {workspace_id}: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"workflow.yaml must be a mapping, got {type(raw).__name__}")
    wf = WorkflowDef.model_validate(raw)
    _cache[workspace_id] = wf
    return wf


def get(workspace_id: str) -> WorkflowDef:
    """取快取；沒有的話現場讀。"""
    if workspace_id in _cache:
        return _cache[workspace_id]
    return load(workspace_id)


def preload_all() -> dict[str, WorkflowDef]:
    """掃 workspaces dir、把所有 workflow.yaml 載進快取。回傳成功載入的字典。"""
    base = Path(settings.workspaces_dir).resolve()
    loaded: dict[str, WorkflowDef] = {}
    if not base.exists():
        log.warning("workspaces dir not found: %s", base)
        return loaded
    for ws_dir in sorted(base.iterdir()):
        if not ws_dir.is_dir():
            continue
        wf_path = ws_dir / "workflow.yaml"
        if not wf_path.exists():
            continue
        try:
            wf = load(ws_dir.name)
            loaded[ws_dir.name] = wf
            log.info("Loaded workflow: %s/%s (%d steps)", ws_dir.name, wf.id, len(wf.steps))
        except Exception as e:  # noqa: BLE001
            log.exception("Failed to load workflow for %s: %s", ws_dir.name, e)
    return loaded


def clear_cache() -> None:
    _cache.clear()


def cached_workspace_ids() -> list[str]:
    return list(_cache.keys())
