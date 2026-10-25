import os
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="dartkeller-test-")

import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    main.registry = main.Registry(tmp_path / "players.json")
    main.contexts.clear()
    main.account_identities.clear()
    main.locks.clear()
    main.errors.clear()
    main.starting.clear()
    main.activation_inflight.clear()
    monkeypatch.setattr(main, 'automation_settings', {'hosts': ['rot', 'schwarz', 'blau']})
    monkeypatch.setattr(main, "DATA", tmp_path)
    page = SimpleNamespace(url="https://play.autodarts.com/", goto=AsyncMock(),
        screenshot=AsyncMock(return_value=b"test-image"),
        mouse=SimpleNamespace(click=AsyncMock(), move=AsyncMock(), wheel=AsyncMock()),
        keyboard=SimpleNamespace(insert_text=AsyncMock(), press=AsyncMock()))
    launch = AsyncMock(side_effect=lambda *a, **k: SimpleNamespace(pages=[page], close=AsyncMock(), on=lambda *args: None))
    runtime = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch), stop=AsyncMock())
    monkeypatch.setattr(main, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=runtime)))
    with TestClient(main.app) as c:
        c.page = page
        c.launch = launch
        yield c


ORIGIN = {"origin": "http://testserver"}


def test_saved_http_session_starts_without_launching_browser_and_hides_secrets(client):
    from app import main
    from app.http_sessions import HttpAccount
    import base64,json
    p=client.post('/api/players',json={'name':'HTTP User'},headers=ORIGIN).json()
    payload=base64.urlsafe_b64encode(json.dumps({'sub':'own','preferred_username':'HTTP User'}).encode()).decode().rstrip('=')
    main.http_service.account(p['id']).install({'access_token':'header.'+payload+'.sig',
        'refresh_token':'must-not-be-public','expires_in':300})
    async def wait(ident):
        await asyncio.sleep(60)
    main.http_service.run=wait
    assert client.post('/api/players/'+p['id']+'/start',headers=ORIGIN).status_code==200
    client.launch.assert_not_awaited()
    result=client.get('/api/players').json()[0]
    assert result['status']=='running' and not result['browser_open']
    assert result['http_session']['authenticated']
    assert 'must-not-be-public' not in str(client.get('/api/players').json())
    assert 'must-not-be-public' not in str(client.get('/api/players/'+p['id']+'/automation-diagnostics').json())
    assert client.post('/api/players/'+p['id']+'/stop',headers=ORIGIN).status_code==200
    assert not main.http_service.summary(p['id'])['active']


def test_emergency_recovery_only_targets_exact_accounts_and_is_idempotent(client):
    ids = []
    pages = []
    for name in ['Alias A', 'Alias B', 'Unrelated']:
        player = client.post('/api/players', json={'name':name}, headers=ORIGIN).json()
        main.registry.get(player['id'])['auto_accept'] = True
        ids.append(player['id'])
        page = SimpleNamespace(url='https://play.autodarts.com/lobby/old-lobby',
                               evaluate=AsyncMock(return_value={'busy':True,'invites':[]}))
        async def navigate(url, p=page, **kwargs):
            p.url = url
        page.goto = AsyncMock(side_effect=navigate)
        pages.append(page)
        main.contexts[player['id']] = SimpleNamespace(pages=[page], close=AsyncMock())
        main.account_identities[player['id']] = 'user-'+str(len(ids))
    payload = {'operation_id':'7f547e3b-86c4-47ca-9c9c-749527e691ee', 'board_account':'blau',
               'lobby_id':'old-lobby','user_ids':['user-1','user-2']}
    url = '/api/automation/lobby-recovery'
    assert client.post(url, json=payload, headers=ORIGIN).status_code == 200
    main.account_identities.clear()  # An acknowledged retry must not touch a new match/session.
    assert client.post(url, json=payload, headers=ORIGIN).status_code == 200
    for page in pages[:2]:
        page.goto.assert_awaited_once_with(main.AUTODARTS,wait_until='domcontentloaded',timeout=15000)
    pages[2].goto.assert_not_awaited()
    assert client.post(url,json={**payload,'user_ids':['user-3']},headers=ORIGIN).status_code == 409


def test_emergency_recovery_refuses_unknown_accounts_or_other_live_game(client):
    p = client.post('/api/players', json={'name':'A'}, headers=ORIGIN).json()
    main.registry.get(p['id'])['auto_accept'] = True
    page = SimpleNamespace(url='https://play.autodarts.com/matches/live-game',
        evaluate=AsyncMock(return_value={'busy':True,'invites':[]}),goto=AsyncMock())
    main.contexts[p['id']] = SimpleNamespace(pages=[page], close=AsyncMock())
    payload = {'operation_id':'7f547e3b-86c4-47ca-9c9c-749527e691ee','board_account':'blau',
               'lobby_id':'old-lobby','user_ids':['user-1']}
    assert client.post('/api/automation/lobby-recovery',json=payload,headers=ORIGIN).status_code == 409
    main.account_identities[p['id']] = 'user-1'
    assert client.post('/api/automation/lobby-recovery',json=payload,headers=ORIGIN).status_code == 409
    page.goto.assert_not_awaited()
    page.url = 'https://play.autodarts.com/matches/imported-completed-game'
    async def navigate(url, **kwargs):
        page.url = url
    page.goto.side_effect = navigate
    assert client.post('/api/automation/lobby-recovery',json={**payload,'completed_match_ids':['imported-completed-game']},headers=ORIGIN).status_code == 200


