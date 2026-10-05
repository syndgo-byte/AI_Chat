import io
import json
import pytest
from ai_chat import GeminiProvider, ChatError

def test_compose_redacts_contacts_and_uses_admin_schema(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','fake-local-test-key')
    monkeypatch.setenv('GEMINI_MODEL','test-model')
    requests=[]
    def transport(req,timeout):
        requests.append(json.loads(req.data))
        output={'title':'확인 안내','body':'담당자 확인이 필요합니다.'}
        return io.StringIO(json.dumps({'candidates':[{'content':{'parts':[{'text':json.dumps(output)}]}}]}))
    result=GeminiProvider(transport).compose('complaint_reply',{'body':'연락 010-1234-5678 test@example.com'})
    assert result['body']=='담당자 확인이 필요합니다.'
    payload=json.dumps(requests[0],ensure_ascii=False)
    assert '010-1234-5678' not in payload and 'test@example.com' not in payload
    assert 'Never promise refunds' in payload and 'not a customer chatbot' in payload
    assert requests[0]['generationConfig']['responseSchema']['required']==['title','body']

def test_invalid_compose_kind_never_calls_google():
    def transport(*args,**kwargs): raise AssertionError('should not call Google')
    with pytest.raises(ChatError): GeminiProvider(transport).compose('publish',{})

def test_invalid_compose_output_rejected(monkeypatch):
    provider=GeminiProvider()
    monkeypatch.setattr(provider,'_generate',lambda _: {'title':'','body':'draft'})
    with pytest.raises(ChatError) as error: provider.compose('notice',{'notes':'facts'})
    assert error.value.status==502
