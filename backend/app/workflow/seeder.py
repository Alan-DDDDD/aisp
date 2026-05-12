"""啟動時 seed workspaces 的設定與知識庫。

每個 workspace 在 repo 中是一個資料夾：
  workspaces/<id>/
    workspace.json       — Workspace 設定
    knowledge/faq.json   — FAQ 種子資料

設計：
- workspace.json 不存在的資料夾忽略。
- Workspace 列已存在則更新 display_name / color / icon / description。
- FAQ 已 seed 過（doc_count > 0）則略過（避免每次重啟重新生成 embedding）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import Document, KnowledgeBase, Workspace
from app.km.ingest import ingest_faq_json

log = logging.getLogger(__name__)


async def seed_on_boot() -> None:
    if not settings.seed_on_boot:
        log.info("SEED_ON_BOOT=false → skipping")
        return

    base = Path(settings.workspaces_dir).resolve()
    if not base.exists():
        log.warning("workspaces dir not found: %s", base)
        return

    seeded = 0
    for ws_dir in sorted(base.iterdir()):
        if not ws_dir.is_dir():
            continue
        config_path = ws_dir / "workspace.json"
        if not config_path.exists():
            log.debug("skip %s: no workspace.json", ws_dir.name)
            continue
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.exception("讀取 %s 失敗：%s", config_path, e)
            continue
        await _seed_workspace(ws_dir, config)
        seeded += 1
    log.info("seed_on_boot 完成，共處理 %d 個 workspace", seeded)


async def _seed_workspace(ws_dir: Path, config: dict) -> None:
    workspace_id = config.get("id") or ws_dir.name

    async with SessionLocal() as session:
        ws = await session.get(Workspace, workspace_id)
        if ws is None:
            ws = Workspace(
                id=workspace_id,
                display_name=config.get("display_name", workspace_id.title()),
                description=config.get("description", ""),
                default_kb=config.get("default_kb", "faq"),
                color=config.get("color", "#5b6cff"),
                icon=config.get("icon", ""),
                status="active",
            )
            session.add(ws)
        else:
            ws.display_name = config.get("display_name", ws.display_name)
            ws.description = config.get("description", ws.description)
            ws.default_kb = config.get("default_kb", ws.default_kb)
            ws.color = config.get("color", ws.color)
            ws.icon = config.get("icon", ws.icon)
        await session.commit()

    faq_path = ws_dir / "knowledge" / "faq.json"
    if faq_path.exists():
        await _seed_faq(workspace_id, config.get("default_kb", "faq"), faq_path)


async def _seed_faq(workspace_id: str, kb_name: str, faq_path: Path) -> None:
    async with SessionLocal() as session:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.workspace_id == workspace_id,
            KnowledgeBase.name == kb_name,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            count_stmt = select(func.count(Document.id)).where(Document.kb_id == existing.id)
            doc_count = int((await session.execute(count_stmt)).scalar() or 0)
            if doc_count > 0:
                log.info(
                    "KB %s/%s 已存在（%d docs），略過 seed",
                    workspace_id,
                    kb_name,
                    doc_count,
                )
                return

        try:
            items = json.loads(faq_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.exception("讀取 %s 失敗：%s", faq_path, e)
            return

        kb, count = await ingest_faq_json(
            session,
            workspace_id=workspace_id,
            kb_name=kb_name,
            items=items,
        )
        await session.commit()
        log.info("Seeded %s/%s with %d documents", workspace_id, kb_name, count)
