"""Registry Loader — 把 approved generated tools 從 disk + DB 載入記憶體 registry。

責任（PLAN §22.5.8）：
1. **寫入**：approve 時把 code 寫到 `generated_tools_dir/<tool_id>.py`，再 import 出
   BaseTool subclass，註冊進 tool_registry（含 workspace_id），更新 retriever
2. **讀取**：app 啟動時掃 `generated_tools` 表，逐筆載回 process

設計要點：
- 載入用 importlib + 手動把檔案放上 sys.path 而非 install 套件
- 每個 tool 各自一個 module（`generated_tool_<id>` 命名空間，避免衝突）
- 寫檔前再跑一次 static_check（縱深防禦：DB 內容若被竄改，這層擋住）
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import GeneratedTool
from app.synthesis import static_check
from app.synthesis.tool_retriever import ToolRetriever, get_default
from app.tools import registry as tool_registry
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


# ── 路徑 ─────────────────────────────────────────────────────────────


def _tools_dir() -> Path:
    p = Path(settings.generated_tools_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _module_name_for(tool_id: str) -> str:
    # 防止跟既有 module 名衝突
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in tool_id)
    return f"_generated_tool_{safe}"


def _source_path_for(tool_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in tool_id)
    return _tools_dir() / f"{safe}.py"


# ── 寫入 + 動態 import ───────────────────────────────────────────────


def write_source(tool_id: str, code: str) -> Path:
    """把 code 寫到 generated_tools_dir，回傳寫入路徑。"""
    path = _source_path_for(tool_id)
    path.write_text(code, encoding="utf-8")
    log.info("Wrote generated tool source: %s", path)
    return path


def _load_module_from_path(module_name: str, path: Path) -> Any:
    """從檔案 path 載入一個 module，註冊到 sys.modules。"""
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"無法為 {path} 建 module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _find_basetool_subclass(module) -> type[BaseTool]:
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseTool)
            and obj is not BaseTool
            and getattr(obj, "id", None)
        ):
            return obj
    raise RuntimeError(f"module {module.__name__} 內沒有 BaseTool subclass")


def install_from_source(
    tool_id: str,
    code: str,
    *,
    workspace_id: str | None,
    retriever: ToolRetriever | None = None,
    skip_static_check: bool = False,
) -> Path:
    """**完整流程**：寫檔 → static check → import → register → reindex。

    Raises RuntimeError 在任一階段失敗（呼叫方應 rollback DB transaction）。
    """
    if not skip_static_check:
        result = static_check.check(code)
        if not result.ok:
            raise RuntimeError(
                f"install_from_source: static check 失敗 - {result.summary}"
            )

    path = write_source(tool_id, code)
    module_name = _module_name_for(tool_id)

    # 之前若已 import 過（reload 情境），先從 sys.modules 移掉
    sys.modules.pop(module_name, None)

    try:
        module = _load_module_from_path(module_name, path)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"import {path} 失敗：{e}") from e

    cls = _find_basetool_subclass(module)
    if cls.id != tool_id:
        log.warning(
            "Generated tool 內 id=%r 與 DB tool_id=%r 不符；以 DB 為準",
            cls.id,
            tool_id,
        )
        cls.id = tool_id  # 強制對齊

    # 若已 register 過（覆蓋 / reload），先 unregister
    if tool_id in tool_registry.list_ids():
        tool_registry.unregister(tool_id)
        (retriever or get_default()).remove_tool(tool_id)

    instance = cls()
    instance.source_path = str(path)
    tool_registry.register(instance, workspace_id=workspace_id)
    (retriever or get_default()).add_tool(tool_id)
    log.info("Generated tool registered: %s (workspace=%s)", tool_id, workspace_id)
    return path


# ── 啟動時批次載入 ──────────────────────────────────────────────────


async def load_all_active(
    session: AsyncSession,
    *,
    retriever: ToolRetriever | None = None,
) -> int:
    """從 DB 撈所有 status=active 的 generated tool，依次 import + register。

    回傳成功載入的工具數。檔案 / static check 失敗的個別工具會被跳過並 log，
    不影響其他工具載入。
    """
    stmt = select(GeneratedTool).where(GeneratedTool.status == "active")
    rows = (await session.execute(stmt)).scalars().all()

    ok = 0
    for row in rows:
        try:
            path = Path(row.source_path)
            if not path.exists():
                log.warning(
                    "generated tool %s 來源檔不存在：%s — 跳過", row.id, path
                )
                continue
            code = path.read_text(encoding="utf-8")
            # 啟動載入時 trust DB 內容（之前 approve 過已檢過）；但仍跑一次 static
            # check 當 defense-in-depth
            install_from_source(
                row.id,
                code,
                workspace_id=row.workspace_id,
                retriever=retriever,
            )
            ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("載入 generated tool %s 失敗：%s", row.id, e)
    log.info("load_all_active: %d/%d generated tools loaded", ok, len(rows))
    return ok
