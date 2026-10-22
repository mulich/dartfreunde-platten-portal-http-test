"""Read current Autodarts React notifications; use the site's own join button.

The notification structure and lobby:invite type were verified against the public
Autodarts frontend on 2026-10-03. Unknown structures fail closed.
"""
import asyncio
import re
import time
from urllib.parse import urlsplit

SCAN = r"""() => {
  const invites = new Map();
  document.querySelectorAll('[data-portal-invitation]').forEach(el => delete el.dataset.portalInvitation);
  let finished = null;
  let lobbyState = null, matchState = null;
  const players = list => list.map(p => ({user_id:p.userId || p.user?.id || null, pending:p.isPending}));
  const currentFiber = el => {
    const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
    let fiber = key ? el[key] : null;
    const root = node => {let n=node;while(n?.return)n=n.return;return n;};
    const top = root(fiber);
    if(top?.stateNode?.current && top.stateNode.current!==top) {
      const alternate = fiber?.alternate;
      return root(alternate)===top.stateNode.current ? alternate : null;
    }
    return fiber;
  };
  const visible = el => !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  for (const el of document.querySelectorAll('button, main, [role="main"]')) {
    let fiber = currentFiber(el);
    let notification = null;
    for (let depth=0; fiber && depth<80; depth++, fiber=fiber.return) {
      const props = fiber.memoizedProps;
      for(const value of [props?.lobby,props?.value]) {
        if(value?.id && value.host?.id && Array.isArray(value.players) && typeof value.isPrivate==='boolean')
          lobbyState={id:value.id,host_id:value.host.id,players:players(value.players)};
      }
      const game=props?.value;
      if(game?.match?.id && game.state && Array.isArray(game.state.players))
        matchState={id:game.match.id,players:players(game.state.players)};
      if (props?.value?.state && typeof props.value.state.finished === 'boolean')
        finished = props.value.state.finished;
      const n = props?.notification;
      if (n?.type === 'lobby:invite' && n.id && n.body?.user && n.body?.lobby?.id)
        notification = n;
    }
    if (el.tagName !== 'BUTTON' || !visible(el) || el.disabled || !notification) continue;
    const label = (el.textContent || '').trim();
    if (!/^(accept|join|annehmen|akzeptieren|beitreten)$/i.test(label)) continue;
    const n = notification;
    el.dataset.portalInvitation = n.id;
    if (!invites.has(n.id)) invites.set(n.id, {
      id: String(n.id), sender: String(n.body.user.name || ''),
      sender_id: String(n.body.user.id || ''), lobby_id: String(n.body.lobby.id)
    });
  }
  const match = /^\/(match|matches)(\/|$)/.test(location.pathname);
  const lobby = /^\/lobby(\/|$)/.test(location.pathname);
  return {invites: [...invites.values()], busy: lobby || (match && finished !== true), path:location.pathname, lobby:lobbyState, match:matchState};
}"""


def sender_allowed(invite, hosts):
    allowed = {value.strip().casefold() for value in hosts if value.strip()}
    return any(str(invite.get(key, '')).strip().casefold() in allowed
               for key in ('sender', 'sender_id') if invite.get(key))


def joined(snapshot, invite, user_id):
    if not user_id:
        return False
    path = snapshot.get('path', '').rstrip('/')
    lobby = snapshot.get('lobby')
    if path == '/lobby/' + invite['lobby_id'] and lobby and lobby.get('id') == invite['lobby_id'] and lobby.get('host_id') == invite['sender_id']:
        own = [p for p in lobby.get('players', []) if p.get('user_id') == user_id]
        return len(own) == 1 and own[0].get('pending') is False
    match = snapshot.get('match')
    if path in ('/match/'+invite['lobby_id'], '/matches/'+invite['lobby_id']) and match and match.get('id') == invite['lobby_id']:
        own = [p for p in match.get('players', []) if p.get('user_id') == user_id]
        return len(own) == 1 and own[0].get('pending') is not True
    return False


