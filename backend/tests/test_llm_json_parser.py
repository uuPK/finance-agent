from app.llm.json_parser import extract_json_object


def test_extract_json_object_from_fenced_response() -> None:
    content = """```json
{"passed": true, "score": 95}
```"""

    assert extract_json_object(content) == {"passed": True, "score": 95}


def test_extract_json_object_from_prefixed_response() -> None:
    content = '好的，结果如下：{"plan_status": "ready", "confidence": 0.9}'

    assert extract_json_object(content) == {"plan_status": "ready", "confidence": 0.9}
