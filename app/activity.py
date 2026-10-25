"""Read account and board status; abort a board match like the classic board manager.

Aborting uses the native match delete (frontend "Abbrechen"), never surrender, so the
match is removed instead of being scored. Autodarts allows it for the match host and
for accounts with permissions on the board.
"""
import json
import time

from app.http_sessions import BOARDS, SessionError, segment

BOARD_NAMES = {ident: name.capitalize() for name, ident in BOARDS.items()}


def player_name(row):
    user = row.get('user') if isinstance(row.get('user'), dict) else {}
    return str(row.get('name') or user.get('name') or '?')


def describe(kind, game, own=None):
    if not isinstance(game, dict) or not game.get('id'):
        raise SessionError('unknown_game_state')
    rows = game.get('players') or []
    if not isinstance(rows, list):
        raise SessionError('unknown_game_state')
    rows = [p for p in rows if isinstance(p, dict)]
    me = next((p for p in rows if own and p.get('userId') == own), None)
    boards = {p.get('boardId') for p in rows} | {game.get('boardId')}
    return {'kind': kind, 'id': segment(str(game['id'])),
            'host': (game.get('host') or {}).get('name'),
            'players': [player_name(p) for p in rows],
            'opponents': [player_name(p) for p in rows if p is not me],
            'boards': sorted(BOARD_NAMES[b] for b in boards if b in BOARD_NAMES),
            'pending': bool(me and me.get('isPending')),
            'variant': game.get('variant'), 'created_at': game.get('createdAt')}


async def player_activity(service, ident):
    account = service.account(ident)
    result = []
    active = await account.request('GET', '/us/v0/match-id')
    if active not in (None, ''):
        if not isinstance(active, str):
            raise SessionError('unknown_match_state')
        path = '/gs/v0/matches/' + segment(active)
        match = await account.request('GET', path, missing=True)
        state = await account.request('GET', path + '/state', missing=True) if match else None
        if match and not (isinstance(state, dict) and state.get('finished') is True):
            result.append(describe('match', match, account.user_id))
    lobbies = await account.request('GET', '/gs/v0/lobbies') or []
    if not isinstance(lobbies, list):
        raise SessionError('unknown_lobby_list')
    for lobby in lobbies:
        if isinstance(lobby, dict) and any(isinstance(p, dict) and p.get('userId') == account.user_id
                                           for p in lobby.get('players') or []):
            result.append(describe('lobby', lobby, account.user_id))
    return result


async def board_rows(account):
    rows = await account.request('GET', '/bs/v0/boards') or []
    if not isinstance(rows, list):
        raise SessionError('unknown_board_list')
    return {row['id']: row for row in rows if isinstance(row, dict) and row.get('id') in BOARD_NAMES}


def is_owner(row, user):
    return any(isinstance(p, dict) and p.get('isOwner') and (p.get('user') or {}).get('id') == user
               for p in row.get('permissions') or [])


async def boards(service, idents):
    found = {}
    for ident in idents:
        account = service.account(ident)
        for board, row in (await board_rows(account)).items():
            owner = is_owner(row, account.user_id)
            if board not in found or owner and not found[board]['owner']:
                found[board] = {'row': row, 'account': account, 'owner': owner}
    result = []
    for board, name in BOARD_NAMES.items():
        entry = found.get(board)
        if not entry:
            result.append({'id': board, 'name': name, 'visible': False, 'match': None})
            continue
        row, match = entry['row'], None
        if row.get('matchId'):
            info = await entry['account'].request('GET', '/gs/v0/matches/' + segment(row['matchId']), missing=True)
            match = describe('match', info) if info else {'kind': 'match', 'id': segment(row['matchId']),
                                                         'host': None, 'players': [], 'boards': [name]}
        result.append({'id': board, 'name': name, 'visible': True, 'status': row.get('status'),
                       'match': match})
    return result


async def abort_match(service, idents, board, match):
    if board not in BOARD_NAMES:
        raise SessionError('unknown_board')
    path = '/gs/v0/matches/' + segment(match)
    accounts = [service.account(ident) for ident in idents]
    rows = {account.ident: (await board_rows(account)).get(board) for account in accounts}
    if any(row and row.get('matchId') != match for row in rows.values()):
        raise SessionError('match_changed')
    visible = any(rows.values())
    denied = False
    # Board permission (classic board manager) first, then the match host (board account).
    for account in sorted(accounts, key=lambda a: not rows[a.ident]):
        if not rows[account.ident]:
            info = await account.request('GET', path, missing=True)
            if not isinstance(info, dict) or (info.get('host') or {}).get('id') != account.user_id:
                continue
        try:
            await account.request('DELETE', path, missing=True)
        except SessionError as error:
            if error.status in (401, 403):
                denied = True
                continue
            raise
        if await account.request('GET', path, missing=True) is not None:
            raise SessionError('abort_not_confirmed')
        return {'aborted': match, 'board': BOARD_NAMES[board], 'account': account.username}
    raise SessionError('abort_not_permitted' if denied or visible else 'board_not_visible')


async def abort_lobby(service, idents, lobby):
    path = '/gs/v0/lobbies/' + segment(lobby)
    found = False
    for ident in idents:
        account = service.account(ident)
        info = await account.request('GET', path, missing=True)
        if info is None:
            continue
        found = True
        if (info.get('host') or {}).get('id') != account.user_id:
            continue
        await account.request('DELETE', path, missing=True)
        if await account.request('GET', path, missing=True) is not None:
            raise SessionError('abort_not_confirmed')
        return {'aborted': lobby, 'host': account.username}
    raise SessionError('lobby_host_not_signed_in' if found else 'lobby_not_found')


class IdLog:
    """Keep seen Autodarts lobby/match IDs for later troubleshooting."""

    def __init__(self, path, limit=500):
        self.path, self.limit = path, limit
        self.entries = json.loads(path.read_text()) if path.exists() else []
        self.seen = {(e['kind'], e['id'], e.get('account')) for e in self.entries}

    def note(self, event, game, account=None, board=None):
        key = (game['kind'], game['id'], account)
        if event == 'gesehen' and key in self.seen:
            return
        self.seen.add(key)
        self.entries.append({'at': time.time(), 'event': event, 'kind': game['kind'], 'id': game['id'],
                             'account': account, 'board': board, 'host': game.get('host'),
                             'players': game.get('players', [])})
        del self.entries[:-self.limit]
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.entries, ensure_ascii=False))
        temp.replace(self.path)