class AutoAcceptor:
    def __init__(self, contexts, registry, locks, settings, identities=None):
        self.contexts, self.registry = contexts, registry
        self.locks, self.settings = locks, settings
        self.status = {}
        self.attempts = {}
        self.drawer_checked = {}
        self.identities = identities if identities is not None else {}
        self.awaiting = {}

    def confirm(self, ident, invite, attempt):
        attempt['done'] = True
        self.awaiting.pop(ident, None)
        self.report(ident, 'Lobby-Beitritt bestätigt', sender=invite['sender'],
                    last_accepted=time.time(), last_sender=invite['sender'], lobby_id=invite['lobby_id'])

    def report(self, ident, message, **extra):
        self.status[ident] = {**self.status.get(ident, {}), 'message': message, **extra}

    async def tick(self, ident):
        item = self.registry.get(ident)
        if not item or not item.get('auto_accept'):
            self.awaiting.pop(ident, None)
            self.drawer_checked.pop(ident, None)
            self.report(ident, 'Automatik aus')
            return
        hosts = self.settings.get('hosts', [])
        if not hosts:
            self.report(ident, 'Bitte Board-Accounts freigeben')
            return
        context = self.contexts.get(ident)
        if not context or not context.pages:
            self.report(ident, 'Sitzung ist pausiert')
            return
        page = context.pages[-1]
        if urlsplit(page.url).netloc != 'play.autodarts.com':
            self.report(ident, 'Wartet auf Autodarts-Anmeldung')
            return
        snapshot = await asyncio.wait_for(page.evaluate(SCAN), timeout=5)
        pending = self.awaiting.get(ident)
        if pending:
            invite, attempt, account = pending
            if self.identities.get(ident) != account or not sender_allowed(invite, hosts):
                self.awaiting.pop(ident, None)
                self.report(ident, 'Account oder Freigabe geändert – Beitritt nicht bestätigt')
                return
            if joined(snapshot, invite, account):
                self.confirm(ident, invite, attempt)
                return
            if urlsplit(page.url).path.rstrip('/') == '/lobby/' + invite['lobby_id']:
                self.report(ident, 'Lobby geöffnet, Beitritt noch ausstehend – Spieleransicht prüfen', sender=invite['sender'])
                # Retry only a still-visible native invitation for this exact lobby.
                snapshot['invites'] = [n for n in snapshot['invites'] if n['id'] == invite['id'] and n['lobby_id'] == invite['lobby_id']]
                if not snapshot['invites']:
                    return
            else:
                self.awaiting.pop(ident, None)
                pending = None
        if snapshot['busy'] and not pending:
            self.report(ident, 'In Lobby oder Match – wartet auf Abschluss')
            return
        # Autodarts moves finished matches to this read-only result route.
        # It has no notification drawer; waiting there misses the next invite.
        # Never leave an active /matches/ or /lobby/ page to find invitations.
        path = urlsplit(page.url).path
        if (not snapshot['busy'] and not snapshot['invites']
                and re.fullmatch(r'/history/matches/[^/]+/?', path)
                and self.identities.get(ident) and item.get('auto_accept')):
            self.report(ident, 'Spiel beendet – öffnet Startseite für nächste Einladung')
            await page.goto('https://play.autodarts.com/',
                            wait_until='domcontentloaded', timeout=15000)
            self.drawer_checked.pop(ident, None)
            return
        checked = self.drawer_checked.get(ident)
        drawer_due = not checked or checked['url'] != page.url or time.monotonic() - checked['at'] >= 15
        if not snapshot['invites'] and drawer_due:
            # Wait for the native opener to exist before recording a check.
            # Later unread invitations may arrive at the same URL after a toast
            # has disappeared; reopen for those, without toggling an open drawer.
            button = page.locator('button[aria-label]')
            for index in range(await button.count()):
                candidate = button.nth(index)
                label = (await candidate.get_attribute('aria-label') or '').casefold()
                if ('notification' in label or 'benachrichtigung' in label) and not any(
                    word in label for word in ('close', 'schließen', 'dismiss', 'friend', 'freunde')):
                    if not await candidate.is_visible():
                        continue
                    expanded = await candidate.get_attribute('aria-expanded') == 'true'
                    first_check = not checked or checked['url'] != page.url
                    count = (await candidate.inner_text()).strip()
                    unread = any(c.isdigit() for c in count) and count != '0'
                    if expanded or first_check or unread:
                        if not expanded:
                            await candidate.click(timeout=2000)
                        self.drawer_checked[ident] = {'url': page.url, 'at': time.monotonic()}
                    break
            self.report(ident, 'Wartet auf Lobby-Einladung')
            return
        if not snapshot['invites']:
            self.report(ident, 'Wartet auf Lobby-Einladung')
            return
        for invite in snapshot['invites']:
            if not sender_allowed(invite, hosts):
                self.report(ident, 'Einladung ignoriert: Absender nicht freigegeben', sender=invite['sender'])
                continue
            account = self.identities.get(ident)
            if not account:
                self.report(ident, 'Account nicht erkannt – Autodarts-Sitzung neu laden und anmelden')
                return
            key = (ident, invite['id'])
            previous = self.attempts.get(key)
            if previous and (previous['done'] or previous['count'] >= 3 or time.monotonic() - previous['at'] < 30):
                continue
            attempt = {'at': time.monotonic(), 'count': previous['count'] + 1 if previous else 1, 'done': False}
            self.attempts[key] = attempt
            if len(self.attempts) > 512:
                self.attempts.pop(next(iter(self.attempts)))
            # Recheck config just before the write; disabling a player takes effect
            # even if an earlier scan was already in flight.
            if not item.get('auto_accept') or not sender_allowed(invite, self.settings.get('hosts', [])):
                return
            buttons = page.locator('button[data-portal-invitation]')
            target = None
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                if await button.get_attribute('data-portal-invitation') == invite['id'] and await button.is_visible():
                    target = button
                    break
            if target is None:
                continue
            self.report(ident, 'Nimmt Einladung an …', sender=invite['sender'])
            try:
                if not item.get('auto_accept') or not sender_allowed(invite, self.settings.get('hosts', [])):
                    return
                fresh = await asyncio.wait_for(page.evaluate(SCAN), timeout=5)
                if fresh['busy'] and not (pending and urlsplit(page.url).path.rstrip('/') == '/lobby/' + invite['lobby_id']):
                    return
                if self.identities.get(ident) != account or not any(n['id'] == invite['id'] and n['lobby_id'] == invite['lobby_id'] and sender_allowed(n, self.settings.get('hosts', [])) for n in fresh['invites']):
                    return
                if await target.get_attribute('data-portal-invitation') != invite['id']:
                    return
                self.awaiting[ident] = (invite, attempt, account)
                await target.click(timeout=3000)
                # Navigation alone does not mean the invited player was accepted.
                # Read committed native participant state; never invoke React callbacks.
                deadline = time.monotonic() + 6
                for _ in range(24):
                    if not item.get('auto_accept') or self.identities.get(ident) != account or not sender_allowed(invite, self.settings.get('hosts', [])):
                        return
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    verified = await asyncio.wait_for(page.evaluate(SCAN), timeout=min(5, remaining))
                    if self.identities.get(ident) != account:
                        return
                    if joined(verified, invite, account):
                        self.confirm(ident, invite, attempt)
                        return
                    await asyncio.sleep(min(0.25, max(0, deadline-time.monotonic())))
                self.report(ident, 'Beitritt nicht bestätigt – bitte Spieleransicht prüfen', sender=invite['sender'])
            except Exception:
                self.report(ident, 'Beitritt nicht bestätigt – bitte Spieleransicht prüfen', sender=invite['sender'])
            # Only one invitation per player per cycle. The next cycle rechecks
            # match state before considering another host.
            return

    async def run(self):
        while True:
            async def check(ident):
                try:
                    async with self.locks.setdefault(ident, asyncio.Lock()):
                        await self.tick(ident)
                except Exception:
                    self.report(ident, 'Ansicht noch nicht bereit – wird erneut geprüft')
            await asyncio.gather(*(check(p['id']) for p in list(self.registry.items)))
            await asyncio.sleep(2)
