"""結構感知切塊測試：heading 階層、表格、程式碼、句子退回切分。"""

from __future__ import annotations

from app.km.chunker import (
    ChunkResult,
    chunk_faq_entry,
    chunk_structured,
    chunk_text,
)


def test_empty_input_returns_no_chunks():
    assert chunk_structured("") == []
    assert chunk_structured("   \n   ") == []


def test_plain_short_text_single_chunk():
    chunks = chunk_structured("這是一段短文字。")
    assert len(chunks) == 1
    assert chunks[0].heading_path == []
    assert chunks[0].has_table is False
    assert chunks[0].has_code is False


def test_markdown_heading_hierarchy_breadcrumb():
    text = """
# 員工手冊

## 休假
特休天數依到職年資而定。

## 健保
公司全額補助員工保費。

### 眷屬
眷屬須自費。
""".strip()
    chunks = chunk_structured(text)
    leave = next(c for c in chunks if "特休" in c.text)
    assert leave.heading_path == ["員工手冊", "休假"]
    assert "[員工手冊 > 休假]" in leave.text

    insurance = next(c for c in chunks if "保費" in c.text)
    assert insurance.heading_path == ["員工手冊", "健保"]

    dependents = next(c for c in chunks if "眷屬" in c.text and "自費" in c.text)
    assert dependents.heading_path == ["員工手冊", "健保", "眷屬"]


def test_heading_pops_same_level():
    """切到同級 heading 時，前一個同級應該 pop 掉而不是堆疊。"""
    text = """
## A
foo
## B
bar
""".strip()
    chunks = chunk_structured(text)
    a = next(c for c in chunks if "foo" in c.text)
    b = next(c for c in chunks if "bar" in c.text)
    assert a.heading_path == ["A"]
    assert b.heading_path == ["B"]


def test_markdown_table_is_atomic_even_when_oversized():
    rows = "\n".join(f"| col1 | col2 | row {i} |" for i in range(30))
    text = f"# Table Doc\n\n| col1 | col2 | col3 |\n| --- | --- | --- |\n{rows}"
    chunks = chunk_structured(text, chunk_size=100)
    tables = [c for c in chunks if c.has_table]
    assert len(tables) == 1, "整張表應該保持為單一 chunk"
    assert "row 0" in tables[0].text
    assert "row 29" in tables[0].text
    assert tables[0].heading_path == ["Table Doc"]


def test_fenced_code_block_is_atomic():
    body = "\n".join([f"    print({i})" for i in range(30)])
    text = f"# Snippet\n\n```python\ndef demo():\n{body}\n    return None\n```\n"
    chunks = chunk_structured(text, chunk_size=80)
    codes = [c for c in chunks if c.has_code]
    assert len(codes) == 1
    assert "def demo" in codes[0].text
    assert "return None" in codes[0].text


def test_long_paragraph_splits_on_sentence_boundary():
    para = "這是第一句。" * 80
    chunks = chunk_structured(para, chunk_size=100)
    assert len(chunks) > 1
    # 每塊應該以「。」結尾（句界），不會把句子腰斬
    for c in chunks:
        assert c.text.endswith("。"), f"chunk 沒有切在句界: {c.text[-20:]!r}"


def test_table_does_not_pollute_subsequent_paragraph_heading_path():
    text = """
# 文件

## A 區
段落 A。

| col | col |
| --- | --- |
| x | y |

## B 區
段落 B。
""".strip()
    chunks = chunk_structured(text)
    table = next(c for c in chunks if c.has_table)
    assert table.heading_path == ["文件", "A 區"]
    b_para = next(c for c in chunks if "段落 B" in c.text)
    assert b_para.heading_path == ["文件", "B 區"]


def test_structural_metadata_is_chroma_safe():
    """metadata 必須是 str/bool，否則 Chroma 會 reject。"""
    chunks = chunk_structured("# Title\n\n內容")
    meta = chunks[0].structural_metadata
    assert isinstance(meta["heading_path"], str)
    assert isinstance(meta["has_table"], bool)
    assert isinstance(meta["has_code"], bool)


def test_backward_compat_chunk_text_returns_strings():
    out = chunk_text("# Title\n\n短內容")
    assert isinstance(out, list)
    assert all(isinstance(x, str) for x in out)
    assert "[Title]" in out[0]


def test_faq_entry_unchanged():
    s = chunk_faq_entry("怎麼申請？", "上系統填表單。")
    assert "問：怎麼申請？" in s
    assert "答：上系統填表單。" in s


def test_chunk_result_dataclass_defaults():
    c = ChunkResult(text="hi")
    assert c.heading_path == []
    assert c.has_table is False
    assert c.has_code is False


# ──────────────────────────────────────────────────────────────────────────
# 法條 (legal) tests
# ──────────────────────────────────────────────────────────────────────────


def test_legal_article_simple():
    text = """
第一條
本契約之目的為規範雙方權利義務。
""".strip()
    chunks = chunk_structured(text)
    art = next(c for c in chunks if "目的" in c.text)
    assert art.heading_path == ["第一條"]
    assert "[第一條]" in art.text


