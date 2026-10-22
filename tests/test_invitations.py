import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.invitations import AutoAcceptor, sender_allowed, joined


INVITE = {'id': 'notice-1', 'sender': 'Rot', 'sender_id': 'user-rot', 'lobby_id': 'lobby-1'}


class Buttons:
    def __init__(self, buttons):
        self.buttons = buttons

    async def count(self):
        return len(self.buttons)

    def nth(self, index):
        return self.buttons[index]


def setup(invites=None, busy=False, enabled=True, hosts=None, confirmed=True):
    item = {'id': 'player', 'auto_accept': enabled}
    page = SimpleNamespace(url='https://play.autodarts.com/',
        evaluate=AsyncMock(return_value={'invites': invites if invites is not None else [INVITE], 'busy': busy}))
    async def scan(script):
        in_lobby = '/lobby/' in page.url
        return {'invites':invites if invites is not None else [INVITE],'busy':busy or in_lobby,
                'path':'/lobby/lobby-1' if in_lobby else '/',
                'lobby':{'id':'lobby-1','host_id':'user-rot','players':[{'user_id':'own-account','pending':not confirmed}]} if in_lobby else None}
    page.evaluate.side_effect = scan
    async def clicked(**kwargs):
        page.url = 'https://play.autodarts.com/lobby/lobby-1'
    button = SimpleNamespace(get_attribute=AsyncMock(return_value='notice-1'),
        is_visible=AsyncMock(return_value=True), click=AsyncMock(side_effect=clicked))
    page.locator = lambda selector: Buttons([button] if 'data-portal-invitation' in selector else [])
    async def wait(predicate, **kwargs):
        if not predicate(page.url):
            raise TimeoutError()
    page.wait_for_url = AsyncMock(side_effect=wait)
    registry = SimpleNamespace(get=lambda ident: item)
    acceptor = AutoAcceptor({'player': SimpleNamespace(pages=[page])}, registry, {},
                            {'hosts': hosts if hosts is not None else ['rot', 'schwarz', 'blau']}, {'player':'own-account'})
    return acceptor, page, button


def test_exact_sender_matching():
    assert sender_allowed(INVITE, ['rot'])
    assert sender_allowed(INVITE, ['user-rot'])
    assert not sender_allowed(INVITE, ['r'])
    assert not sender_allowed({**INVITE, 'sender': 'rot-fake'}, ['rot'])


def test_finished_result_returns_home_then_accepts_next_invitation():
    acceptor, page, button = setup()
    page.url = 'https://play.autodarts.com/history/matches/finished-1'
    original_scan = page.evaluate.side_effect
    async def scan(script):
        if '/history/' in page.url:
            return {'path':'/history/matches/finished-1','busy':False,'invites':[]}
        return await original_scan(script)
    page.evaluate.side_effect = scan
    async def navigate(url, **kwargs):
        page.url = url
    page.goto = AsyncMock(side_effect=navigate)
    acceptor.drawer_checked['player'] = {'url':page.url,'at':0}
    async def check():
        await acceptor.tick('player')
        button.click.assert_not_awaited()
        assert 'player' not in acceptor.drawer_checked
        await acceptor.tick('player')
    asyncio.run(check())
    page.goto.assert_awaited_once_with('https://play.autodarts.com/',
        wait_until='domcontentloaded',timeout=15000)
    button.click.assert_awaited_once()
    assert acceptor.attempts[('player','notice-1')]['done']


def test_return_home_never_leaves_live_or_unknown_pages_or_paused_accounts():
    cases = [('/matches/live',True,True,True),('/lobby/live',True,True,True),
             ('/matches/live',False,True,True),('/',False,True,True),
             ('/history/matches/done',False,False,True),
             ('/history/matches/done',False,True,False),
             ('/history/matches/done',True,True,True)]
    for path,busy,enabled,known in cases:
        acceptor,page,button=setup(invites=[],enabled=enabled)
        page.url='https://play.autodarts.com'+path
        page.evaluate.side_effect=None
        page.evaluate.return_value={'path':path,'busy':busy,'invites':[]}
        page.goto=AsyncMock()
        if not known:
            acceptor.identities.clear()
        asyncio.run(acceptor.tick('player'))
        page.goto.assert_not_awaited()
        button.click.assert_not_awaited()


def test_accept_and_confirm_once():
    acceptor, page, button = setup()
    async def check():
        await acceptor.tick('player')
        await acceptor.tick('player')
    asyncio.run(check())
    button.click.assert_awaited_once()
    assert acceptor.status['player']['last_sender'] == 'Rot'
    assert acceptor.status['player']['last_accepted'] > 0


def test_reject_unknown_busy_disabled_and_missing_hosts():
    for arguments in [{'invites': [{**INVITE, 'sender': 'fremd', 'sender_id': 'other'}]},
                      {'busy': True}, {'enabled': False}, {'hosts': []}]:
        acceptor, page, button = setup(**arguments)
        asyncio.run(acceptor.tick('player'))
        button.click.assert_not_awaited()


