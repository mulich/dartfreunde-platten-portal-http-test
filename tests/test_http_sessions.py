import asyncio
import base64
import json
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.http_sessions import HttpAccount, HttpSessions, SessionStore, SessionError, BOARDS


def token(user='own', name='Mulich'):
    body=base64.urlsafe_b64encode(json.dumps({'sub':user,'preferred_username':name}).encode()).decode().rstrip('=')
    return 'header.'+body+'.signature'


def credentials(user='own', refresh='secret-refresh'):
    return {'access_token':token(user),'refresh_token':refresh,'expires_in':300}


def setup(tmp_path, *, finish=False, timeout=False, wrong_board=False, busy=False):
    item={'id':'player','auto_accept':True}
    registry=SimpleNamespace(get=lambda i:item)
    notice={'id':'notice','type':'lobby:invite','body':{'user':{'id':'host','name':'blau'},'lobby':{'id':'lobby'}}}
    board=BOARDS['blau']
    lobby={'id':'lobby','isPrivate':True,'host':{'id':'host'},'players':[
        {'userId':'host','hostId':'host','boardId':board,'isPending':False},
        {'userId':'own','hostId':'own','isPending':True}]}
    calls=[];joined=False
    def respond(request):
        nonlocal joined
        calls.append((request.method,request.url.path,request.content))
        path=request.url.path
        if path=='/auth/v1/account/me':return httpx.Response(200,json={'id':'own'})
        if path=='/as/v0/notifications':return httpx.Response(200,json=[notice])
        if path=='/us/v0/match-id':return httpx.Response(200,json='other' if busy else None)
        if path=='/gs/v0/matches/other/state':return httpx.Response(200,json={'finished':False})
        if path=='/gs/v0/lobbies':return httpx.Response(200,json=[lobby])
        if request.method=='POST' and path=='/gs/v0/lobbies/lobby/players/with-host/host':
            joined=True
            lobby['players'][1].update(isPending=False,hostId='host',boardId='wrong' if wrong_board else board)
            if timeout:raise httpx.ReadTimeout('must not log secrets',request=request)
            return httpx.Response(204)
        if path=='/gs/v0/lobbies/lobby':
            return httpx.Response(404) if joined and finish else httpx.Response(200,json=lobby)
        if path=='/gs/v0/matches/lobby':return httpx.Response(200,json=lobby)
        if request.method=='DELETE' and path=='/as/v0/notifications/notice':return httpx.Response(204)
        raise AssertionError((request.method,path))
    service=HttpSessions(registry,{'hosts':['blau']},tmp_path,
        client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    service.account('player').install(credentials())
    return service,item,notice,lobby,calls


def test_http_join_local_confirmation_and_duplicate_invitation(tmp_path):
    service,item,notice,lobby,calls=setup(tmp_path)
    async def run():
        await service.tick('player');await service.tick('player')
        await service.close()
    asyncio.run(run())
    posts=[c for c in calls if c[0]=='POST']
    assert len(posts)==1
    assert json.loads(posts[0][2])=={'name':'Mulich','userId':'own'}
    assert service.status['player']['board_id']==BOARDS['blau']
    assert service.store.read('player')['receipts']['notice']['done']
    assert 'secret-refresh' not in json.dumps(service.summary('player'))
    assert stat.S_IMODE(service.store.path('player').stat().st_mode)==0o600


def test_match_starts_before_confirmation(tmp_path):
    service,*_=setup(tmp_path,finish=True)
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert service.status['player'].get('last_accepted')


def test_timeout_after_server_acceptance_does_not_post_twice(tmp_path):
    service,item,notice,lobby,calls=setup(tmp_path,timeout=True)
    async def run():
        await service.tick('player')
        assert service.status['player']['error']=='network'
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert len([c for c in calls if c[0]=='POST'])==1
    assert service.status['player'].get('last_accepted')


def test_host_need_not_be_a_player_when_local_players_use_its_board(tmp_path):
    service,item,notice,lobby,calls=setup(tmp_path)
    lobby['players'][0]['userId']=None
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert service.status['player']['stage']=='confirmed'
    assert service.status['player']['sender']=='blau'


def test_native_join_without_host_player_is_verified_after_join(tmp_path):
    service,item,notice,lobby,calls=setup(tmp_path)
    lobby['players'][0].update(userId=None,hostId=None,boardId=None)
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert service.status['player']['stage']=='confirmed'
    assert service.status['player']['board_id']==BOARDS['blau']


def test_failed_old_invitation_does_not_hide_next_invitation(tmp_path):
    service,item,notice,lobby,calls=setup(tmp_path)
    old={**notice,'id':'old-notice','body':{'user':{'id':'old-host','name':'rot'},'lobby':{'id':'old-lobby'}}}
    service.settings['hosts'].append('rot')
    account=service.account('player');original=account.request
    async def request(method,path,**kwargs):
        if path=='/as/v0/notifications':return [old,notice]
        if path=='/gs/v0/lobbies/old-lobby':
            return {'id':'old-lobby','host':{'id':'old-host'},'isPrivate':True,
                    'players':[{'userId':'old-host','boardId':'wrong-board'}]}
        return await original(method,path,**kwargs)
    account.request=request
    service.report('player','old',sender='dierote',http_status=403)
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    status=service.status['player']
    assert status['sender']=='blau' and status['http_status'] is None
    assert status['stage']=='confirmed'
    assert status['invitations'][0]['sender']=='rot'
    assert status['invitations'][0]['error']=='host_board_not_confirmed'
    assert status['invitations'][1]['stage']=='confirmed'


def test_no_invitation_clears_stale_sender_and_http_status(tmp_path):
    service,*_=setup(tmp_path)
    account=service.account('player');original=account.request
    async def request(method,path,**kwargs):
        if path=='/as/v0/notifications':return []
        return await original(method,path,**kwargs)
    account.request=request
    service.report('player','old',sender='dierote',lobby_id='old',http_status=403)
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert service.status['player']['sender'] is None
    assert service.status['player']['http_status'] is None
    assert service.status['player']['lobby_id'] is None
    assert service.status['player']['invitations']==[]


@pytest.mark.parametrize('change',['friend','host','public','board','busy','paused','disabled','wrong-identity'])
def test_never_joins_unapproved_or_busy_accounts(tmp_path,change):
    service,item,notice,lobby,calls=setup(tmp_path,busy=change=='busy')
    if change=='friend':notice['type']='friend-list:request'
    if change=='host':notice['body']['user']['name']='unknown'
    if change=='public':lobby['isPrivate']=False
    if change=='board':lobby['players'][0]['boardId']='unexpected'
    if change=='paused':item['paused']=True
    if change=='disabled':item['auto_accept']=False
    if change=='wrong-identity':service.account('player').user_id='other'
    async def run():
        try:await service.tick('player')
        except SessionError:pass
        await service.close()
    asyncio.run(run())
    assert not [c for c in calls if c[0]=='POST']


def test_unconfirmed_local_board_is_not_success(tmp_path,monkeypatch):
    service,item,notice,lobby,calls=setup(tmp_path,wrong_board=True)
    async def no_delay(*args):pass
    monkeypatch.setattr('app.http_sessions.asyncio.sleep',no_delay)
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert not service.status['player'].get('last_accepted')
    assert not [c for c in calls if c[0]=='DELETE']


def test_refresh_rotation_is_persisted_and_subject_is_pinned(tmp_path):
    store=SessionStore(tmp_path/'sessions');store.save('player',{'user_id':'own','username':'Mulich','refresh_token':'old'})
    calls=[]
    def respond(request):
        calls.append(request)
        assert json.loads(request.content)=={'client_id':'autodarts-play','refresh_token':'old'}
        return httpx.Response(200,json=credentials(refresh='rotated'))
    account=HttpAccount('player',store,httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    async def run():
        await asyncio.gather(account.refresh(),account.refresh())
        await account.close()
    asyncio.run(run())
    assert len(calls)==1 and store.read('player')['refresh_token']=='rotated'
    assert 'access_token' not in store.read('player')
    with pytest.raises(SessionError,match='account_changed'):account.install(credentials(user='different'))


def test_401_refresh_and_retry_once_and_login_failure_is_sanitized(tmp_path):
    calls=[]
    def respond(request):
        calls.append(request.url.path)
        if request.url.path=='/auth/v1/refresh':return httpx.Response(200,json=credentials(refresh='new'))
        return httpx.Response(401,json={'secret':'never expose'})
    account=HttpAccount('player',SessionStore(tmp_path),httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    account.install(credentials())
    async def run():
        with pytest.raises(SessionError,match='http_error') as error:await account.request('GET','/private')
        assert 'secret' not in str(error.value)
        await account.close()
    asyncio.run(run())
    assert calls==['/private','/auth/v1/refresh','/private']


def test_presence_uses_ticket_and_subscriptions_without_browser(tmp_path):
    service,*_=setup(tmp_path);account=service.account('player')
    account.request=AsyncMock(return_value={'code':'private-ticket'})
    sent=[]
    class WS:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def send(self,data):sent.append(json.loads(data))
        def __aiter__(self):return self
        async def __anext__(self):raise asyncio.CancelledError()
    def connect(url,**kwargs):
        assert url=='wss://play.ws.autodarts.com/ms/v0/subscribe?code=private-ticket'
        return WS()
    service.connector=connect
    async def run():
        with pytest.raises(asyncio.CancelledError):await service.presence(account,asyncio.Event())
        await service.close()
    asyncio.run(run())
    assert {s['channel'] for s in sent}=={'autodarts.notifications','autodarts.friends','autodarts.users'}
    assert 'private-ticket' not in json.dumps(service.summary('player'))


@pytest.mark.parametrize('location,allowed',[
    ('/as/v0/friends/',True),('https://other.example/friends',False),
    ('http://api.autodarts.com/as/v0/friends/',False)])
def test_redirects_never_leak_authorization_to_another_origin(tmp_path,location,allowed):
    calls=[]
    def respond(request):
        calls.append(str(request.url))
        if len(calls)==1:return httpx.Response(301,headers={'location':location})
        return httpx.Response(200,json=[])
    account=HttpAccount('player',SessionStore(tmp_path),httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    account.install(credentials())
    async def run():
        if allowed:assert await account.request('GET','/as/v0/friends')==[]
        else:
            with pytest.raises(SessionError,match='unsafe_redirect'):await account.request('GET','/as/v0/friends')
        await account.close()
    asyncio.run(run())
    assert len(calls)==(2 if allowed else 1)


def test_empty_native_states_are_not_mistaken_for_live_games(tmp_path):
    service,*_=setup(tmp_path);account=service.account('player')
    account.request=AsyncMock(side_effect=['',None])
    async def run():
        assert not await service.busy(account,'target')
        await service.close()
    asyncio.run(run())
    assert service.own({'players':None},'own') is None


def test_disabling_while_last_lobby_read_is_in_flight_prevents_join(tmp_path):
    service,item,notice,lobby,calls=setup(tmp_path)
    account=service.account('player');original=account.request;reads=0
    async def request(method,path,**kwargs):
        nonlocal reads
        result=await original(method,path,**kwargs)
        if method=='GET' and path=='/gs/v0/lobbies/lobby':
            reads+=1
            if reads==2:item['auto_accept']=False
        return result
    account.request=request
    async def run():
        await service.tick('player');await service.close()
    asyncio.run(run())
    assert not [c for c in calls if c[0]=='POST']
