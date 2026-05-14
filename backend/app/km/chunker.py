"""文件切塊。

策略：
- FAQ：Q&A 合成單一 chunk，不切。
- 結構感知切塊（chunk_structured）：
  * Markdown：heading、表格、fenced code block
  * 法條：第N章 / 第N節 / 第N條（含「之一」修正版、阿拉伯或中文數字、行內標題）
    自動成為對應層級的 heading
  * 表格、程式碼為原子單位，不被切斷
  * 維持 heading 階層，產生 heading_path（breadcrumb），並 prepend 到 chunk 文字
    以強化 embedding 的語意脈絡
  * 段落超過 chunk_size 時的退回切分順序：
      1. 子條款邊界（第N項 / 第N款 / (一)(二) / ①②）
      2. 句子邊界（中文 。！？；／英文 .!?）
- 中英混合：直接用 len()（字元數），不做 token-aware。

設計：0 額外依賴，純 stdlib（re + dataclasses）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkResult:
    """一個 chunk 的內容與結構標記。"""

    text: str
    heading_path: list[str] = field(default_factory=list)
    has_table: bool = False
    has_code: bool = False

    @property
    def structural_metadata(self) -> dict[str, Any]:
        """轉成 Chroma 可吃的 metadata（純 str/bool）。"""
        return {
            "heading_path": " > ".join(self.heading_path),
            "has_table": self.has_table,
            "has_code": self.has_code,
        }


# ──────────────────────────────────────────────────────────────────────────
# Structural patterns
# ──────────────────────────────────────────────────────────────────────────

# Markdown
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^```")
_TABLE_LINE_RE = re.compile(r"^\s*\|.+\|\s*$")

# Sentence delimiters (中文 + 英文)
_SENT_SPLIT = re.compile(r"(?<=[。！？；])|(?<=[\.!?])\s+")

# Legal: 章 / 節 / 條
# 數字部分接受中文（一二…百千零〇）或阿拉伯數字；「條」可帶「之一」這類修正
_NUM = r"[一二三四五六七八九十百千零〇\d]+"
_LEGAL_CHAPTER_RE = re.compile(
    rf"^\s*(第\s*{_NUM}\s*章)(?:[：:　\s]+(.*?))?\s*$"
)
_LEGAL_SECTION_RE = re.compile(
    rf"^\s*(第\s*{_NUM}\s*節)(?:[：:　\s]+(.*?))?\s*$"
)
_LEGAL_ARTICLE_RE = re.compile(
    rf"^\s*(第\s*{_NUM}\s*條(?:之\s*{_NUM})?)(?:[：:　\s]+(.*?))?\s*$"
)

# 子條款（用於段落內切分）：第N項 / 第N款 / (一) (二) / ① ② …
_SUBCLAUSE_START_RE = re.compile(
    rf"^(?:第\s*{_NUM}\s*[項款]|[（(]\s*{_NUM}\s*[)）]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])"
)

# 法條層級（刻意取 10+，讓 markdown # ~ ###### 可以排在上面）
_LEGAL_CHAPTER_LEVEL = 10
_LEGAL_SECTION_LEVEL = 11
_LEGAL_ARTICLE_LEVEL = 12

# 行內標題與行內內文的閾值（超過或含句點就視為內文，分成 heading + paragraph）
_LEGAL_INLINE_TITLE_MAX = 30
_LEGAL_INLINE_SENTENCE_CHARS = "。；！？"


@dataclass
class _Block:
    kind: str  # heading | paragraph | table | code
    text: str
    level: int = 0  # heading only


# ──────────────────────────────────────────────────────────────────────────
# Block parsing
# ──────────────────────────────────────────────────────────────────────────


def _match_legal(line: str) -> tuple[re.Match[str], int] | None:
    """命中法條 heading 時回傳 (match, level)。"""
    for pattern, level in (
        (_LEGAL_CHAPTER_RE, _LEGAL_CHAPTER_LEVEL),
        (_LEGAL_SECTION_RE, _LEGAL_SECTION_LEVEL),
        (_LEGAL_ARTICLE_RE, _LEGAL_ARTICLE_LEVEL),
    ):
        m = pattern.match(line)
        if m:
            return m, level
    return None


def _is_structural_line(line: str) -> bool:
    """判斷某行是否屬於結構標記（heading / fence / table / 法條 heading）。"""
    s = line.strip()
    if not s:
        return False
    if _HEADING_RE.match(s):
        return True
    if _FENCE_RE.match(s):
        return True
    if _TABLE_LINE_RE.match(line):
        return True
    if _match_legal(s):
        return True
    return False


def _emit_legal_heading(
    blocks: list[_Block], marker: str, rest: str, level: int
) -> None:
    """處理法條 heading：依「行內是否帶內文」決定要不要拆成 heading + paragraph。"""
    rest = rest.strip()
    if rest and (
        len(rest) > _LEGAL_INLINE_TITLE_MAX
        or any(p in rest for p in _LEGAL_INLINE_SENTENCE_CHARS)
    ):
        blocks.append(_Block(kind="heading", text=marker, level=level))
        blocks.append(_Block(kind="paragraph", text=rest))
    else:
        full = f"{marker} {rest}".strip() if rest else marker
        blocks.append(_Block(kind="heading", text=full, level=level))


def _parse_blocks(text: str) -> list[_Block]:
    """把原文掃成有型別的區塊序列。"""
    lines = text.splitlines()
    blocks: list[_Block] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # markdown heading
        m = _HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            blocks.append(_Block(kind="heading", text=m.group(2).strip(), level=level))
            i += 1
            continue

        # 法條 heading：章 / 節 / 條
        legal = _match_legal(stripped)
        if legal:
            m, level = legal
            marker = m.group(1).strip()
            rest = (m.group(2) or "").strip()
            _emit_legal_heading(blocks, marker, rest, level)
            i += 1
            continue

        # fenced code block
        if _FENCE_RE.match(stripped):
            buf = [line]
            i += 1
            while i < n and not _FENCE_RE.match(lines[i].strip()):
                buf.append(lines[i])
                i += 1
            if i < n:
                buf.append(lines[i])  # closing fence
                i += 1
            blocks.append(_Block(kind="code", text="\n".join(buf)))
            continue

        # markdown table（連續 | ... | 行）
        if _TABLE_LINE_RE.match(line):
            buf = [line]
            i += 1
            while i < n and _TABLE_LINE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            if len(buf) >= 2:
                blocks.append(_Block(kind="table", text="\n".join(buf)))
                continue
            blocks.append(_Block(kind="paragraph", text="\n".join(buf)))
            continue

        # paragraph：收到空白行或下個結構標記為止
        buf = [line]
        i += 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip():
                break
            if _is_structural_line(nxt):
                break
            buf.append(nxt)
            i += 1
        para = "\n".join(buf).strip()
        if para:
            blocks.append(_Block(kind="paragraph", text=para))

    return blocks


# ──────────────────────────────────────────────────────────────────────────
# Oversized paragraph splitting
# ──────────────────────────────────────────────────────────────────────────


def _split_sentences(text: str) -> list[str]:
    """以中英文標點為邊界切句。"""
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _split_subclauses(text: str) -> list[str]:
    """依「行首子條款標記」切分；找不到任何標記則回傳 [text]。"""
    lines = text.split("\n")
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _SUBCLAUSE_START_RE.match(line.strip()):
            if current:
                groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)
    parts = ["\n".join(g).strip() for g in groups if "".join(g).strip()]
    return parts if len(parts) >= 2 else [text.strip()]


def _pack_units(
    units: list[str],
    *,
    chunk_size: int,
    joiner: str,
    overlap: int,
) -> list[str]:
    """把字串單位 pack 成 chunk_size 大小群組；overlap > 0 時保留上一塊最末單位。"""
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for u in units:
        u = u.strip()
        if not u:
            continue
        sep_len = len(joiner) if cur else 0
        if cur and cur_len + sep_len + len(u) > chunk_size:
            out.append(joiner.join(cur).strip())
            cur = [cur[-1]] if overlap > 0 else []
            cur_len = sum(len(x) for x in cur) + (
                len(joiner) * max(0, len(cur) - 1)
            )
            sep_len = len(joiner) if cur else 0
        cur.append(u)
        cur_len += sep_len + len(u)
    if cur:
        out.append(joiner.join(cur).strip())
    return out


def _split_oversized_paragraph(
    para: str, *, chunk_size: int, overlap: int
) -> list[str]:
    """把超量段落切成多塊。優先以子條款邊界切，否則退到句界。"""
    subs = _split_subclauses(para)
    if len(subs) >= 2:
        return _pack_units(subs, chunk_size=chunk_size, joiner="\n", overlap=0)
    sents = _split_sentences(para)
    if len(sents) >= 2:
        return _pack_units(sents, chunk_size=chunk_size, joiner="", overlap=overlap)
    return [para.strip()]


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


def chunk_structured(
    text: str,
    *,
    chunk_size: int = 500,
    overlap: int = 60,
) -> list[ChunkResult]:
    """結構感知切塊。

    回傳 ChunkResult 列表，每個 chunk 帶 heading_path 與表格/程式碼旗標。
    表格與程式碼絕不被切斷（即使單塊超過 chunk_size）。
    法條 (章/節/條) 自動納入 heading 階層；過長條文以子條款邊界優先切。
    """
    text = (text or "").strip()
    if not text:
        return []

    blocks = _parse_blocks(text)
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    chunks: list[ChunkResult] = []

    buffer: list[str] = []
    buffer_len = 0

    def current_path() -> list[str]:
        return [t for _, t in heading_stack]

    def emit_buffer() -> None:
        nonlocal buffer, buffer_len
        if not buffer:
            return
        body = "\n\n".join(buffer).strip()
        if body:
            chunks.append(ChunkResult(text=body, heading_path=current_path()))
        buffer = []
        buffer_len = 0

    def append_paragraph(para: str) -> None:
        nonlocal buffer, buffer_len
        if not para:
            return
        # 單段超量：先 flush buffer，再依「子條款 → 句界」順序切
        if len(para) > chunk_size:
            emit_buffer()
            for s in _split_oversized_paragraph(
                para, chunk_size=chunk_size, overlap=overlap
            ):
                chunks.append(ChunkResult(text=s, heading_path=current_path()))
            return
        # 一般段落：超量就先 flush 再放入
        if buffer and buffer_len + len(para) + 2 > chunk_size:
            emit_buffer()
        buffer.append(para)
        buffer_len += len(para) + (2 if len(buffer) > 1 else 0)

    for block in blocks:
        if block.kind == "heading":
            emit_buffer()
            heading_stack = [
                (lvl, t) for (lvl, t) in heading_stack if lvl < block.level
            ]
            heading_stack.append((block.level, block.text))
            continue

        if block.kind == "table":
            emit_buffer()
            chunks.append(
                ChunkResult(
                    text=block.text.strip(),
                    heading_path=current_path(),
                    has_table=True,
                )
            )
            continue

        if block.kind == "code":
            emit_buffer()
            chunks.append(
                ChunkResult(
                    text=block.text.strip(),
                    heading_path=current_path(),
                    has_code=True,
                )
            )
            continue

        # paragraph
        append_paragraph(block.text.strip())

    emit_buffer()

    return [_with_breadcrumb(c) for c in chunks]


def _with_breadcrumb(c: ChunkResult) -> ChunkResult:
    """把 heading 路徑當 prefix 加進 chunk text，提升 embedding 的語意脈絡。"""
    if not c.heading_path:
        return c
    crumb = " > ".join(c.heading_path)
    return ChunkResult(
        text=f"[{crumb}]\n{c.text}",
        heading_path=c.heading_path,
        has_table=c.has_table,
        has_code=c.has_code,
    )


def chunk_text(
    text: str,
    *,
    chunk_size: int = 500,
    overlap: int = 60,
) -> list[str]:
    """向後相容：回傳純文字 list（不含結構 metadata）。"""
    return [
        c.text
        for c in chunk_structured(text, chunk_size=chunk_size, overlap=overlap)
    ]


def chunk_faq_entry(question: str, answer: str) -> str:
    """FAQ 模式：Q&A 一條合成單一 chunk。"""
    return f"問：{question.strip()}\n\n答：{answer.strip()}"
