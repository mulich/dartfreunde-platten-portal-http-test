"""Bounded controls for the two explicitly authorized accounts in this test fork."""
import asyncio
import json
from pathlib import Path

from app.http_sessions import BOARDS, SessionError, segment

ALLOWED = {'mulich', 'dierote'}


async def peers(service, ident):
    account = service.account(ident)
    friends = await account.request('GET', '/as/v0/friends')
    if not isinstance(friends, list):
        raise SessionError('unknown_friends')
    ids={a.user_id for a in service.accounts.values() if a.username and a.username.casefold() in ALLOWED}
    result=[]
    for row in friends:
        user=row.get('user', row)
        uid=user.get('id') or row.get('userId')
        if uid in ids:
            # Only the two authorized accounts; never return full friend profiles.
            result.append({'name':user.get('name') or user.get('username'),
                           'status':row.get('status'), 'onlineStatus':row.get('onlineStatus'),
                           'online':row.get('online'), 'isOnline':row.get('isOnline')})
    return result


def state_path(data):
    return Path(data)/'http-test-lobby.json'


async def create_lobby(service, host_id, guest_id, board, data):
    host,guest=service.account(host_id),service.account(guest_id)
    await host.verify_identity();await guest.verify_identity()
    if {host.username.casefold(),guest.username.casefold()}!=ALLOWED or board not in BOARDS.values():
        raise SessionError('test_accounts_not_allowed')
    if await service.busy(host,'new-test') or await service.busy(guest,'new-test'):
        raise SessionError('test_account_busy')
    file=state_path(data)
    lobby=None
    if file.exists():
        old=json.loads(file.read_text())
        existing=await host.request('GET','/gs/v0/lobbies/'+segment(old['lobby_id']),missing=True)
        if existing:
            if old['host_ident']!=host_id or old['guest_ident']!=guest_id or old['board_id']!=board:
                raise SessionError('test_lobby_already_exists')
            if existing.get('host',{}).get('id')!=host.user_id or existing.get('isPrivate') is not True:
                raise SessionError('test_lobby_changed')
            lobby=existing
    if lobby is None:
        lobby=await host.request('POST','/gs/v0/lobbies',data={
            'variant':'X01','isPrivate':True,'hasReferee':False,'bullOffMode':'Off','legs':1,
            'settings':{'baseScore':501,'inMode':'Straight','outMode':'Double','bullMode':'25/50','maxRounds':20}})
    if not isinstance(lobby,dict):raise SessionError('unknown_lobby_state')
    lobby_id=segment(lobby.get('id'))
    record={'lobby_id':lobby_id,'host_ident':host_id,'guest_ident':guest_id,'board_id':board}
    file.write_text(json.dumps(record))
    path='/gs/v0/lobbies/'+lobby_id
    if not service.own(lobby,host.user_id):
        await host.request('POST',path+'/players',data={'name':host.username,'userId':host.user_id,'boardId':board})
    else:
        await host.request('PUT',path+'/players/by-userid/'+segment(host.user_id)+'/board',data={'boardId':board})
    fresh=await host.request('GET',path)
    row=service.own(fresh,host.user_id)
    if not row or row.get('boardId')!=board:raise SessionError('host_board_not_confirmed')
    service.settings.setdefault('boards',{})[host.username.casefold()]=board
    if host.username.casefold() not in {s.casefold() for s in service.settings.get('hosts',[])}:
        service.settings.setdefault('hosts',[]).append(host.username)
    (Path(data)/'automation.json').write_text(json.dumps(service.settings))
    service.registry.get(guest_id)['auto_accept']=True
    service.registry.save()
    await host.request('POST',path+'/invitations/'+segment(guest.user_id))
    return {**record,'guest':guest.username,'host':host.username}


async def lobby_status(service, data):
    file=state_path(data)
    if not file.exists():return {'lobby_id':None}
    record=json.loads(file.read_text());host=service.account(record['host_ident'])
    lobby=await host.request('GET','/gs/v0/lobbies/'+segment(record['lobby_id']),missing=True)
    if not lobby:return {**record,'exists':False}
    return {**record,'exists':True,'response_keys':sorted(lobby.keys()),
        'lobby_keys':sorted(lobby.get('lobby',{}).keys()),'players':[
        {k:p.get(k) for k in ('name','userId','hostId','boardId','isPending')}
        for p in (lobby.get('players') or [])]}