def test_legal_chapter_section_article_hierarchy():
    text = """
第一章 總則

第一節 通則

第三條 保密義務
甲乙雙方對於業務上知悉之秘密應予保密。
""".strip()
    chunks = chunk_structured(text)
    art = next(c for c in chunks if "保密" in c.text and "甲乙" in c.text)
    assert art.heading_path == ["第一章 總則", "第一節 通則", "第三條 保密義務"]
    assert "[第一章 總則 > 第一節 通則 > 第三條 保密義務]" in art.text


def test_legal_article_with_inline_long_content_splits():
    """行內帶長內文時，第N條當 heading、後面當 paragraph。"""
    text = "第三條　甲乙雙方對於業務上知悉之資料應予以保密。違反者須負損害賠償責任。"
    chunks = chunk_structured(text)
    art = next(c for c in chunks if "甲乙" in c.text)
    assert art.heading_path == ["第三條"]
    assert "甲乙雙方" in art.text
    assert "違反者" in art.text


def test_legal_article_amendment_variant():
    """第N條之X 修正版條號要被認得。"""
    text = """
第三條之一
新增條款內容。
""".strip()
    chunks = chunk_structured(text)
    art = next(c for c in chunks if "新增" in c.text)
    assert art.heading_path == ["第三條之一"]


def test_legal_article_arabic_numerals():
    text = """
第3條
阿拉伯數字編號也要支援。
""".strip()
    chunks = chunk_structured(text)
    art = next(c for c in chunks if "阿拉伯" in c.text)
    assert art.heading_path == ["第3條"]


def test_legal_chapter_resets_article_in_stack():
    """跨章時，前一章內的條應該被 pop。"""
    text = """
第一章 總則
第一條
foo

第二章 罰則
第一條
bar
""".strip()
    chunks = chunk_structured(text)
    foo = next(c for c in chunks if "foo" in c.text)
    bar = next(c for c in chunks if "bar" in c.text)
    assert foo.heading_path == ["第一章 總則", "第一條"]
    assert bar.heading_path == ["第二章 罰則", "第一條"]


def test_long_legal_article_splits_at_subclauses():
    """過長條文應該以 (一)(二)(三) 子條款為邊界切，不要句界亂切。"""
    text = """
第五條 員工義務
員工應遵守下列各項規定：
(一) 不得洩漏業務上知悉之秘密。秘密包含但不限於客戶名單、技術資料與財務數據。
(二) 不得從事與公司業務競爭之行為。違反者將解除契約並追究法律責任。
(三) 應依公司政策參加教育訓練。缺席須提出正當理由。
(四) 應遵守工作時間與請假規定。
""".strip()
    chunks = chunk_structured(text, chunk_size=80)
    # 每個 chunk 都該屬於 第五條
    art_chunks = [c for c in chunks if c.heading_path == ["第五條 員工義務"]]
    assert len(art_chunks) >= 2
    # 應該至少能找到分別含有不同子條款的 chunk
    bodies = "\n---\n".join(c.text for c in art_chunks)
    assert "(一)" in bodies and "(二)" in bodies
    # 任一 chunk 都不該把子條款開頭跟內文劈開
    for c in art_chunks:
        # 如果文字內含子條款標記，它應該在某一行的開頭
        for marker in ["(一)", "(二)", "(三)", "(四)"]:
            if marker in c.text:
                # 該標記前面應該是換行（或位在 prefix breadcrumb 之後）
                idx = c.text.index(marker)
                assert idx == 0 or c.text[idx - 1] in ("\n", " ")


def test_legal_subclause_circled_numerals():
    """① ② ③ 也算子條款邊界。"""
    text = (
        "第八條 試用期\n"
        "① 試用期間為三個月。試用期間屆滿時得依工作表現決定是否續聘。"
        "② 試用期間之薪資依勞動契約所載辦理。試用期不得超過六個月。"
        "③ 試用期間離職毋須預告。但仍須完成業務交接。"
    )
    chunks = chunk_structured(text, chunk_size=60)
    art_chunks = [c for c in chunks if "第八條" in (c.heading_path[0] if c.heading_path else "")]
    assert len(art_chunks) >= 1


def test_legal_article_short_keeps_atomic_when_fits():
    """條文長度在 chunk_size 之內，應保持為單一 chunk。"""
    text = """
第二條 名詞定義
本契約所稱「保密資訊」係指任何商業機密。
""".strip()
    chunks = chunk_structured(text, chunk_size=500)
    arts = [c for c in chunks if c.heading_path == ["第二條 名詞定義"]]
    assert len(arts) == 1
    assert "保密資訊" in arts[0].text


def test_legal_heading_inside_paragraph_not_misdetected():
    """段落中提到「依第三條規定」這類引用，不應被誤判為新條。"""
    text = "本條款依第三條規定辦理。"
    chunks = chunk_structured(text)
    # 應該是純段落，無 heading
    assert len(chunks) == 1
    assert chunks[0].heading_path == []
    assert "依第三條規定" in chunks[0].text