def test_unconfirmed_join_is_not_success_and_not_repeated_immediately():
    acceptor, page, button = setup()
    button.click.side_effect = None
    async def check():
        await acceptor.tick('player')
        await acceptor.tick('player')
    asyncio.run(check())
    button.click.assert_awaited_once()
    assert 'last_accepted' not in acceptor.status['player']
    assert 'nicht bestätigt' in acceptor.status['player']['message']


def test_login_page_and_paused_session_do_not_click():
    acceptor, page, button = setup()
    page.url = 'https://accounts.google.com/'
    asyncio.run(acceptor.tick('player'))
    button.click.assert_not_awaited()
    acceptor.contexts.clear()
    asyncio.run(acceptor.tick('player'))
    assert acceptor.status['player']['message'] == 'Sitzung ist pausiert'


def test_open_lobby_is_not_accepted_and_late_confirmation_is_observed(monkeypatch):
    acceptor, page, button = setup(confirmed=False)
    async def no_delay(*args):
        return None
    monkeypatch.setattr('app.invitations.asyncio.sleep',no_delay)
    asyncio.run(acceptor.tick('player'))
    assert 'last_accepted' not in acceptor.status['player']
    assert not acceptor.attempts[('player','notice-1')]['done']
    asyncio.run(acceptor.tick('player'))
    button.click.assert_awaited_once()
    assert 'ausstehend' in acceptor.status['player']['message']
    page.evaluate.side_effect = None
    page.evaluate.return_value = {'busy':True,'invites':[],'path':'/lobby/lobby-1',
        'lobby':{'id':'lobby-1','host_id':'user-rot','players':[{'user_id':'own-account','pending':False}]}}
    asyncio.run(acceptor.tick('player'))
    assert acceptor.attempts[('player','notice-1')]['done']
    assert acceptor.status['player']['last_accepted'] > 0
    button.click.assert_awaited_once()


def test_join_confirmation_requires_exact_lobby_host_account_and_pending_flag():
    snapshot={'path':'/lobby/lobby-1','lobby':{'id':'lobby-1','host_id':'user-rot','players':[{'user_id':'own','pending':False}]}}
    assert joined(snapshot,INVITE,'own')
    assert not joined(snapshot,INVITE,'someone-else')
    assert not joined({**snapshot,'path':'/lobby/other'},INVITE,'own')
    for change in [{'id':'other'},{'host_id':'other'},{'players':[{'user_id':'own','pending':True}]},
                   {'players':[{'user_id':'own'}]},{'players':[{'user_id':'own','pending':False}]*2}]:
        assert not joined({**snapshot,'lobby':{**snapshot['lobby'],**change}},INVITE,'own')
    match={'path':'/matches/lobby-1','match':{'id':'lobby-1','players':[{'user_id':'own'}]}}
    assert joined(match,INVITE,'own')
    assert not joined({**match,'match':{**match['match'],'id':'unrelated-match'}},INVITE,'own')


def test_notification_opener_loading_late_is_not_permanently_skipped(monkeypatch):
    acceptor, page, _ = setup(invites=[])
    now = [100.0]
    monkeypatch.setattr('app.invitations.time.monotonic', lambda: now[0])
    async def check():
        await acceptor.tick('player')
        assert 'player' not in acceptor.drawer_checked
        async def attribute(name):
            return 'Benachrichtigungen öffnen' if name == 'aria-label' else 'false'
        opener = SimpleNamespace(get_attribute=AsyncMock(side_effect=attribute),
            is_visible=AsyncMock(return_value=True), inner_text=AsyncMock(return_value=''),click=AsyncMock())
        page.locator = lambda selector: Buttons([opener])
        await acceptor.tick('player')
        opener.click.assert_awaited_once()
        await acceptor.tick('player')
        opener.click.assert_awaited_once()
        now[0] += 16
        await acceptor.tick('player')
        opener.click.assert_awaited_once()  # No unread badge: leave closed.
        opener.inner_text.return_value = '1'
        await acceptor.tick('player')
        assert opener.click.await_count == 2
        await acceptor.tick('player')
        assert opener.click.await_count == 2  # Cooldown, not repeated toggling.
    asyncio.run(check())


def test_open_notification_drawer_is_never_toggled_closed_and_friends_are_skipped(monkeypatch):
    acceptor, page, _ = setup(invites=[])
    clock = [100.0]
    monkeypatch.setattr('app.invitations.time.monotonic',lambda:clock[0])
    async def attributes(name):
        return 'Open notifications' if name=='aria-label' else 'true'
    friends = SimpleNamespace(get_attribute=AsyncMock(return_value='Friends and notifications'),click=AsyncMock())
    opener = SimpleNamespace(get_attribute=AsyncMock(side_effect=attributes),is_visible=AsyncMock(return_value=True),
        inner_text=AsyncMock(return_value='1'),click=AsyncMock())
    page.locator = lambda selector: Buttons([friends,opener])
    async def check():
        await acceptor.tick('player')
        clock[0] += 16
        await acceptor.tick('player')
    asyncio.run(check())
    friends.click.assert_not_awaited()
    opener.click.assert_not_awaited()
