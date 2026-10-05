"""Server-only client for a service-scoped central ai_chat deployment."""
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from .chatbot import ChatError

class ServiceChatClient:
    def __init__(self, service_id, base_url=None, token_file=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',service_id): raise ValueError('Invalid service ID')
        self.service_id=service_id
        self.base_url=(base_url or os.getenv('AI_CHAT_HUB_URL','http://127.0.0.1:9890')).rstrip('/')
        url=urlsplit(self.base_url)
        if url.scheme != 'https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')): raise ValueError('Use HTTPS for remote service connections')
        self.token_file=Path(token_file or os.getenv('AI_CHAT_SERVICE_TOKEN_FILE',str(Path(__file__).resolve().parents[3]/'mcp_hub'/'.chatbot'/('service-'+service_id+'.token'))))
    def token(self):
        token=os.getenv('AI_CHAT_SERVICE_TOKEN','')
        if not token:
            try: token=self.token_file.read_text(encoding='utf-8').strip()
            except OSError: raise ChatError('관리자가 서비스 챗봇 연결을 설정해야 합니다.',503) from None
        if len(token)<24: raise ChatError('서비스 챗봇 연결 설정을 확인하세요.',503)
        return token
    def call(self,path,owner,method='GET',body=None):
        payload={**(body or {}),'owner':owner}
        url=self.base_url+'/ai/service/'+quote(self.service_id,safe='')+path
        if method=='GET': url+='?'+urlencode({'owner':owner})
        req=Request(url,data=json.dumps(payload,ensure_ascii=False).encode() if method!='GET' else None,method=method,headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token()})
        try:
            with urlopen(req,timeout=60) as r: return json.load(r)
        except HTTPError as exc:
            try: message=json.load(exc).get('detail','챗봇 요청에 실패했습니다.')
            except (ValueError,AttributeError): message='챗봇 요청에 실패했습니다.'
            raise ChatError(message if isinstance(message,str) else '입력값을 확인하세요.',exc.code) from None
        except (URLError,TimeoutError): raise ChatError('중앙 챗봇 서비스에 연결할 수 없습니다.',503) from None
