"""Retrieval 評估 harness。

度量：recall@k、precision@k、MRR、hit_rate（top_k 內至少有一筆命中）。

Golden set 結構：
    workspace_id: cs
    kb_name: faq
    queries:
      - q: "70 歲申請車貸"
        expected_titles: ["車貸高齡客戶處理"]   # 子字串比對
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.km import retriever

# ──────────────────────────────────────────────────────────────────────────
# Metric helpers
# ──────────────────────────────────────────────────────────────────────────


def _hit_at(hits: list[Any], expected_titles: list[str]) -> list[bool]:
    """逐位置標出 hit.title 是否命中任何期望 title 子字串。"""
    out = []
    for h in hits:
        title = getattr(h, "title", "") or ""
        out.append(any(exp and exp in title for exp in expected_titles))
    return out


def recall_at_k(hits: list[Any], expected_titles: list[str], k: int) -> float:
    """前 k 筆中命中的「期望文件」覆蓋率。"""
    if not expected_titles:
        return 0.0
    found: set[str] = set()
    for h in hits[:k]:
        title = getattr(h, "title", "") or ""
        for exp in expected_titles:
            if exp and exp in title:
                found.add(exp)
    return len(found) / len(expected_titles)


def precision_at_k(hits: list[Any], expected_titles: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    flags = _hit_at(hits[:k], expected_titles)
    return sum(flags) / k


def hit_rate_at_k(hits: list[Any], expected_titles: list[str], k: int) -> float:
    return 1.0 if any(_hit_at(hits[:k], expected_titles)) else 0.0


def mrr(hits: list[Any], expected_titles: list[str]) -> float:
    """Mean Reciprocal Rank — 第一筆命中的位置倒數，無命中為 0。"""
    flags = _hit_at(hits, expected_titles)
    for i, f in enumerate(flags, start=1):
        if f:
            return 1.0 / i
    return 0.0


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class QueryResult:
    query: str
    expected_titles: list[str]
    hits: list[Any]
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class EvalReport:
    workspace_id: str
    kb_name: str
    mode: str
    top_k: int
    per_query: list[QueryResult] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)


async def evaluate(
    session: AsyncSession,
    *,
    workspace_id: str,
    kb_name: str,
    queries: list[dict],
    top_k: int = 5,
    mode: str | None = None,
) -> EvalReport:
    """跑一份 golden set，回傳逐題與彙總指標。

    queries 每筆需要：{q: str, expected_titles: list[str]}。
    """
    report = EvalReport(
        workspace_id=workspace_id,
        kb_name=kb_name,
        mode=mode or "default",
        top_k=top_k,
    )
    if not queries:
        return report

    sums = {"recall": 0.0, "precision": 0.0, "hit_rate": 0.0, "mrr": 0.0}

    for q_item in queries:
        q = q_item["q"]
        exp = q_item.get("expected_titles") or []
        hits = await retriever.search(
            session,
            workspace_id=workspace_id,
            kb_name=kb_name,
            query=q,
            top_k=top_k,
            mode=mode,
        )
        m = {
            f"recall@{top_k}": recall_at_k(hits, exp, top_k),
            f"precision@{top_k}": precision_at_k(hits, exp, top_k),
            f"hit_rate@{top_k}": hit_rate_at_k(hits, exp, top_k),
            "mrr": mrr(hits, exp),
        }
        sums["recall"] += m[f"recall@{top_k}"]
        sums["precision"] += m[f"precision@{top_k}"]
        sums["hit_rate"] += m[f"hit_rate@{top_k}"]
        sums["mrr"] += m["mrr"]
        report.per_query.append(
            QueryResult(query=q, expected_titles=exp, hits=hits, metrics=m)
        )

    n = len(queries)
    report.aggregate = {
        f"recall@{top_k}": round(sums["recall"] / n, 4),
        f"precision@{top_k}": round(sums["precision"] / n, 4),
        f"hit_rate@{top_k}": round(sums["hit_rate"] / n, 4),
        "mrr": round(sums["mrr"] / n, 4),
    }
    return report
