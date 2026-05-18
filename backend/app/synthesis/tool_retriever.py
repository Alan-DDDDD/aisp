"""Tool Retriever — 在 tool registry 上做 embedding-based retrieval。

設計選擇（PLAN §22.4.2）：
- 用 km.store 的 embedding function（與 KB 同模型，省一份載入）
- In-memory dict 快取，因為 tool 數量小（builtin 2~10，generated 預期上限 50）
- 不走 ChromaDB：避開 collection persistence 對小資料的 overhead，且方便 reset

Index lifecycle：
- 第一次呼叫 retrieve()/build_index() 才 lazy build
- 註冊新工具後要手動 rebuild()（M6 註冊 generated tool 時會呼叫）
"""

from __future__ import annotations

import logging
import math

from app.km import store
from app.synthesis.schemas import ToolCandidate
from app.tools import registry as tool_registry
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity；不依賴 numpy，tools 數量小直接 Python 算。"""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _tool_class(tool_id: str) -> type[BaseTool]:
    return type(tool_registry.get(tool_id))


class ToolRetriever:
    """Singleton-like：在進程內共用一份索引。

    測試時可以直接 new 一個並注入 fake embeddings 繞過真實模型。

    Workspace scoping（M6，PLAN §22.5.8）：
    - 索引存 (embedding, workspace_id)，workspace_id=None 表 global
    - retrieve() 可傳 workspace_id 過濾；None = admin 視角
    """

    def __init__(self) -> None:
        # tool_id → (embedding, workspace_id)
        self._index: dict[str, tuple[list[float], str | None]] = {}
        self._embed_fn = None

    def _get_embed_fn(self):
        if self._embed_fn is None:
            self._embed_fn = store._get_embedding_fn()
        return self._embed_fn

    def _embed(self, texts: list[str]) -> list[list[float]]:
        fn = self._get_embed_fn()
        # ChromaDB embedding functions return list[list[float]] for batch input
        return [list(v) for v in fn(texts)]

    def is_built(self) -> bool:
        return bool(self._index)

    def build(self) -> None:
        """從 tool_registry 完整重建 index，連同 workspace_id 一起存。"""
        tool_ids = tool_registry.list_ids()
        if not tool_ids:
            log.info("ToolRetriever.build: registry empty")
            self._index = {}
            return

        texts = [_tool_class(tid).embedding_text() for tid in tool_ids]
        vectors = self._embed(texts)
        self._index = {
            tid: (vec, tool_registry.workspace_of(tid))
            for tid, vec in zip(tool_ids, vectors, strict=True)
        }
        log.info("ToolRetriever indexed %d tools", len(self._index))

    def add_tool(self, tool_id: str) -> None:
        """單獨補一個 tool 的 embedding（M6 註冊 generated tool 後呼叫）。"""
        text = _tool_class(tool_id).embedding_text()
        vec = self._embed([text])[0]
        self._index[tool_id] = (vec, tool_registry.workspace_of(tool_id))

    def remove_tool(self, tool_id: str) -> None:
        self._index.pop(tool_id, None)

    def reset(self) -> None:
        """測試用。"""
        self._index = {}

    def retrieve(
        self,
        step_description: str,
        top_k: int = 5,
        *,
        workspace_id: str | None = None,
    ) -> list[ToolCandidate]:
        if not self._index:
            self.build()
        if not self._index:
            return []

        query_vec = self._embed([step_description])[0]
        scored: list[tuple[str, float]] = []
        for tid, (vec, ws) in self._index.items():
            if not _visible_to(ws, workspace_id):
                continue
            scored.append((tid, _cosine(query_vec, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)

        candidates: list[ToolCandidate] = []
        for tid, sim in scored[:top_k]:
            cls = _tool_class(tid)
            candidates.append(
                ToolCandidate(
                    tool_id=tid,
                    similarity=sim,
                    description=cls.description,
                    when_to_use=cls.when_to_use,
                    when_not_to_use=cls.when_NOT_to_use,
                    side_effect=cls.side_effect.value,
                )
            )
        return candidates


def _visible_to(tool_ws: str | None, query_ws: str | None) -> bool:
    """workspace 可見性：global tool 對所有人可見；scoped tool 只對該 workspace 可見。

    query_ws=None 視為 admin/全域查詢，只看 global tool（避免跨 workspace 洩漏）。
    """
    if tool_ws is None:
        return True
    if query_ws is None:
        return False
    return tool_ws == query_ws


# Process-wide instance；測試可用 reset() / new instance 隔離。
_default = ToolRetriever()


def get_default() -> ToolRetriever:
    return _default
