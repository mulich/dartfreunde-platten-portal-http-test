import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.http_test import create_lobby
from app.http_sessions import HttpSessions, BOARDS


def test_test_lobby_adds_host_before_assigning_guest(tmp_path):
    board=BOARDS['blau'];lobby={'id':'test-lobby','isPrivate':True,'host':{'id':'h'},'players':None}
    host=SimpleNamespace(username='mulich',user_id='h',verify_identity=AsyncMock())
    guest=SimpleNamespace(username='dierote',user_id='g',verify_identity=AsyncMock())
    calls=[];item={'auto_accept':False}
    async def request(method,path,**kwargs):
        calls.append((method,path,kwargs))
        if method=='POST' and path=='/gs/v0/lobbies':return lobby
        if method=='POST' and path.endswith('/players'):
            lobby['players']=[{'userId':'h','boardId':board}];return
        if method=='GET':return lobby
    host.request=request
    service=SimpleNamespace(account=lambda ident:host if ident=='host' else guest,
        busy=AsyncMock(return_value=False),own=HttpSessions.own,settings={'hosts':[]},
        registry=SimpleNamespace(get=lambda i:item,save=lambda:None))
    result=asyncio.run(create_lobby(service,'host','guest',board,tmp_path))
    assert result['lobby_id']=='test-lobby'
    assert item['auto_accept']
    assert calls[-1][1].endswith('/invitations/g')
    assert [c[1] for c in calls[:2]]==['/gs/v0/lobbies','/gs/v0/lobbies/test-lobby/players']
