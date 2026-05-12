"""驗證 LLM JSON 輸出的容錯解析（給 Router 與其他 JSON-mode agent 共用）。"""

from app.agents._json_util import parse_json_loose


def test_parse_plain_json():
    out = parse_json_loose('{"intent":"x","category":"hr","confidence":0.9}')
    assert out == {"intent": "x", "category": "hr", "confidence": 0.9}


def test_parse_json_code_fence():
    raw = '```json\n{"intent":"x","category":"hr","confidence":0.9}\n```'
    out = parse_json_loose(raw)
    assert out == {"intent": "x", "category": "hr", "confidence": 0.9}


def test_parse_with_leading_text():
    raw = '這是分類結果：\n{"intent":"x","category":"loan","confidence":0.8}'
    out = parse_json_loose(raw)
    assert out == {"intent": "x", "category": "loan", "confidence": 0.8}


def test_parse_empty():
    assert parse_json_loose("") is None
    assert parse_json_loose("not json at all") is None


def test_parse_multiline_json():
    raw = '''
{
  "intent": "leave_inquiry",
  "category": "hr",
  "confidence": 0.95
}
'''
    out = parse_json_loose(raw)
    assert out["intent"] == "leave_inquiry"
    assert out["category"] == "hr"