def test_direct_access_and_origin(client):
    assert client.get('/').status_code == 200
    assert client.get('/api/players').status_code == 200
    assert client.get('/login', follow_redirects=False).headers['location'] == '/'
    assert client.post('/api/players', json={'name': 'A'}, headers={'origin': 'http://evil.test'}).status_code == 403
    with pytest.raises(Exception):
        with client.websocket_connect('/ws/nope', headers={'origin': 'http://evil.test'}):
            pass


def test_isolated_profiles_and_persistence(client):
    a = client.post("/api/players", json={"name": "Anna"}, headers=ORIGIN).json()
    b = client.post("/api/players", json={"name": "Ben"}, headers=ORIGIN).json()
    for p in [a, b]:
        assert client.post(f'/api/players/{p["id"]}/start', headers=ORIGIN).status_code == 200
    paths = [call.args[0] for call in client.launch.call_args_list]
    assert len(set(paths)) == 2
    assert main.Registry(main.registry.path).items == [a, b]
    assert all(p["status"] == "running" for p in client.get("/api/players").json())
    assert client.post(f'/api/players/{a["id"]}/stop', headers=ORIGIN).status_code == 200
    assert b["id"] in main.contexts
    profile = main.DATA / "profiles" / a["id"]
    profile.mkdir(parents=True)
    (profile / "cookie").write_text("test")
    assert client.delete(f'/api/players/{a["id"]}', headers=ORIGIN).status_code == 200
    assert not profile.exists()
    assert main.registry.items == [b]


def test_screen_input(client):
    p = client.post("/api/players", json={"name": "Anna"}, headers=ORIGIN).json()
    client.post(f'/api/players/{p["id"]}/start', headers=ORIGIN)
    with client.websocket_connect(f'/ws/{p["id"]}', headers=ORIGIN) as ws:
        assert ws.receive_json()["type"] == "frame"
        ws.send_json({"type": "click", "x": 300, "y": 400})
        ws.send_json({"type": "text", "text": "Hallo"})
        ws.receive_json()
        client.page.mouse.click.assert_awaited_with(300.0, 400.0)
        client.page.keyboard.insert_text.assert_awaited_with("Hallo")


def test_validation(client):
    assert client.post("/api/players", json={"name": " "}, headers=ORIGIN).status_code == 400
    assert client.post("/api/players/unknown/start", headers=ORIGIN).status_code == 404


def test_legacy_desktop_profile_uses_fresh_chromium(client):
    item = {'id': 'legacy', 'name': 'Alt', 'browser': 'chrome'}
    main.registry.items.append(item)
    old = main.DATA / 'profiles' / 'legacy'
    old.mkdir(parents=True)
    (old / 'existing').write_text('preserved')
    assert client.post('/api/players/legacy/start', headers=ORIGIN).status_code == 200
    assert client.launch.call_args.args[0] == str(main.DATA / 'profiles/legacy-autodarts')
    assert 'channel' not in client.launch.call_args.kwargs
    assert (old / 'existing').read_text() == 'preserved'
    assert client.post('/api/players/legacy/native-login', headers=ORIGIN).status_code == 404


def test_automation_configuration(client):
    p = client.post('/api/players', json={'name': 'Anna'}, headers=ORIGIN).json()
    path = f'/api/players/{p["id"]}/auto-accept'
    assert client.get('/api/automation').json()['hosts'] == ['rot', 'schwarz', 'blau']
    assert client.put(path, json={'enabled': True}, headers=ORIGIN).status_code == 200
    assert main.Registry(main.registry.path).get(p['id'])['auto_accept'] is True
    assert client.put('/api/automation', json={'hosts': []}, headers=ORIGIN).status_code == 200
    assert client.put(path, json={'enabled': True}, headers=ORIGIN).status_code == 400
    assert client.put('/api/automation', json={'hosts': [' rot ', 'rot', 'blau']}, headers=ORIGIN).json()['hosts'] == ['rot', 'blau']
    assert (main.DATA / 'automation.json').exists()
    assert client.put(path, json={'enabled': False}, headers=ORIGIN).status_code == 200


