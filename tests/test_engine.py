from ai_chat import AIEngine, manifest


def test_analyze_known_category(engine):
    result = engine.analyze({"title": "로그인 오류", "body": "로그인이 안 됩니다"})
    assert result["category"] == "outage"
    assert result["answer"]
    assert 0 < result["confidence"] <= 1
    assert result["route"] in {"auto", "approve", "owner", "vip"}


def test_analyze_unknown_category_skips_answer(engine):
    result = engine.analyze({"title": "hello", "body": "world"})
    assert result["category"] == "other"
    assert result["answer"] == ""
    assert result["confidence"] == 0.0


def test_suggest_ranks_answered_matches(engine):
    items = [
        {"id": 1, "title": "로그인 오류", "body": "로그인 안됨", "answer": "비밀번호 확인", "confidence": 0.8},
        {"id": 2, "title": "결제 실패", "body": "결제 안됨", "answer": "결제 재시도", "confidence": 0.7},
        {"id": 3, "title": "로그인 문제", "body": "로그인 안됨", "answer": ""},
    ]
    result = engine.suggest("로그인 문제 있어요", items, limit=2)
    assert result
    assert result[0]["item_id"] == 1
    assert all(item["item_id"] != 3 for item in result)
    assert engine.suggest("", items) == []
    assert engine.suggest("로그인", items, limit=0) == []


def test_manifest_and_public_imports():
    assert manifest()["id"] == "ai_chat"
    assert isinstance(AIEngine(), AIEngine)
