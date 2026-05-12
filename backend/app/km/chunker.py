"""文件切塊。

策略：
- FAQ：一條 Q&A 一個 chunk，不切
- 其他：按字元數切，保留 overlap
- 中英混合：直接用 len()（字元數），不做 token-aware
"""

from __future__ import annotations

import re


def chunk_text(
    text: str,
    *,
    chunk_size: int = 500,
    overlap: int = 60,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    # 先依段落（兩個換行）分組，避免硬切句子
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buffer = ""

    for p in paragraphs:
        if not buffer:
            buffer = p
            continue
        if len(buffer) + len(p) + 1 <= chunk_size:
            buffer = f"{buffer}\n\n{p}"
        else:
            chunks.append(buffer)
            # 帶 overlap 開新 chunk
            tail = buffer[-overlap:] if overlap > 0 else ""
            buffer = f"{tail}\n\n{p}" if tail else p

    if buffer:
        chunks.append(buffer)

    # 對單段超長的 paragraph：暴力按字元切
    final: list[str] = []
    for c in chunks:
        if len(c) <= chunk_size * 1.5:
            final.append(c)
        else:
            i = 0
            while i < len(c):
                final.append(c[i : i + chunk_size])
                i += chunk_size - overlap
    return [c.strip() for c in final if c.strip()]


def chunk_faq_entry(question: str, answer: str) -> str:
    """FAQ 模式：Q&A 一條合成單一 chunk。"""
    return f"問：{question.strip()}\n\n答：{answer.strip()}"