def test_production_board_script_links_hidden_in_test_portal(client):
    html = client.get('/').text
    assert 'HTTP-TEST' in html
    boards = {'blau':'faa2cd5f-5d19-4e68-9749-1b7b95c753d4',
              'rot':'ad381dc0-7e86-45a1-9fa8-61c8b18ec89b',
              'schwarz':'6e390006-cdba-4ac5-b0bb-0e03eb880af6'}
    for name, ident in boards.items():
        url = f'/static/turnier-{name}.user.js'
        response = client.get(url)
        assert response.status_code == 200
        assert url not in html
        assert ident in response.text
        assert 'http://dartturnier.hausi' in response.text
        assert f'http://dartportal.hausi{url}' in response.text


def test_shared_tournament_board_script_download(client):
    response=client.get('/static/turnier-board.user.js')
    assert response.status_code == 200
    assert 'function identifyBoard()' in response.text
    assert 'http://dartportal.hausi/static/turnier-board.user.js' in response.text


def test_tournament_activates_only_matching_existing_sessions_and_pause_is_durable(client):
    anna = client.post('/api/players',json={'name':'Anna-Account'},headers=ORIGIN).json()
    other = client.post('/api/players',json={'name':'Other'},headers=ORIGIN).json()
    body = {'tournament_id':'56fd5829-c4ec-46d8-837f-bf3e92f2e97f',
            'players':[{'name':'Anna','account_name':'anna-account'},{'name':'Missing','account_name':'missing'}]}
    url = '/api/automation/tournament-sessions'
    assert client.post(url,json=body).status_code == 403
    response = client.post(url,json=body,headers=ORIGIN)
    assert response.status_code == 202
    assert [p['status'] for p in response.json()['players']] == ['scheduled','missing']
    for _ in range(20):
        if client.get('/api/players').json()[0]['status'] == 'running': break
    assert anna['id'] in main.contexts and other['id'] not in main.contexts
    assert main.registry.get(anna['id'])['auto_accept'] is True
    launches = client.launch.call_count
    assert client.post('/api/players/pause-all',headers=ORIGIN).status_code == 200
    assert not main.contexts
    assert all(p['paused'] for p in main.Registry(main.registry.path).items)
    asyncio.run(main.restore())
    assert not main.contexts and client.launch.call_count == launches
    # A duplicate delivery of this same tournament must not undo All paused.
    again = client.post(url,json=body,headers=ORIGIN).json()
    assert again['players'][0]['status'] == 'already_requested'
    assert not main.contexts
    assert client.post('/api/players/pause-all',headers=ORIGIN).status_code == 200
    assert client.post(f"/api/players/{anna['id']}/start",headers=ORIGIN).status_code == 200
    assert anna['id'] in main.contexts
    assert 'id="pause-all"' in client.get('/').text


def test_pause_all_waits_for_inflight_start_then_closes_it(client):
    p = client.post('/api/players',json={'name':'Anna'},headers=ORIGIN).json()
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        async def navigate(*args, **kwargs):
            entered.set()
            await release.wait()
        client.page.goto.side_effect = navigate
        launch = asyncio.create_task(main.start_player(p['id']))
        await entered.wait()
        pause = asyncio.create_task(main.pause_all())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(launch,pause)
        assert p['id'] not in main.contexts
        assert main.registry.get(p['id'])['paused'] is True
    asyncio.run(exercise())


def test_tournament_session_duplicates_are_not_guessed(client):
    for _ in range(2): client.post('/api/players',json={'name':'Same'},headers=ORIGIN)
    response = client.post('/api/automation/tournament-sessions',headers=ORIGIN,json={
        'tournament_id':'56fd5829-c4ec-46d8-837f-bf3e92f2e97f','players':[{'name':'Same','account_name':'Same'}]})
    assert response.json()['players'][0]['status'] == 'ambiguous'
    assert not main.contexts


def test_invitation_diagnostics_are_read_only_and_do_not_include_credentials(client):
    player = client.post('/api/players',json={'name':'Diagnostic'},headers=ORIGIN).json()
    path = f"/api/players/{player['id']}/automation-diagnostics"
    assert client.get(path).json()['running'] is False
    assert client.get('/api/players/unknown/automation-diagnostics').status_code == 404
    page = SimpleNamespace(url='https://play.autodarts.com/?private=do-not-include',evaluate=AsyncMock(side_effect=[
        {'busy':False,'path':'/','invites':[],'private':'do-not-include'},
        [{'label':'Benachrichtigungen öffnen','text':'1','expanded':'false','disabled':False}]
    ]))
    main.contexts[player['id']] = SimpleNamespace(pages=[page],close=AsyncMock())
    main.account_identities[player['id']] = 'private-user-id'
    response = client.get(path)
    assert response.status_code == 200
    data = response.json()
    assert data['identity_known'] and data['scan']['busy'] is False
    assert data['buttons'][0]['text'] == '1'
    assert data['invitation_revision'] == client.get('/health').json()['invitation_revision']
    assert 'do-not-include' not in response.text and 'private-user-id' not in response.text
    assert 'authorization' not in response.text.lower()
