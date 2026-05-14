"""Cross-encoder reranker（精排）。

設計：
- 走 sentence-transformers 的 CrossEncoder。
- 由 settings.rerank_model 控制：空字串 = 不啟用，呼叫 rerank() 會直接回原 hits。
- 模型 lazy load 並 cache，避免每次查詢重新初始化。
- HF Spaces 免費版資源緊，預設關閉；本機跑 eval 或部署到較好機器再開。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import settings
from app.schemas.knowledge import KnowledgeSearchHit

log = logging.getLogger(__name__)


_lock = threading.Lock()
_cached_model: Any | None = None
_cached_model_name: str = ""


def is_enabled() -> bool:
    return bool((settings.rerank_model or "").strip())


def _get_model() -> Any | None:
    global _cached_model, _cached_model_name
    name = (settings.rerank_model or "").strip()
    if not name:
        return None
    if _cached_model is not None and _cached_model_name == name:
        return _cached_model
    with _lock:
        if _cached_model is not None and _cached_model_name == name:
            return _cached_model
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            log.warning("CrossEncoder import failed (%s); reranker disabled", e)
            return None
        log.info("Loading reranker model: %s", name)
        _cached_model = CrossEncoder(name)
        _cached_model_name = name
    return _cached_model


def rerank(
    query: str,
    hits: list[KnowledgeSearchHit],
    *,
    top_n: int | None = None,
) -> list[KnowledgeSearchHit]:
    """根據 cross-encoder 分數重排 hits；reranker 未啟用時回原序。"""
    if not hits or not (query or "").strip():
        return hits
    model = _get_model()
    if model is None:
        return hits

    pairs = [(query, h.text) for h in hits]
    try:
        scores = model.predict(pairs)
    except Exception as e:  # noqa: BLE001
        log.warning("Reranker predict failed (%s); falling back to original order", e)
        return hits

    # CrossEncoder 預測分數越高越相關；min-max 正規化便於與 cosine 同尺度顯示
    raw = [float(s) for s in scores]
    if raw:
        lo, hi = min(raw), max(raw)
        span = hi - lo if hi > lo else 1.0
        normed = [(s - lo) / span for s in raw]
    else:
        normed = raw

    paired = list(zip(hits, raw, normed, strict=False))
    paired.sort(key=lambda x: x[1], reverse=True)

    out: list[KnowledgeSearchHit] = []
    for h, raw_s, norm_s in paired:
        new_meta = dict(h.metadata or {})
        new_meta["rerank_score"] = round(raw_s, 4)
        out.append(
            KnowledgeSearchHit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                title=h.title,
                text=h.text,
                score=round(norm_s, 4),
                metadata=new_meta,
            )
        )
    n = top_n if top_n is not None else settings.rerank_top_n
    return out[:n]


def reset() -> None:
    """測試用：清模型 cache。"""
    global _cached_model, _cached_model_name
    with _lock:
        _cached_model = None
        _cached_model_name = ""
