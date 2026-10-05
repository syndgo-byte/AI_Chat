# AI Chat 0.3.0
마지막 업데이트: 2026-10-05 22:40 (Asia/Seoul)

각 서비스의 고객 화면에 탑재하고 MCP 허브에서 답변 기준·민원 분류·승인 학습을 중앙 관리하는 공통 모듈이다.

- 고객 화면: `/support`, Enter 전송 / Shift+Enter 줄바꿈, 서비스 로그인 또는 서명된 방문 세션 사용. 고객에게 허브 토큰이나 Google 키를 요구하지 않는다.
- 서비스 서버: `ai_chat.adapter.create_support_router(service_id, get_owner=...)`가 사용자 신원을 서버에서 확인하고 `ServiceChatClient`로 중앙 API를 호출한다.
- 중앙 허브: Google 연결, 서비스별 정책, 대화 저장, FAQ·처리 답변 승인, 민원 접수, 감사 이력. Google 키는 서버 환경변수로만 전달한다.
- 학습: 관리자 작성 FAQ 또는 처리 완료 민원의 처리 결과를 **후보**로 등록하고 별도 승인하면 동일 서비스의 유사 질문 답변 자료로 재사용한다. 모델 가중치 재학습이나 고객 메시지의 자동 정책 반영은 하지 않는다.

## 서비스에 탑재

```python
from ai_chat.adapter import create_support_router
# 기존 로그인 계정 식별자는 신뢰할 수 있는 서버 함수에서 가져온다.
app.include_router(create_support_router('my-service', get_owner=lambda request: current_user(request)['id']))
# 로그인 없는 서비스: 서명된 HttpOnly 방문 세션과 동일 출처 검사를 사용한다.
# app.include_router(create_support_router('my-service'))
```

`pip install -e .[web]`로 설치한다. 고객 화면 링크는 `/support`이다. 실제 등록 서비스 EMSv3와 funeral에 탑재 코드를 연결했다. 테스트용 service 노드에는 별도 실제 앱이 없어 탑재하지 않는다.

서비스 서버 환경설정: `AI_CHAT_HUB_URL` (기본 로컬 9890), `AI_CHAT_SERVICE_TOKEN_FILE` 또는 `AI_CHAT_SERVICE_TOKEN`. 원격 허브 연결은 HTTPS를 사용한다. 로컬 워크스페이스에서는 Hub의 `scripts/setup_chatbot_access.py`가 등록 서비스별 연결키 파일을 제한된 권한으로 생성한다. 브라우저에는 전달하지 않는다. 다른 호스트 배포는 해당 서비스 전용 키만 서버 환경에 전달해야 한다.

## 자동 응답과 분류

허브 AI 챗봇 → 서비스 선택 → **자동 응답 · 학습 관리**. 자동 응답은 기본 꺼져 있다. 실제 FAQ를 등록·승인하고 허용 카테고리와 자동 응답을 설정한다. 승인된 질문과 정규화 문자 유사도가 기준 이상인 경우 승인 답변을 그대로 응답한다. 이 값은 휴리스틱 유사도이며 모델의 확률이나 정확도 수치가 아니다.

Google은 대화의 민원 사실·빠진 정보·카테고리를 구조화 추출한다. 서버는 원문에서 위험 신호를 별도로 검사하고 답변 가능 여부를 결정한다. 결제·환불·개인정보 요청, 명시적 욕설·위협, 일부 정책 변경 문구는 자동 응답을 보류한다. 신고나 고소 의사 자체는 악성으로 확정하지 않는다. 악성 **의심**은 담당자 검토 신호이며 제재를 자동 실행하지 않는다. 키워드와 유사도 검사는 모든 우회·의미를 탐지하는 판별기가 아니므로 불확실한 질문은 검토로 보낸다.

원본 대화에서 발생한 검토 신호는 같은 대화에서 누적 유지된다. 고객이 나중에 초안을 고치거나 AI가 낮은 위험 분류를 제안해도 해제되지 않는다. 민원 접수 시 `support_evidence`로 보존하며 기존 민원 분류를 다시 실행해도 자동 경로로 바뀌지 않는다. 정책·승인 변경은 관리자 접근 API만 제공하고 개정 번호와 감사 이력을 기록한다.

민원은 고객이 내용을 확인한 후 접수하며 접수·환불 등의 행위를 AI가 수행했다고 주장하지 않는다. 답변 자료가 없거나 검토 대상이면 담당자 확인 안내와 민원 초안을 제공한다. 기존 ComplaintDesk의 규칙 기반 자동 발송·AutoSendLearner를 통해 새 챗봇 판단을 우회하지 않는다.

## 직접 모듈 사용

```python
from ai_chat import Chatbot, GeminiProvider, SupportStore
bot=Chatbot('chat.db',GeminiProvider(),support=SupportStore('support.db'))
s=bot.create_session({'id':'my-service','description':'서비스 설명'},owner='trusted-user-id')
s=bot.message(s['id'],'로그인이 안 됩니다',expected_version=s['version'],allow_external_processing=True)
```

라이브러리 자체는 로그인 시스템이 아니다. 직접 호출하는 앱은 요청마다 서비스와 대화 소유권을 검증해야 한다. 중앙 서비스 API는 서비스 전용 인증과 소유자 검사를 제공한다. 고객 HTTP 어댑터는 동일 출처 요청 검사 및 프로세스 내 IP별 호출 제한을 사용한다. 여러 프로세스·여러 인스턴스 배포에서는 게이트웨이의 통합 호출 제한을 추가한다.

대화는 지정한 SQLite에 저장한다. 외부 전송은 동의 시에만 하고 연락처·주민번호 패턴을 가리지만 완전한 개인정보 탐지기는 아니다. 한 요청당 Google 호출 한 번, 자동 재시도·자동 유료 전환 없음. 검색 연동 없음. Google API 요금·한도는 프로젝트 설정을 따른다.

`python -m pytest tests -q`로 검증한다. 기존 AIEngine, Classifier, AnswerGenerator, AutoSendLearner 인터페이스는 유지한다.


## 관리자 초안 작성

관리 서비스의 민원 상세에서 **AI 답변 채우기**, 공지 작성에서 **AI 공지 채우기**를 누른다. 알림 상세의 **이 알림으로 공지 작성**은 기존 알림 내용을 가져온다. 민원 원문과 담당자 메모 또는 공지 핵심 사항을 Google로 전송하고 편집 가능한 제목·내용을 반환한다. 생성 자체는 저장·승인·발송·게시 상태를 바꾸지 않는다.

공통 작성 API: `GeminiProvider().compose('complaint_reply' 또는 'notice', facts)`. 중앙 관리 HTTP API는 `/ai/chat/compose/complaints/{id}`와 `/ai/chat/compose/notice`이며 관리자 인증이 필요하다. 고객 챗봇 답변 승인 자료와 관리자가 검토할 작성 초안은 분리한다.
