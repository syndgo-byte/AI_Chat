"""Mount the common customer widget using local identity and server-only credentials."""
import hashlib
import hmac
import secrets
import time
import threading
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from .client import ServiceChatClient
from .chatbot import ChatError

class Message(BaseModel):
    model_config=ConfigDict(extra='forbid')
    content: str=Field(min_length=1,max_length=8000)
    expected_version: int=Field(ge=0)
    allow_external_processing: bool=False
class Draft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str=Field(min_length=1,max_length=200)
    body: str=Field(min_length=1,max_length=10000)
    expected_version: int=Field(ge=0)
class Submit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version: int=Field(ge=0)
    confirmed: bool=False
    email_notify: bool=False

def create_support_router(service_id, get_owner=None, client=None, get_contact=None):
    client=client or ServiceChatClient(service_id)
    router=APIRouter(tags=['AI support'])
    cookie_name='support_owner_'+service_id
    arrivals=OrderedDict(); lock=threading.Lock()
    def mutate(request):
        origin=request.headers.get('origin','')
        if not origin or origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403,'같은 서비스 화면에서 요청하세요.')
        ip=request.client.host if request.client else 'unknown'
        current=time.monotonic()
        with lock:
            entries=[t for t in arrivals.pop(ip,[]) if current-t<3600]
            if len(entries)>=60 or sum(current-t<60 for t in entries)>=10:
                raise HTTPException(429,'요청이 많습니다. 잠시 후 다시 시도하세요.')
            arrivals[ip]=entries+[current]
            while len(arrivals)>5000: arrivals.popitem(last=False)
    def owner(request,create=False):
        if get_owner:
            identity=get_owner(request)
            if not identity: raise HTTPException(401,'로그인이 필요합니다.')
            return str(identity),None
        signed=request.cookies.get(cookie_name,'')
        value,_,signature=signed.partition('.')
        key=client.token().encode()
        expected=hmac.new(key,value.encode(),hashlib.sha256).hexdigest()
        if value and len(value)==32 and hmac.compare_digest(expected,signature): return 'visitor:'+value,None
        if not create: raise HTTPException(401,'새 대화를 시작하세요.')
        value=secrets.token_hex(16)
        return 'visitor:'+value,value+'.'+hmac.new(key,value.encode(),hashlib.sha256).hexdigest()
    def invoke(request,path,method='GET',body=None,create=False):
        from fastapi.responses import JSONResponse
        try:
            if method!='GET': mutate(request)
            identity,new_cookie=owner(request,create)
            result=client.call(path,identity,method,body)
            response=JSONResponse(result)
            if new_cookie: response.set_cookie(cookie_name,new_cookie,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=86400)
            return response
        except ChatError as exc: raise HTTPException(exc.status,str(exc)) from None
    @router.get('/api/support/contact')
    def contact(request: Request):
        value=get_contact(request) if get_contact else ''
        return {'email_available':bool(value)}
    @router.get('/support')
    def page():
        return FileResponse(Path(__file__).with_name('widget.html'))
    @router.post('/api/support/sessions')
    def start(request: Request): return invoke(request,'/sessions','POST',create=True)
    @router.get('/api/support/sessions/{id}')
    def session(id: str,request: Request): return invoke(request,'/sessions/'+quote(id,safe=''))
    @router.post('/api/support/sessions/{id}/messages')
    def message(id: str,request: Request,body: Message): return invoke(request,'/sessions/'+quote(id,safe='')+'/messages','POST',body.model_dump())
    @router.put('/api/support/sessions/{id}/draft')
    def draft(id: str,request: Request,body: Draft): return invoke(request,'/sessions/'+quote(id,safe='')+'/draft','PUT',body.model_dump())
    @router.post('/api/support/sessions/{id}/complaint')
    def submit(id: str,request: Request,body: Submit):
        payload=body.model_dump()
        payload['contact_email']=get_contact(request) if get_contact else ''
        if body.email_notify and not payload['contact_email']: raise HTTPException(400,'서비스 계정에 답변 받을 이메일이 없습니다.')
        return invoke(request,'/sessions/'+quote(id,safe='')+'/complaint','POST',payload)
    return router
