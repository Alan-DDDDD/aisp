"""PDF 文字抽取。

設計：
- 同步函式（pypdf 是 sync）；由 caller 自行決定要不要丟到 threadpool。
- 一頁一段，頁與頁之間用兩個換行（讓 chunker 把頁當段落處理）。
- 加密 / 純圖片 / 解析失敗會回傳清楚的錯誤類別，讓 API 層映射成 400。
"""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)


class PdfExtractError(Exception):
    """PDF 抽取失敗的統一例外，message 對人類可讀。"""


def extract_text_from_pdf(data: bytes) -> str:
    """從 PDF bytes 抽出純文字。

    Raises:
        PdfExtractError: 加密、損毀、無可抽文字（純圖片掃描）等。
    """
    if not data:
        raise PdfExtractError("檔案內容為空")

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as e:
        raise PdfExtractError(f"PDF 解析失敗：{e}") from e
    except Exception as e:  # noqa: BLE001
        raise PdfExtractError(f"無法讀取 PDF：{e}") from e

    if reader.is_encrypted:
        # pypdf 對「空密碼加密」會自動解；其他情況 raise
        try:
            ok = reader.decrypt("")
        except Exception:  # noqa: BLE001
            ok = 0
        if not ok:
            raise PdfExtractError("此 PDF 有密碼保護，請先解密後再上傳")

    pages_text: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001
            log.warning("PDF page %d extract failed: %s", i, e)
            txt = ""
        txt = txt.strip()
        if txt:
            pages_text.append(txt)

    if not pages_text:
        raise PdfExtractError(
            "PDF 沒有可抽取的文字（可能是純圖片掃描檔；需要 OCR 才能處理）"
        )

    return "\n\n".join(pages_text)
