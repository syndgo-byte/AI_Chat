import json
from unittest.mock import Mock
import pytest
from ai_chat import Chatbot, ChatError, GeminiProvider


class Provider:
    def respond(self, history, service, previous_draft):
        return {'reply': '결제 문제 내용을 정리했습니다. 언제 발생했나요?', 'draft': {'title': '결제 후 이용 불가', 'body': history[-1]['content']}, 'missing_fields': ['발생 시점']}


class Desk:
    def __init__(self):
        self.items = {}
    def submit(self, service_id, title, body, *, reporter, intake_key):
        if intake_key not in self.items:
            self.items[intake_key] = dict(id=len(self.items)+1, service_id=service_id, title=title, body=body)
        return self.items[intake_key]
    def get(self, id):
        return next(v for v in self.items.values() if v['id'] == id)


def test_conversation_drafts_without_submitting_and_manual_edit(tmp_path):
    bot = Chatbot(tmp_path/'chat.db', Provider())
    session = bot.create_session({'id': 'EMSv3', 'description': 'EMS'})
    session = bot.message(session['id'], '결제했는데 이용이 안 돼요', expected_version=0, allow_external_processing=True)
    assert len(session['messages']) == 2 and session['draft']['body'] == '결제했는데 이용이 안 돼요'
    assert session['complaint_id'] is None
    edited = bot.edit_draft(session['id'], {'title': '수정 제목', 'body': '수정 내용'}, expected_version=session['version'])
    assert edited['draft']['title'] == '수정 제목'
    assert bot.session(session['id']) == edited


def test_consent_and_stale_versions_are_rejected(tmp_path):
    provider = Mock(wraps=Provider())
    bot = Chatbot(tmp_path/'chat.db', provider)
    session = bot.create_session({'id':'EMS'})
    with pytest.raises(ChatError):
        bot.message(session['id'], '내용', expected_version=0)
    provider.respond.assert_not_called()
    bot.message(session['id'], '내용', expected_version=0, allow_external_processing=True)
    with pytest.raises(ChatError) as caught:
        bot.message(session['id'], '중복', expected_version=0, allow_external_processing=True)
    assert caught.value.status == 409
    assert provider.respond.call_count == 1


def test_confirmed_intake_is_idempotent(tmp_path):
    bot = Chatbot(tmp_path/'chat.db', Provider())
    session = bot.create_session({'id':'EMS'})
    session = bot.message(session['id'], '로그인 문제', expected_version=0, allow_external_processing=True)
    desk = Desk()
    with pytest.raises(ChatError):
        bot.submit_complaint(session['id'], desk, expected_version=session['version'])
    assert desk.items == {}
    first = bot.submit_complaint(session['id'], desk, confirmed=True, expected_version=session['version'])
    second = bot.submit_complaint(session['id'], desk, confirmed=True, expected_version=session['version'])
    assert first['complaint']['id'] == second['complaint']['id']
    assert second['deduplicated'] and len(desk.items) == 1
    with pytest.raises(ChatError):
        bot.message(session['id'], '추가', expected_version=first['session']['version'], allow_external_processing=True)


def test_provider_failure_does_not_change_session(tmp_path):
    provider = Mock()
    provider.respond.side_effect = ChatError('연결 실패', 502)
    bot = Chatbot(tmp_path/'chat.db', provider)
    session = bot.create_session({'id':'EMS'})
    with pytest.raises(ChatError):
        bot.message(session['id'], '문제', expected_version=0, allow_external_processing=True)
    assert bot.session(session['id']) == session


def test_crash_between_intake_and_session_update_does_not_duplicate(tmp_path):
    class FailingDesk(Desk):
        fail = True
        def submit(self, *args, **kwargs):
            result = super().submit(*args, **kwargs)
            if self.fail:
                self.fail = False
                raise RuntimeError('simulated interrupted reply')
            return result
    bot = Chatbot(tmp_path/'chat.db', Provider())
    session = bot.create_session({'id':'EMS'})
    session = bot.message(session['id'], '문제', expected_version=0, allow_external_processing=True)
    desk = FailingDesk()
    with pytest.raises(RuntimeError):
        bot.submit_complaint(session['id'], desk, confirmed=True, expected_version=session['version'])
    result = bot.submit_complaint(session['id'], desk, confirmed=True, expected_version=session['version'])
    assert result['complaint']['id'] == 1 and len(desk.items) == 1


def test_google_payload_redacts_contacts_and_validates_json(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setenv('GEMINI_MODEL', 'test-model')
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            output = {'reply':'확인할 내용을 정리했어요','has_complaint':True,'title':'로그인 문제','body':'로그인이 안 됨','missing_fields':['발생 시점']}
            return json.dumps({'candidates':[{'content':{'parts':[{'text':json.dumps(output)}]}}]}).encode()
    def transport(req, timeout):
        captured.append(req)
        return Response()
    provider = GeminiProvider(transport=transport)
    assert 'api_key' not in provider.status()
    output = provider.respond([{'role':'user','content':'010-1234-5678 test@example.com 900101-1234567 로그인 안됨'}], {'id':'EMS'})
    payload = captured[0].data.decode()
    assert '010-1234-5678' not in payload and 'test@example.com' not in payload and '900101-1234567' not in payload
    assert 'test-key' not in captured[0].full_url
    assert output['draft']['title'] == '로그인 문제'


def test_missing_google_key_is_explicit(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_MODEL', raising=False)
    provider = GeminiProvider()
    assert provider.status()['configured'] is False
    with pytest.raises(ChatError) as caught:
        provider.respond([{'role':'user','content':'test'}], {'id':'EMS'})
    assert caught.value.status == 503


@pytest.mark.parametrize('error,expected', [
    ({'message': 'API key not valid. secret-example', 'details': [{'reason': 'API_KEY_INVALID'}]}, '키가 올바르지'),
    ({'message': 'Request blocked secret-example', 'details': [{'reason': 'API_KEY_SERVICE_BLOCKED'}]}, '사용 제한'),
    ({'message': 'Invalid JSON payload received secret-example'}, '요청 형식'),
    ({'message': 'model is not available secret-example'}, '모델 ID'),
    ({'message': 'unknown secret-example'}, 'HTTP 400'),
])
def test_google_400_diagnostics_do_not_expose_raw_error(monkeypatch, error, expected):
    from io import BytesIO
    from urllib.error import HTTPError
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setenv('GEMINI_MODEL', 'test-model')
    def transport(req, timeout):
        raise HTTPError(req.full_url, 400, 'Bad Request', {}, BytesIO(json.dumps({'error': error}).encode()))
    with pytest.raises(ChatError) as caught:
        GeminiProvider(transport).respond([{'role': 'user', 'content': 'test'}], {'id': 'test'})
    assert expected in str(caught.value)
    assert 'secret-example' not in str(caught.value)
    assert caught.value.status == 502
