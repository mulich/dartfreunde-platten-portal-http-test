import asyncio
import base64
import json
import hashlib
import logging
import os
import uuid
from contextlib import AsyncExitStack
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field
from app.invitations import AutoAcceptor, SCAN
from app import invitations
from app.recovery import observe_account

DATA = Path(os.getenv("DATA_DIR", "data"))
DATA.mkdir(parents=True, exist_ok=True)
STATIC = Path(__file__).parent / "static"
AUTODARTS = "https://play.autodarts.com/"


class Registry:
    def __init__(self, path):
        self.path = path
        self.items = json.loads(path.read_text()) if path.exists() else []

    def save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.items, ensure_ascii=False))
        temp.replace(self.path)

    def get(self, ident):
        return next((item for item in self.items if item["id"] == ident), None)


registry = Registry(DATA / "players.json")
contexts = {}
account_identities = {}
recovery_lock = asyncio.Lock()
locks = {}
starting = set()
errors = {}
playwright = None
SETTINGS_FILE = DATA / 'automation.json'
automation_settings = json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {'hosts': ['rot', 'schwarz', 'blau']}
acceptor = None
activation_tasks = set()
activation_inflight = set()
activation_generation = 0


def player_profile(item):
    # Keep obsolete desktop profiles intact; Chromium must not downgrade them.
    suffix = '-autodarts' if item.get('browser') == 'chrome' else ''
    return DATA / 'profiles' / (item['id'] + suffix)


def player_lock(ident):
    return locks.setdefault(ident, asyncio.Lock())


async def start_player(ident):
    async with player_lock(ident):
        if registry.get(ident) and registry.get(ident).get('paused'):
            return
        if ident in contexts:
            return
        if not registry.get(ident):
            raise HTTPException(404, "Spieler nicht gefunden")
        starting.add(ident)
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(player_profile(registry.get(ident))), headless=True,
                viewport={"width": 1280, "height": 800}, locale="de-DE",
                args=["--disable-background-timer-throttling",
                      "--disable-renderer-backgrounding",
                      "--disable-backgrounding-occluded-windows"],
            )
            contexts[ident] = context
            account_identities.pop(ident, None)
            observe_account(context, ident, account_identities)
            page = context.pages[-1] if context.pages else await context.new_page()
            await page.goto(AUTODARTS, wait_until="domcontentloaded", timeout=60000)
            if registry.get(ident).get('paused'):
                contexts.pop(ident, None)
                await context.close()
                return
            errors.pop(ident, None)
        except BaseException:
            context = contexts.pop(ident, None)
            if context:
                await context.close()
            errors[ident] = "Sitzung konnte nicht gestartet werden. Serververbindung und Browserinstallation prüfen."
            raise
        finally:
            starting.discard(ident)


async def restore():
    # Sequential startup avoids a burst of Chromium processes on small hosts.
    for item in list(registry.items):
        try:
            await start_player(item["id"])
        except Exception:
            logging.warning("Sitzung %s konnte nicht wiederhergestellt werden", item["id"])


@asynccontextmanager
async def lifespan(app):
    global playwright, acceptor
    playwright = await async_playwright().start()
    acceptor = AutoAcceptor(contexts, registry, locks, automation_settings, account_identities)
    task = asyncio.create_task(restore())
    automation_task = asyncio.create_task(acceptor.run())
    yield
    task.cancel()
    automation_task.cancel()
    for pending in list(activation_tasks):
        pending.cancel()
    await asyncio.gather(*activation_tasks, return_exceptions=True)
    await asyncio.gather(task, automation_task, return_exceptions=True)
    await asyncio.gather(*(c.close() for c in contexts.values()), return_exceptions=True)
    await playwright.stop()


app = FastAPI(lifespan=lifespan)


def same_origin(origin, host):
    return bool(origin and urlsplit(origin).netloc == host)


@app.middleware("http")
async def guard(request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not same_origin(request.headers.get("origin"), request.headers.get("host")):
            return HTMLResponse("Ungültiger Ursprung", status_code=403)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "invitation_revision": invitation_revision()}


def invitation_revision():
    return hashlib.sha256(Path(invitations.__file__).read_bytes()).hexdigest()[:16]


@app.get("/login")
async def legacy_login():
    return RedirectResponse("/", status_code=303)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


