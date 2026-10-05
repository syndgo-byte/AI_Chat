from fastapi import FastAPI
from fastapi.testclient import TestClient
from ai_chat.adapter import create_support_router

class Client:
    def __init__(self): self.calls=[]
    def call(self,path,owner,method='GET',body=None): self.calls.append((path,owner,body));return {'ok':True}

def test_account_email_is_server_supplied():
    upstream=Client();app=FastAPI()
    app.include_router(create_support_router('EMS',get_owner=lambda request:'logged-in-user',get_contact=lambda request:'account@example.com',client=upstream))
    client=TestClient(app)
    assert client.get('/api/support/contact').json()=={'email_available':True}
    result=client.post('/api/support/sessions/test/complaint',headers={'Origin':'http://testserver'},json={'expected_version':0,'confirmed':True,'email_notify':True})
    assert result.status_code==200
    assert upstream.calls[-1][1]=='logged-in-user' and upstream.calls[-1][2]['contact_email']=='account@example.com'
    assert client.post('/api/support/sessions/test/complaint',headers={'Origin':'http://testserver'},json={'expected_version':0,'confirmed':True,'email_notify':True,'contact_email':'other@example.com'}).status_code==422

def test_no_account_email_cannot_request_email_delivery():
    upstream=Client();app=FastAPI();app.include_router(create_support_router('EMS',get_owner=lambda request:'user',client=upstream))
    client=TestClient(app)
    assert client.get('/api/support/contact').json()=={'email_available':False}
    response=client.post('/api/support/sessions/test/complaint',headers={'Origin':'http://testserver'},json={'expected_version':0,'confirmed':True,'email_notify':True})
    assert response.status_code==400 and upstream.calls==[]
