"""Browserless Autodarts sessions. Native HTTP + message-broker protocol.

Refresh tokens live only in the private data volume, never in API responses.
No browser callbacks, DOM selectors, password storage or guessed user IDs.
"""
import asyncio
import base64
import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
from websockets.asyncio.client import connect

API = 'https://api.autodarts.com'
BROKER = 'https://play.ws.autodarts.com/ms/v0'
ORIGIN = 'https://play.autodarts.com'
BOARDS = {
    'blau': 'faa2cd5f-5d19-4e68-9749-1b7b95c753d4',
    'rot': 'ad381dc0-7e86-45a1-9fa8-61c8b18ec89b',
    'schwarz': '6e390006-cdba-4ac5-b0bb-0e03eb880af6',
}


class SessionError(Exception):
    """Deliberately excludes URLs, response bodies and authentication values."""
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)


def claims(token):
    try:
        part = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
    except (ValueError, IndexError, TypeError):
        raise SessionError('invalid_login') from None


def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w-]{1,100}', value, flags=re.ASCII):
        raise SessionError('invalid_identifier')
    return value


class SessionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def path(self, ident):
        return self.root / (segment(ident) + '.json')

    def read(self, ident):
        path = self.path(ident)
        return json.loads(path.read_text()) if path.exists() else None

    def save(self, ident, data):
        path = self.path(ident)
        temp = path.with_suffix('.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)

    def delete(self, ident):
        self.path(ident).unlink(missing_ok=True)


class HttpAccount:
    def __init__(self, ident, store, client=None):
        self.ident, self.store = ident, store
        self.saved = store.read(ident) or {}
        self.user_id = self.saved.get('user_id')
        self.username = self.saved.get('username')
        self.access = None
        self.redirects = []
        self.expires = 0
        self.refresh_lock = asyncio.Lock()
        self.client = client or httpx.AsyncClient(
            timeout=15, follow_redirects=False, headers={'Origin': ORIGIN})

    async def close(self):
        await self.client.aclose()

    def persist(self):
        self.store.save(self.ident, self.saved)

    def install(self, response):
        access, refresh = response.get('access_token'), response.get('refresh_token')
        if not isinstance(access, str) or not isinstance(refresh, str) or not refresh:
            raise SessionError('invalid_login')
        info = claims(access)
        user = info.get('sub')
        name = info.get('preferred_username')
        if not isinstance(user, str) or not isinstance(name, str) or not user or not name:
            raise SessionError('invalid_login')
        if self.user_id and self.user_id != user:
            raise SessionError('account_changed')
        self.user_id, self.username = user, name
        self.access = access
        seconds = response.get('expires_in', 0)
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            raise SessionError('invalid_login')
        self.expires = time.monotonic() + seconds
        # Persist a rotated refresh token before making another request.
        self.saved.update(user_id=user, username=name, refresh_token=refresh)
        self.persist()

    async def raw(self, method, url, **kwargs):
        try:
            for _ in range(4):
                response = await self.client.request(method, url, **kwargs)
                if response.status_code not in (301,302,303,307,308):
                    return response
                target = urljoin(url,response.headers.get('location',''))
                parsed = urlsplit(target)
                if (parsed.scheme!='https' or parsed.netloc!=urlsplit(url).netloc
                        or parsed.username or parsed.password
                        or (method not in ('GET','HEAD') and response.status_code in (301,302,303))):
                    raise SessionError('unsafe_redirect')
                redirect={'from':urlsplit(url).path,'to':parsed.path}
                if redirect not in self.redirects:
                    self.redirects.append(redirect)
                url=target
            raise SessionError('too_many_redirects')
        except httpx.HTTPError:
            raise SessionError('network') from None

    async def refresh(self, rejected=None):
        async with self.refresh_lock:
            if self.access and self.expires > time.monotonic() + 30 and (
                    rejected is None or self.access != rejected):
                return
            refresh = self.saved.get('refresh_token')
            if not refresh:
                raise SessionError('login_required')
            response = await self.raw('POST', API + '/auth/v1/refresh', json={
                'refresh_token': refresh, 'client_id': 'autodarts-play'})
            if response.status_code in (400, 401):
                raise SessionError('login_required', response.status_code)
            if response.status_code != 200:
                raise SessionError('refresh_failed', response.status_code)
            try:
                self.install(response.json())
            except ValueError:
                raise SessionError('invalid_login') from None

    async def request(self, method, path, *, data=None, missing=False, broker=False):
        await self.refresh()
        base = BROKER if broker else API
        for retry in range(2):
            access = self.access
            response = await self.raw(method, base + path,
                headers={'Authorization': 'Bearer ' + access},
                **({'json': data} if data is not None else {}))
            if response.status_code == 401 and not retry:
                await self.refresh(rejected=access)
                continue
            if response.status_code == 404 and missing:
                return None
            if not 200 <= response.status_code < 300:
                raise SessionError('http_error', response.status_code)
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                raise SessionError('invalid_response') from None

    async def verify_identity(self):
        own = await self.request('GET', '/auth/v1/account/me')
        if not isinstance(own, dict) or own.get('id') != self.user_id:
            raise SessionError('identity_not_confirmed')


class HttpSessions:
    def __init__(self, registry, settings, data, *, client_factory=None, connector=connect):
        self.registry, self.settings = registry, settings
        self.store = SessionStore(Path(data) / 'http-sessions')
        self.accounts, self.tasks, self.status, self.connected = {}, {}, {}, set()
        self.client_factory, self.connector = client_factory, connector
        self.locks = {}

    def account(self, ident):
        if ident not in self.accounts:
            client = self.client_factory() if self.client_factory else None
            self.accounts[ident] = HttpAccount(ident, self.store, client)
        return self.accounts[ident]

    def report(self, ident, message, **extra):
        self.status[ident] = {**self.status.get(ident, {}), 'message': message, **extra}

    def summary(self, ident):
        account = self.accounts.get(ident)
        saved = account.saved if account else self.store.read(ident)
        return {'authenticated': bool(saved and saved.get('refresh_token')),
                'account_name': saved.get('username') if saved else None,
                'transport_connected': ident in self.connected,
                'active': ident in self.tasks and not self.tasks[ident].done(),
                'automation': self.status.get(ident, {}), 'mode': 'http',
                'api_redirects':list(account.redirects) if account else []}

    async def adopt(self, ident, tokens):
        await self.stop(ident)
        account = self.account(ident)
        account.install(tokens)
        await account.verify_identity()
        self.report(ident, 'Anmeldung übernommen – HTTP-Sitzung bereit')

    async def credential_login(self, ident, path, body):
        """Native HTTP login (password or e-mail code). Credentials are never stored or logged."""
        if path not in ('/auth/v1/login', '/auth/v1/login/otp', '/auth/v1/login/otp/verify'):
            raise SessionError('invalid_login')
        response = await self.account(ident).raw('POST', API + path, json={**body, 'client_id': 'autodarts-play'})
        if response.status_code == 429:
            raise SessionError('login_rate_limited', 429)
        if 400 <= response.status_code < 500:
            raise SessionError('login_rejected', response.status_code)
        if not 200 <= response.status_code < 300:
            raise SessionError('http_error', response.status_code)
        if path == '/auth/v1/login/otp':
            return False
        try:
            tokens = response.json()
        except ValueError:
            raise SessionError('invalid_response') from None
        await self.adopt(ident, tokens)
        return True

    async def start(self, ident):
        item = self.registry.get(ident)
        if not item or item.get('paused'):
            return False
        if not self.store.read(ident):
            return False
        if ident not in self.tasks or self.tasks[ident].done():
            self.tasks[ident] = asyncio.create_task(self.run(ident))
        return True

    async def stop(self, ident):
        task = self.tasks.pop(ident, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.connected.discard(ident)

    async def close(self):
        await asyncio.gather(*(self.stop(i) for i in list(self.tasks)))
        await asyncio.gather(*(a.close() for a in self.accounts.values()))
        self.accounts.clear()

    async def run(self, ident):
        account = self.account(ident)
        wake = asyncio.Event()
        async def poll():
            while True:
                try:
                    await self.tick(ident)
                except SessionError as error:
                    messages = {'login_required': 'Anmeldung abgelaufen – erneut anmelden',
                        'account_changed': 'Accountwechsel erkannt – Anmeldung prüfen',
                        'network': 'Verbindung unterbrochen – erneuter Versuch',
                        'identity_not_confirmed': 'Account konnte nicht bestätigt werden'}
                    self.report(ident, messages.get(error.code, 'Autodarts-Antwort nicht bestätigt'),
                                error=error.code, http_status=error.status)
                except Exception:
                    self.report(ident, 'HTTP-Sitzung nicht bereit – erneuter Versuch', error='unexpected')
                try:
                    await asyncio.wait_for(wake.wait(), 8)
                except asyncio.TimeoutError:
                    pass
                wake.clear()
        tasks = [asyncio.create_task(poll()), asyncio.create_task(self.presence(account, wake))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.connected.discard(ident)

    async def presence(self, account, wake):
        retry = 0
        while True:
            try:
                ticket = await account.request('POST', '/tickets', broker=True)
                if not isinstance(ticket, dict) or not isinstance(ticket.get('code'), str):
                    raise SessionError('invalid_ticket')
                url = BROKER.replace('https:', 'wss:') + '/subscribe?' + urlencode({'code': ticket['code']})
                async with self.connector(url, origin=ORIGIN, ping_interval=20,
                                          ping_timeout=20, max_size=2**20) as ws:
                    for channel, topic in [('autodarts.notifications', account.user_id),
                                           ('autodarts.friends', account.user_id + '.status'),
                                           ('autodarts.users', account.user_id + '.events')]:
                        await ws.send(json.dumps({'type': 'subscribe', 'channel': channel, 'topic': topic}))
                    self.connected.add(account.ident)
                    retry = 0
                    wake.set()
                    # Reconnect periodically with a fresh ticket; HTTP refreshes tokens.
                    async with asyncio.timeout(240):
                        async for raw in ws:
                            event = json.loads(raw)
                            if event.get('type') == 'error':
                                raise SessionError('subscription_rejected')
                            if event.get('channel') == 'autodarts.notifications':
                                wake.set()  # Fetch canonical notifications via authenticated HTTP.
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Never log websocket URLs/tickets, frames or auth responses.
            finally:
                self.connected.discard(account.ident)
            retry += 1
            await asyncio.sleep(min(30, 2**min(retry, 5)) + random.random())

    async def busy(self, account, target):
        active = await account.request('GET', '/us/v0/match-id')
        if active not in (None, ''):
            if not isinstance(active, str):
                raise SessionError('unknown_match_state')
            segment(active)
            state = await account.request('GET', '/gs/v0/matches/' + active + '/state')
            if not isinstance(state, dict) or state.get('finished') is not True:
                return True
        lobbies = await account.request('GET', '/gs/v0/lobbies')
        if lobbies is None:
            lobbies = []  # Native getLobbies() also normalizes null to [].
        if not isinstance(lobbies, list):
            raise SessionError('unknown_lobby_list')
        for lobby in lobbies:
            if not isinstance(lobby, dict):
                raise SessionError('unknown_lobby_list')
            players = lobby.get('players') or []
            if not isinstance(players, list):
                raise SessionError('unknown_lobby_players')
            if lobby.get('id') != target and any(p.get('userId') == account.user_id
                    and p.get('isPending') is False for p in players):
                return True
        return False

    async def local_membership(self, account, path, invite):
        lobby = await account.request('GET', path, missing=True)
        if lobby is not None:
            return self.confirmed(self.own(lobby, account.user_id), invite)
        # Board scripts can start the match immediately after acceptance.
        match = await account.request('GET', '/gs/v0/matches/' + invite['lobby'], missing=True)
        if not isinstance(match, dict) or match.get('host', {}).get('id') != invite['host']:
            return False
        row = self.own(match, account.user_id)
        return bool(row and row.get('isPending') is not True
                    and row.get('hostId') == invite['host'] and row.get('boardId') == invite['board'])

    def invitation(self, notice):
        if not isinstance(notice, dict) or notice.get('type') != 'lobby:invite':
            return None
        body = notice.get('body', {})
        sender, lobby = body.get('user', {}), body.get('lobby', {})
        host = str(sender.get('name', '')).casefold()
        allowed = {s.strip().casefold() for s in self.settings.get('hosts', [])}
        mappings = {**BOARDS, **self.settings.get('boards', {})}
        board = mappings.get(host)
        if host not in allowed or not board:
            return None
        return {'id': segment(notice.get('id')), 'lobby': segment(lobby.get('id')),
                'host': segment(sender.get('id')), 'sender': sender['name'], 'board': segment(board)}

    @staticmethod
    def own(lobby, user):
        if not isinstance(lobby, dict) or 'players' not in lobby:
            raise SessionError('unknown_lobby_state')
        players = lobby['players'] if lobby['players'] is not None else []
        if not isinstance(players, list):
            raise SessionError('unknown_lobby_state')
        rows = [p for p in players if p.get('userId') == user]
        if len(rows) > 1:
            raise SessionError('ambiguous_player')
        return rows[0] if rows else None

    @staticmethod
    def confirmed(row, invite):
        return bool(row and row.get('isPending') is False
                    and row.get('hostId') == invite['host'] and row.get('boardId') == invite['board'])

    @staticmethod
    def host_boards(lobby, host):
        # The native board selector uses userId OR hostId. A board account can
        # host local players without being listed as a player itself.
        players = lobby.get('players') or []
        if not isinstance(players, list):
            raise SessionError('unknown_lobby_players')
        return sorted({p['boardId'] for p in players if isinstance(p, dict)
                       and (p.get('userId') == host or p.get('hostId') == host)
                       and not p.get('cpuPPR') and p.get('boardId')})

    async def tick(self, ident):
        async with self.locks.setdefault(ident, asyncio.Lock()):
            item = self.registry.get(ident)
            if not item or item.get('paused'):
                return
            account = self.account(ident)
            await account.verify_identity()
            if not item.get('auto_accept'):
                self.report(ident, 'HTTP-Verbindung aktiv – Annahme aus', error=None)
                return
            notices = await account.request('GET', '/as/v0/notifications')
            if not isinstance(notices, list):
                raise SessionError('unknown_notifications')
            # Normal native joins may consume the notification before the board
            # script links the player. Keep checking this confirmed membership.
            notice_ids = {n.get('id') for n in notices if isinstance(n, dict)}
            for key, receipt in account.saved.get('receipts', {}).items():
                invite = receipt.get('invite')
                if receipt.get('accepted') and not receipt.get('done') and invite and key not in notice_ids:
                    notices.append({'id':key, 'type':'lobby:invite', 'body':{
                        'user':{'id':invite['host'], 'name':invite['sender']},
                        'lobby':{'id':invite['lobby']}}})
            observations = []
            self.report(ident, 'Wartet auf Lobby-Einladung per HTTP', error=None,
                        sender=None, lobby_id=None, http_status=None,
                        expected_board=None, observed_host_boards=[], actual_board=None, actual_host=None,
                        stage='notifications', checked_at=time.time(), invitations=observations)
            for notice in notices:
                invite = self.invitation(notice)
                if invite:
                    observation = {k: invite[k] for k in ('id', 'lobby', 'sender', 'board')}
                    observations.append(observation)
                    self.report(ident, 'Prüft Lobby-Einladung', sender=invite['sender'],
                                lobby_id=invite['lobby'], error=None, http_status=None,
                                stage='lobby', expected_board=invite['board'], observed_host_boards=[],
                                actual_board=None, actual_host=None)
                    try:
                        await self.accept(ident, account, item, invite)
                    except SessionError as error:
                        self.report(ident, 'Einladung konnte nicht bestätigt werden',
                                    error=error.code, http_status=error.status)
                        receipt = account.saved.get('receipts', {}).get(invite['id'])
                        if receipt is not None:
                            receipt.update(error=error.code, http_status=error.status,
                                           stage=self.status[ident].get('stage'))
                            account.persist()
                    observation.update({k: self.status[ident].get(k) for k in
                                        ('message', 'stage', 'error', 'http_status', 'observed_host_boards')})
                    # Inspect remaining invitations even if this one is expired,
                    # already joined, waiting for its board or rejected by the API.
                    if item.get('paused') or not item.get('auto_accept'):
                        break

    async def accept(self, ident, account, item, invite):
        path = '/gs/v0/lobbies/' + invite['lobby']
        lobby = await account.request('GET', path, missing=True)
        if lobby is None:
            self.report(ident, 'Einladung abgelaufen – Lobby existiert nicht mehr')
            receipt = account.saved.get('receipts', {}).get(invite['id'])
            if receipt:
                receipt.update(done=True, expired=True)
                account.persist()
            return
        if (lobby.get('id') != invite['lobby'] or lobby.get('host', {}).get('id') != invite['host']
                or lobby.get('isPrivate') is not True or lobby.get('tournamentId')):
            raise SessionError('lobby_not_allowed')
        boards = self.host_boards(lobby, invite['host'])
        self.report(ident, 'Prüft lokale Scheibe des Gastgebers',
                    stage='host_board', observed_host_boards=boards)
        if boards and boards != [invite['board']]:
            raise SessionError('host_board_not_confirmed')
        row = self.own(lobby, account.user_id)
        receipts = account.saved.setdefault('receipts', {})
        if not self.confirmed(row, invite):
            if row and row.get('isPending') is False:
                self.report(ident, 'Bereits beigetreten, lokale Zuordnung noch nicht bestätigt',
                            stage='membership', error='local_assignment_required',
                            actual_board=row.get('boardId'), actual_host=row.get('hostId'))
                return
            if await self.busy(account, invite['lobby']):
                self.report(ident, 'Anderes Match oder andere Lobby aktiv – wartet auf Abschluss')
                return
            previous = receipts.get(invite['id'], {})
            if time.time() - previous.get('at', 0) < 30:
                self.report(ident, 'Beitritt wird geprüft – wartet vor erneutem Versuch',
                            stage=previous.get('stage','join_with_host'), error=previous.get('error'),
                            http_status=previous.get('http_status'))
                return
            # Re-read before writing: a paused/disabled session must not accept late.
            if not item.get('auto_accept') or item.get('paused') or not self.invitation({
                    'id':invite['id'], 'type':'lobby:invite', 'body':{'user':{
                    'id':invite['host'],'name':invite['sender']},'lobby':{'id':invite['lobby']}}}):
                return
            fresh = await account.request('GET', path, missing=True)
            if not fresh or fresh.get('host', {}).get('id') != invite['host']:
                raise SessionError('lobby_changed')
            fresh_boards = self.host_boards(fresh, invite['host'])
            if (fresh.get('isPrivate') is not True or fresh.get('tournamentId')
                    or (fresh_boards and fresh_boards != [invite['board']])):
                raise SessionError('lobby_changed')
            current_board = {**BOARDS, **self.settings.get('boards', {})}.get(invite['sender'].casefold())
            if (not item.get('auto_accept') or item.get('paused') or current_board != invite['board']
                    or invite['sender'].casefold() not in {h.strip().casefold() for h in self.settings.get('hosts', [])}):
                return
            row = self.own(fresh, account.user_id)
            if not self.confirmed(row, invite):
                receipts[invite['id']] = {'at': time.time(), 'done': False, 'lobby': invite['lobby'],
                                         'invite':invite}
                if len(receipts) > 100:
                    del receipts[next(iter(receipts))]
                account.persist()
                self.report(ident, 'Nimmt Einladung per HTTP lokal an', sender=invite['sender'],
                            stage='join_with_host')
                # Native /join/:id?hostId=... uses this endpoint and no boardId body.
                # The service assigns the authenticated player to this host's board.
                try:
                    await account.request('POST', path + '/players/with-host/' + invite['host'], data={
                        'name': account.username, 'userId': account.user_id})
                except SessionError as error:
                    # Native join-with-host needs an existing host player. If the
                    # board script removed that dummy, use the normal native join.
                    # Only the authenticated board host can link the guest locally.
                    if error.code != 'http_error' or error.status != 404:
                        raise
                    current = await account.request('GET', path, missing=True)
                    if (not current or current.get('id') != invite['lobby']
                            or current.get('host',{}).get('id') != invite['host']
                            or current.get('isPrivate') is not True or current.get('tournamentId')
                            or self.own(current, invite['host']) is not None):
                        raise
                    if item.get('paused') or not item.get('auto_accept'):
                        return
                    current_board = {**BOARDS, **self.settings.get('boards',{})}.get(invite['sender'].casefold())
                    if (current_board != invite['board'] or invite['sender'].casefold()
                            not in {h.strip().casefold() for h in self.settings.get('hosts',[])}):
                        return
                    current_row = self.own(current, account.user_id)
                    if not current_row or current_row.get('isPending') is not False:
                        self.report(ident, 'Nimmt Einladung an – Board-Script übernimmt lokale Zuordnung',
                                    stage='join_without_host_player')
                        await account.request('POST', path + '/players', data={
                            'name':account.username, 'userId':account.user_id})
                    joined = await account.request('GET', path, missing=True)
                    row = self.own(joined, account.user_id) if joined else None
                    if row and row.get('isPending') is False:
                        receipts[invite['id']]['accepted'] = True
                        account.persist()
            self.report(ident, 'Prüft Beitritt und lokale Board-Zuordnung', stage='membership')
            for _ in range(8):
                if await self.local_membership(account, path, invite):
                    break
                await asyncio.sleep(0.25)
            else:
                self.report(ident, 'HTTP-Beitritt oder lokale Zuordnung nicht bestätigt')
                return
        receipts[invite['id']] = {'at':time.time(), 'done':True, 'lobby':invite['lobby']}
        account.persist()
        self.report(ident, 'HTTP-Beitritt und lokales Board bestätigt',
                    last_accepted=time.time(), last_sender=invite['sender'],
                    lobby_id=invite['lobby'], board_id=invite['board'], error=None,
                    http_status=None, stage='confirmed')
        # Dismiss only this lobby notification, after confirmed local membership.
        await account.request('DELETE', '/as/v0/notifications/' + invite['id'], missing=True)
