"""ChromaDB 封裝。

Phase 3 用 Chroma 內建 DefaultEmbeddingFunction（ONNX all-MiniLM-L6-v2，~80MB 一次下載）。
透過 settings.embedding_model 可以未來替換成多語言模型。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from app.config import settings

log = logging.getLogger(__name__)


_lock = threading.Lock()
_client: ClientAPI | None = None
_embedding_fn = None


def _get_embedding_fn():
    """共用一份 embedding function，避免重複初始化 ONNX runtime。"""
    global _embedding_fn
    if _embedding_fn is None:
        with _lock:
            if _embedding_fn is None:
                log.info("Initializing Chroma DefaultEmbeddingFunction (ONNX MiniLM-L6-v2)")
                _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    return _embedding_fn


def get_client() -> ClientAPI:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                persist_dir = Path(settings.chroma_persist_dir).resolve()
                persist_dir.mkdir(parents=True, exist_ok=True)
                log.info("Initializing Chroma PersistentClient at %s", persist_dir)
                _client = chromadb.PersistentClient(path=str(persist_dir))
    return _client


def get_or_create_collection(collection_name: str) -> Collection:
    client = get_client()
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=_get_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )


def delete_collection(collection_name: str) -> None:
    client = get_client()
    try:
        client.delete_collection(collection_name)
    except (ValueError, Exception) as e:  # noqa: BLE001 — Chroma 不同版本錯誤類型不一
        log.warning("delete_collection %s: %s", collection_name, e)


def reset_client() -> None:
    """測試用：重設 client / embedding 快取。"""
    global _client, _embedding_fn
    with _lock:
        _client = None
        _embedding_fn = None
