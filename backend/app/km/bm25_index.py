"""每個 Chroma collection 配一份 BM25 in-memory 索引。

設計：
- 索引內容直接從 Chroma collection.get() 拉，跟 dense embedding 同步源。
- Lazy build：第一次查詢時建索引，之後同個 collection 重用。
- 寫入 ingest 完之後呼叫 invalidate()；下一次查詢會重建。
- 中文以 jieba 分詞、英數以 regex 抽 token、全轉小寫。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import jieba
from rank_bm25 import BM25Okapi

from app.km import store

log = logging.getLogger(__name__)

# 抑制 jieba 啟動時 stderr 的 dict-loading log
jieba.setLogLevel(logging.WARNING)


_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_ALNUM_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """混中英 tokenize：中文走 jieba 精確模式、英數抽 alnum、全轉 lowercase。"""
    if not text:
        return []
    text = text.lower()
    out: list[str] = []
    for part in re.split(r"\s+", text):
        if not part:
            continue
        if _CJK_RE.search(part):
            out.extend(t for t in jieba.lcut(part, cut_all=False) if t.strip())
        else:
            out.extend(_ALNUM_RE.findall(part))
    # 過濾單字元、空字串
    return [t for t in out if t and t.strip()]


@dataclass
class _Index:
    bm25: BM25Okapi
    ids: list[str]
    documents: list[str]
    metadatas: list[dict]


_lock = threading.Lock()
_cache: dict[str, _Index] = {}


def _build(collection_name: str) -> _Index | None:
    collection = store.get_or_create_collection(collection_name)
    try:
        data = collection.get(include=["documents", "metadatas"])
    except Exception as e:  # noqa: BLE001
        log.warning("BM25 build: collection.get failed (%s): %s", collection_name, e)
        return None

    ids = list(data.get("ids") or [])
    docs = list(data.get("documents") or [])
    metas = list(data.get("metadatas") or [])
    # Chroma 0.5 在 get() 也可能不回 ids（依版本）；補齊到等長
    if len(ids) != len(docs):
        ids = [f"_{i}" for i in range(len(docs))]
    if len(metas) != len(docs):
        metas = [{} for _ in docs]

    if not docs:
        return None

    tokens = [tokenize(d) for d in docs]
    bm25 = BM25Okapi(tokens)
    log.info(
        "BM25 index built for %s: %d docs, avg %d tokens",
        collection_name,
        len(docs),
        sum(len(t) for t in tokens) // max(1, len(tokens)),
    )
    return _Index(bm25=bm25, ids=ids, documents=docs, metadatas=metas)


def get_index(collection_name: str) -> _Index | None:
    with _lock:
        idx = _cache.get(collection_name)
    if idx is not None:
        return idx
    built = _build(collection_name)
    if built is None:
        return None
    with _lock:
        _cache[collection_name] = built
    return built


def invalidate(collection_name: str) -> None:
    """ingest 寫入後呼叫，下一次查詢重建。"""
    with _lock:
        _cache.pop(collection_name, None)


def reset() -> None:
    """測試用：清整個 cache。"""
    with _lock:
        _cache.clear()


def search(
    collection_name: str,
    query: str,
    *,
    top_k: int,
    workspace_id: str | None = None,
) -> list[tuple[str, str, dict, float]]:
    """回傳 [(chunk_id, document, metadata, bm25_score), ...]，已依分數降序、施加 workspace 過濾。"""
    idx = get_index(collection_name)
    if idx is None or not query.strip():
        return []
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    scores = idx.bm25.get_scores(q_tokens)
    # 取分數 > 0 的，依降序排
    ranked = sorted(
        ((i, float(s)) for i, s in enumerate(scores) if s > 0),
        key=lambda t: t[1],
        reverse=True,
    )
    out: list[tuple[str, str, dict, float]] = []
    for i, score in ranked:
        meta = idx.metadatas[i] or {}
        if workspace_id is not None and meta.get("workspace_id") != workspace_id:
            continue
        out.append((idx.ids[i], idx.documents[i], meta, score))
        if len(out) >= top_k:
            break
    return out
