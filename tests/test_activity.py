import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import activity
from app.http_sessions import BOARDS, HttpSessions, SessionError
from tests.test_http_sessions import credentials

ROT = BOARDS['rot']


def service(tmp_path, respond, users=('own',)):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return respond(request)
    registry = SimpleNamespace(get=lambda i: {'id': i})
    result = HttpSessions(registry, {'hosts': ['rot']}, tmp_path,
                          client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    for user in users:
        result.account(user).install(credentials(user))
    return result, calls


def match(host='rot-id', board=ROT):
    return {'id': 'm1', 'variant': 'X01', 'host': {'id': host, 'name': 'rot'}, 'players': [
        {'userId': 'own', 'name': 'Mulich', 'boardId': board},
        {'userId': 'ly', 'name': 'Ly', 'boardId': board}]}


def test_player_activity_names_opponent_and_board(tmp_path):
    def respond(request):
        path = request.url.path
        if path == '/us/v0/match-id': return httpx.Response(200, json='m1')
        if path == '/gs/v0/matches/m1': return httpx.Response(200, json=match())
        if path == '/gs/v0/matches/m1/state': return httpx.Response(200, json={'finished': False})
        if path == '/gs/v0/lobbies': return httpx.Response(200, json=[
            {'id': 'l1', 'host': {'id': 'h', 'name': 'blau'}, 'players': [{'userId': 'own', 'name': 'Mulich', 'isPending': True}]},
            {'id': 'other', 'host': {'id': 'h'}, 'players': [{'userId': 'x', 'name': 'X'}]}])
        raise AssertionError(path)
    svc, _ = service(tmp_path, respond)
    games = asyncio.run(activity.player_activity(svc, 'own'))
    assert [(g['kind'], g['id'], g['opponents'], g['boards']) for g in games] == [
        ('match', 'm1', ['Ly'], ['Rot']), ('lobby', 'l1', [], [])]
    assert games[1]['pending'] and games[1]['host'] == 'blau'


def test_finished_match_is_not_reported(tmp_path):
    def respond(request):
        path = request.url.path
        if path == '/us/v0/match-id': return httpx.Response(200, json='m1')
        if path == '/gs/v0/matches/m1': return httpx.Response(200, json=match())
        if path == '/gs/v0/matches/m1/state': return httpx.Response(200, json={'finished': True})
        if path == '/gs/v0/lobbies': return httpx.Response(200, json=None)
        raise AssertionError(path)
    svc, _ = service(tmp_path, respond)
    assert asyncio.run(activity.player_activity(svc, 'own')) == []


def board_service(tmp_path, *, deny=False, board_match='m1', visible=True, host='rot-id', users=('own',)):
    deleted = []

    def respond(request):
        path, method = request.url.path, request.method
        if path == '/bs/v0/boards':
            if not visible or request.headers['authorization'].split('.')[1] != credentials('own')['access_token'].split('.')[1]:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{'id': ROT, 'matchId': None if deleted else board_match, 'status': 'Running',
                                              'permissions': [{'isOwner': True, 'user': {'id': 'own'}}]}])
        if path == '/gs/v0/matches/m1':
            if method == 'DELETE':
                if deny: return httpx.Response(403)
                deleted.append(path); return httpx.Response(204)
            return httpx.Response(404) if deleted else httpx.Response(200, json=match(host))
        raise AssertionError((method, path))
    svc, calls = service(tmp_path, respond, users)
    return svc, calls, deleted


def test_board_overview_and_abort_deletes_without_surrender(tmp_path):
    svc, calls, deleted = board_service(tmp_path)
    boards = asyncio.run(activity.boards(svc, ['own']))
    rot = next(b for b in boards if b['name'] == 'Rot')
    assert rot['match']['players'] == ['Mulich', 'Ly'] and rot['match']['id'] == 'm1'
    assert not next(b for b in boards if b['name'] == 'Blau')['visible']
    assert asyncio.run(activity.abort_match(svc, ['own'], ROT, 'm1'))['aborted'] == 'm1'
    assert deleted and not any('surrender' in path for _, path in calls)


