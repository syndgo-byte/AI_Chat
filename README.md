# AI Chat
마지막 업데이트: 2026-10-03 20:59


Shared rule-based classification, draft answer generation, and related answer recommendations for ops services. The classifier, answer templates, and repeat learner were copied from `ops/complaints` for the initial version. This package does not call an LLM or send answers automatically.

```python
from ai_chat import AIEngine

engine = AIEngine()
result = engine.analyze({"title": "로그인 오류", "body": "로그인이 안 됩니다"})

answered_items = [
    {"id": 1, "title": "로그인 오류", "body": "로그인 안됨", "answer": "비밀번호를 확인하세요"}
]
suggestions = engine.suggest("로그인 문제", answered_items)
```

`analyze` returns category, route, risk, VIP and abuse flags, a draft answer, and its confidence. Unknown categories receive an empty answer and zero confidence. `suggest` ranks answered items by normalized title and body similarity and returns at most `limit` results.

Install with `pip install -e .` from this directory, or add this directory to `PYTHONPATH`. Run tests with `python -m pytest tests -q`.

To register the module with a running local Hub:

```powershell
$rootPath = (Resolve-Path .).Path
$body = @{root=$rootPath; entry='ai_chat/__init__.py'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:9890/hub/register' -ContentType 'application/json' -Body $body
```

The Hub records `ai_chat.analyze` and `ai_chat.suggest` in its tool catalog. Services call the Python package directly; Hub registration is metadata, not an HTTP execution endpoint.

Version: 0.1.0