class Player(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@app.get("/api/players")
async def list_players():
    return [{**p, "status": "starting" if p["id"] in starting else
             "running" if p["id"] in contexts else "stopped",
             "auto_accept": p.get('auto_accept', False),
             "automation": acceptor.status.get(p['id'], {}) if acceptor else {},
             "error": errors.get(p["id"])} for p in registry.items]


@app.get('/api/players/{ident}/automation-diagnostics')
async def automation_diagnostics(ident: str):
    if not registry.get(ident):
        raise HTTPException(404, 'Spieler nicht gefunden')
    result = {'invitation_revision': invitation_revision(),
              'enabled': bool(registry.get(ident).get('auto_accept')),
              'identity_known': bool(account_identities.get(ident)),
              'running': ident in contexts}
    if not result['running']:
        return result
    async with player_lock(ident):
        context = contexts.get(ident)
        if not context or not context.pages:
            return {**result, 'running': False}
        page = context.pages[-1]
        parsed = urlsplit(page.url)
        result['path'] = parsed.path
        if parsed.netloc != 'play.autodarts.com':
            return {**result, 'message': 'Keine Autodarts-Ansicht'}
        try:
            snapshot = await asyncio.wait_for(page.evaluate(SCAN), timeout=5)
            result['scan'] = {key: snapshot.get(key) for key in ('path','busy','invites')}
            # Only visible button labels/counts: never input values, cookies,
            # request headers, tokens, raw React props or browser storage.
            result['buttons'] = await asyncio.wait_for(page.evaluate(r'''() =>
              [...document.querySelectorAll('button')].filter(el =>
                el.getClientRects().length && getComputedStyle(el).visibility!=='hidden')
              .map(el => ({label:(el.getAttribute('aria-label') || '').slice(0,120),
                text:(el.textContent || '').trim().slice(0,80),
                expanded:el.getAttribute('aria-expanded'), disabled:el.disabled}))
              .slice(0,100)
            '''),timeout=5)
        except Exception:
            result['message'] = 'Native Ansicht konnte nicht rechtzeitig gelesen werden'
        if acceptor:
            checked = acceptor.drawer_checked.get(ident)
            result['drawer_check'] = {'path':urlsplit(checked['url']).path,'at':checked['at']} if checked else None
            result['attempts'] = [{'invitation_id':key[1], 'count':value['count'], 'done':value['done']}
                                  for key,value in acceptor.attempts.items() if key[0]==ident][-10:]
    return result


class AutomationSettings(BaseModel):
    hosts: list[str] = Field(max_length=20)


class AutoAcceptSetting(BaseModel):
    enabled: bool


class TournamentParticipant(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    account_name: str = Field(min_length=1, max_length=60)


class TournamentSessions(BaseModel):
    tournament_id: uuid.UUID
    players: list[TournamentParticipant] = Field(max_length=64)


@app.post('/api/automation/tournament-sessions', status_code=202)
async def tournament_sessions(body: TournamentSessions):
    file = DATA / 'tournament-activations.json'
    receipts = json.loads(file.read_text()) if file.exists() else {}
    generation = activation_generation
    targets, results = [], []
    for player in body.players:
        account = player.account_name.strip().casefold()
        key = str(body.tournament_id)+':'+account
        matches = [p for p in registry.items if p['name'].strip().casefold() == account]
        if not matches:
            matches = [p for p in registry.items if p['name'].strip().casefold() == player.name.strip().casefold()]
        if len(matches) != 1 or not account:
            results.append({'name': player.name, 'status': 'ambiguous' if matches else 'missing'})
            continue
        item = matches[0]
        if key in receipts or key in activation_inflight:
            results.append({'name': player.name, 'status': 'already_requested'})
            continue
        item.pop('paused', None)
        item['auto_accept'] = bool(automation_settings.get('hosts'))
        activation_inflight.add(key)
        targets.append((key, item['id']))
        results.append({'name': player.name, 'status': 'scheduled'})
    registry.save()

    async def activate_targets():
        for key, ident in targets:
            try:
                if generation != activation_generation:
                    continue
                await start_player(ident)
                if ident in contexts and generation == activation_generation:
                    saved = json.loads(file.read_text()) if file.exists() else {}
                    saved[key] = True
                    temp = file.with_suffix('.tmp')
                    temp.write_text(json.dumps(saved))
                    temp.replace(file)
            except Exception:
                logging.warning('Turniersitzung %s konnte nicht gestartet werden', ident)
            finally:
                activation_inflight.discard(key)
    if targets:
        task = asyncio.create_task(activate_targets())
        activation_tasks.add(task)
        def completed(task):
            activation_tasks.discard(task)
            for key, _ in targets:
                activation_inflight.discard(key)
        task.add_done_callback(completed)
    return {'players': results}


@app.post('/api/players/pause-all')
async def pause_all():
    global activation_generation
    activation_generation += 1
    file = DATA / 'tournament-activations.json'
    receipts = json.loads(file.read_text()) if file.exists() else {}
    receipts.update({key: True for key in activation_inflight})
    temp = file.with_suffix('.tmp')
    temp.write_text(json.dumps(receipts))
    temp.replace(file)
    for item in registry.items:
        item['paused'] = True
    registry.save()
    failed = []
    for item in list(registry.items):
        async with player_lock(item['id']):
            context = contexts.pop(item['id'], None)
            if context:
                try:
                    await context.close()
                except Exception:
                    contexts[item['id']] = context
                    failed.append(item['id'])
    if failed:
        raise HTTPException(503, 'Einige Sitzungen konnten nicht pausiert werden. Erneut versuchen.')
    return {'paused': len(registry.items)}


class LobbyRecovery(BaseModel):
    operation_id: uuid.UUID
    board_account: str = Field(min_length=1, max_length=100)
    lobby_id: str = Field(min_length=1, max_length=80)
    user_ids: list[str] = Field(max_length=2)
    completed_match_ids: list[str] = Field(default_factory=list, max_length=64)


@app.post('/api/automation/lobby-recovery')
async def recover_lobby(body: LobbyRecovery):
    if body.board_account.casefold() not in {host.casefold() for host in automation_settings.get('hosts', [])}:
        raise HTTPException(409, 'Board-Account in der Accountzentrale nicht freigegeben.')
    users = sorted(set(body.user_ids))
    if any(not user or user.startswith('local:') for user in users):
        raise HTTPException(422, 'Nur echte Autodarts-Accounts zurücksetzen.')
    operation = str(body.operation_id)
    fingerprint = [body.board_account.casefold(), body.lobby_id, users]
    async with recovery_lock:
        file = DATA / 'lobby-recoveries.json'
        receipts = json.loads(file.read_text()) if file.exists() else {}
        receipt = receipts.get(operation, {'fingerprint': fingerprint, 'completed': []})
        if receipt['fingerprint'] != fingerprint:
            raise HTTPException(409, 'Neustart-ID gehört zu einer anderen Lobby.')
        pending = [user for user in users if user not in receipt['completed']]
        targets = {}
        for user in pending:
            matches = [p['id'] for p in registry.items if account_identities.get(p['id']) == user and p['id'] in contexts]
            if len(matches) != 1:
                raise HTTPException(409, 'Betroffener Account nicht eindeutig angemeldet. Spieler-Sitzung in der Accountzentrale öffnen oder neu laden.')
            if not registry.get(matches[0]).get('auto_accept'):
                raise HTTPException(409, 'Automatisches Annehmen beim betroffenen Spieler zuerst einschalten.')
            targets[user] = matches[0]
        async with AsyncExitStack() as stack:
            for ident in sorted(targets.values()):
                await stack.enter_async_context(player_lock(ident))
            pages = {}
            for user, ident in targets.items():
                context = contexts.get(ident)
                if account_identities.get(ident) != user or not context or not context.pages:
                    raise HTTPException(409, 'Spieler-Sitzung inzwischen gewechselt oder pausiert.')
                page = context.pages[-1]
                if urlsplit(page.url).netloc != 'play.autodarts.com':
                    raise HTTPException(409, 'Spieler zuerst bei Autodarts anmelden.')
                snapshot = await asyncio.wait_for(page.evaluate(SCAN), timeout=5)
                path = urlsplit(page.url).path
                completed = {f'/{prefix}/{match}' for match in body.completed_match_ids for prefix in ('match','matches')}
                if snapshot['busy'] and path.rstrip('/') != '/lobby/' + body.lobby_id and path.rstrip('/') not in completed:
                    raise HTTPException(409, 'Spieler ist noch in einem anderen laufenden Match oder einer anderen Lobby. Diese zuerst beenden.')
                pages[user] = page
            for user, page in pages.items():
                ident = targets[user]
                await page.goto(AUTODARTS, wait_until='domcontentloaded', timeout=15000)
                if urlsplit(page.url).netloc != 'play.autodarts.com' or urlsplit(page.url).path != '/':
                    raise HTTPException(409, 'Autodarts-Startseite nicht bestätigt. Anmeldung prüfen.')
                if acceptor:
                    acceptor.drawer_checked.pop(ident, None)
                    acceptor.awaiting.pop(ident, None)
                    acceptor.attempts = {key: value for key, value in acceptor.attempts.items() if key[0] != ident}
                    acceptor.report(ident, 'Lobby-Neustart: wartet auf neue Einladung')
                receipt['completed'].append(user)
                receipts[operation] = receipt
                # Keep receipts across container restarts so a lost response cannot reset a new game.
                temp = file.with_suffix('.tmp')
                temp.write_text(json.dumps(receipts))
                temp.replace(file)
        return {'recovered': users, 'operation_id': operation}


@app.get('/api/automation')
async def get_automation():
    return automation_settings


@app.put('/api/automation')
async def set_automation(settings: AutomationSettings):
    hosts = list(dict.fromkeys(name.strip() for name in settings.hosts if name.strip()))
    if any(len(name) > 100 for name in hosts):
        raise HTTPException(400, 'Accountname ist zu lang')
    automation_settings['hosts'] = hosts
    temp = (DATA / 'automation.json').with_suffix('.tmp')
    temp.write_text(json.dumps(automation_settings, ensure_ascii=False))
    temp.replace(DATA / 'automation.json')
    return automation_settings


@app.put('/api/players/{ident}/auto-accept')
async def set_auto_accept(ident: str, setting: AutoAcceptSetting):
    item = registry.get(ident)
    if not item:
        raise HTTPException(404, 'Spieler nicht gefunden')
    if setting.enabled and not automation_settings.get('hosts'):
        raise HTTPException(400, 'Bitte zuerst Board-Accounts freigeben')
    item['auto_accept'] = setting.enabled
    registry.save()
    if acceptor:
        acceptor.drawer_checked.pop(ident, None)
        acceptor.awaiting.pop(ident, None)
        # Enabling again explicitly allows retrying an invitation which failed.
        acceptor.attempts = {key: value for key, value in acceptor.attempts.items() if key[0] != ident}
        acceptor.report(ident, 'Wartet auf Lobby-Einladung' if setting.enabled else 'Automatik aus')
    return {'enabled': setting.enabled}


@app.post("/api/players")
async def create_player(player: Player):
    name = player.name.strip()
    if not name:
        raise HTTPException(400, "Bitte einen Namen eingeben")
    if len(registry.items) >= 32:
        raise HTTPException(400, "Maximal 32 Sitzungen")
    item = {"id": str(uuid.uuid4()), "name": name}
    registry.items.append(item)
    registry.save()
    return item


@app.post("/api/players/{ident}/start")
async def start(ident: str):
    item = registry.get(ident)
    if item:
        item.pop('paused', None)
        registry.save()
    try:
        await start_player(ident)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, errors.get(ident, "Browser konnte nicht gestartet werden"))
    return {"ok": True}


@app.post("/api/players/{ident}/stop")
async def stop(ident: str):
    if not registry.get(ident):
        raise HTTPException(404, "Spieler nicht gefunden")
    registry.get(ident)['paused'] = True
    registry.save()
    async with player_lock(ident):
        context = contexts.pop(ident, None)
        if context:
            await context.close()
    return {"ok": True}


@app.delete("/api/players/{ident}")
async def delete(ident: str):
    import shutil
    async with player_lock(ident):
        if not registry.get(ident):
            raise HTTPException(404, "Spieler nicht gefunden")
        context = contexts.pop(ident, None)
        if context:
            await context.close()
        registry.items = [p for p in registry.items if p["id"] != ident]
        registry.save()
        shutil.rmtree(DATA / "profiles" / ident, ignore_errors=True)
        shutil.rmtree(DATA / "profiles" / (ident + "-autodarts"), ignore_errors=True)
        shutil.rmtree(DATA / "profiles" / (ident + "-chromium-backup"), ignore_errors=True)
        errors.pop(ident, None)
    return {"ok": True}


@app.websocket("/ws/{ident}")
async def screen(ws: WebSocket, ident: str):
    if not same_origin(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=1008)
        return
    if ident not in contexts:
        await ws.close(code=1008)
        return
    await ws.accept()

    async def frames():
        try:
            while ident in contexts:
                async with player_lock(ident):
                    context = contexts.get(ident)
                    if not context:
                        break
                    page = context.pages[-1] if context.pages else await context.new_page()
                    screenshot = await page.screenshot(type="jpeg", quality=65, timeout=10000)
                    await ws.send_json({"type": "frame", "image": base64.b64encode(screenshot).decode(), "url": page.url})
                await asyncio.sleep(0.7)
        except Exception:
            pass
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    task = asyncio.create_task(frames())
    try:
        while True:
            message = await ws.receive_json()
            async with player_lock(ident):
                context = contexts.get(ident)
                if not context:
                    break
                page = context.pages[-1] if context.pages else await context.new_page()
                kind = message.get("type")
                if kind == "click":
                    await page.mouse.click(max(0, min(1279, float(message["x"]))), max(0, min(799, float(message["y"]))))
                elif kind == "text":
                    await page.keyboard.insert_text(str(message.get("text", ""))[:10000])
                elif kind == "key":
                    await page.keyboard.press(str(message.get("key", ""))[:80])
                elif kind == "scroll":
                    await page.mouse.move(max(0, min(1279, float(message.get("x", 640)))), max(0, min(799, float(message.get("y", 400)))))
                    await page.mouse.wheel(0, max(-2000, min(2000, float(message.get("dy", 0)))))
                elif kind == "home":
                    await page.goto(AUTODARTS, wait_until="domcontentloaded")
                elif kind == "back":
                    await page.go_back(wait_until="domcontentloaded")
                elif kind == "reload":
                    await page.reload(wait_until="domcontentloaded")
    except Exception:
        pass
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        try:
            await ws.close()
        except RuntimeError:
            pass