def test_abort_refuses_changed_match_and_reports_missing_permission(tmp_path):
    svc, calls, deleted = board_service(tmp_path, board_match='other')
    with pytest.raises(SessionError) as error:
        asyncio.run(activity.abort_match(svc, ['own'], ROT, 'm1'))
    assert error.value.code == 'match_changed' and not any(m == 'DELETE' for m, _ in calls)
    svc, _, _ = board_service(tmp_path / 'deny', deny=True)
    with pytest.raises(SessionError) as error:
        asyncio.run(activity.abort_match(svc, ['own'], ROT, 'm1'))
    assert error.value.code == 'abort_not_permitted'


def test_board_account_as_match_host_may_abort(tmp_path):
    svc, _, deleted = board_service(tmp_path, visible=False, host='rot-id', users=('rot-id',))
    assert asyncio.run(activity.abort_match(svc, ['rot-id'], ROT, 'm1'))['aborted'] == 'm1'
    svc, _, deleted = board_service(tmp_path / 'guest', visible=False, host='rot-id', users=('ly',))
    with pytest.raises(SessionError) as error:
        asyncio.run(activity.abort_match(svc, ['ly'], ROT, 'm1'))
    assert error.value.code == 'board_not_visible' and not deleted


def test_lobby_is_deleted_only_by_its_host(tmp_path):
    gone = []

    def respond(request):
        if request.url.path != '/gs/v0/lobbies/l1': raise AssertionError(request.url.path)
        if request.method == 'DELETE':
            gone.append(1); return httpx.Response(204)
        return httpx.Response(404) if gone else httpx.Response(200, json={'id': 'l1', 'host': {'id': 'rot-id'}, 'players': []})
    svc, _ = service(tmp_path, respond, users=('own', 'rot-id'))
    with pytest.raises(SessionError) as error:
        asyncio.run(activity.abort_lobby(svc, ['own'], 'l1'))
    assert error.value.code == 'lobby_host_not_signed_in' and not gone
    assert asyncio.run(activity.abort_lobby(svc, ['own', 'rot-id'], 'l1'))['aborted'] == 'l1'


def test_id_log_keeps_ids_once_and_survives_restart(tmp_path):
    log = activity.IdLog(tmp_path / 'ids.json', limit=3)
    game = {'kind': 'match', 'id': 'm1', 'host': 'rot', 'players': ['Mulich', 'Ly']}
    log.note('gesehen', game, account='mulich'); log.note('gesehen', game, account='mulich')
    log.note('abgebrochen', game, board='Rot')
    again = activity.IdLog(tmp_path / 'ids.json', limit=3)
    assert [e['event'] for e in again.entries] == ['gesehen', 'abgebrochen']
    for i in range(5):
        again.note('gesehen', {**game, 'id': f'x{i}'})
    assert len(json.loads((tmp_path / 'ids.json').read_text())) == 3


def test_password_and_code_login_adopt_tokens_without_storing_credentials(tmp_path):
    seen = []

    def respond(request):
        body = json.loads(request.content or b'{}')
        seen.append((request.url.path, body))
        if request.url.path == '/auth/v1/login':
            if body.get('password') != 'pw': return httpx.Response(401, json={'error': {'code': 'invalid'}})
            return httpx.Response(200, json=credentials('rot-id'))
        if request.url.path == '/auth/v1/login/otp': return httpx.Response(204)
        if request.url.path == '/auth/v1/login/otp/verify': return httpx.Response(200, json=credentials('blau-id'))
        if request.url.path == '/auth/v1/account/me':
            return httpx.Response(200, json={'id': 'rot-id'})
        raise AssertionError(request.url.path)
    svc, _ = service(tmp_path, respond, users=())
    with pytest.raises(SessionError) as error:
        asyncio.run(svc.credential_login('a', '/auth/v1/login', {'username': 'rot', 'password': 'bad'}))
    assert error.value.code == 'login_rejected' and not svc.store.read('a')
    assert asyncio.run(svc.credential_login('a', '/auth/v1/login', {'username': 'rot', 'password': 'pw'}))
    saved = json.dumps(svc.store.read('a'))
    assert 'rot-id' in saved and '"pw"' not in saved and 'password' not in saved
    assert all(b.get('client_id') == 'autodarts-play' for p, b in seen if p.startswith('/auth/v1/login'))
    assert asyncio.run(svc.credential_login('b', '/auth/v1/login/otp', {'email': 'b@example.test'})) is False
    with pytest.raises(SessionError):
        asyncio.run(svc.credential_login('b', '/auth/v1/register', {}))
