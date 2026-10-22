"""Move selected paused Autodarts logins into the local HTTP test container.

Run on the MacBook. Secret payloads are piped in memory via SSH/docker stdin;
they are never printed, passed as command-line arguments or written on the Mac.
Only the refresh-token localStorage entry is extracted. No browser profiles,
cookies or passwords are imported into the destination.
"""
import argparse
import json
import shlex
import subprocess
import sys
from urllib.request import Request, urlopen


EXPORT = r'''
import asyncio,json,shutil,tempfile,sys
from pathlib import Path
from playwright.async_api import async_playwright
names=json.loads(sys.argv[1]);data=Path('/data')
players=json.loads((data/'players.json').read_text())
selected=[]
for name in names:
 matches=[p for p in players if p['name'].casefold()==name.casefold()]
 if len(matches)!=1:raise SystemExit('Spielername fehlt oder ist mehrdeutig')
 if not matches[0].get('paused'):raise SystemExit('Quellsitzung muss zuerst pausiert werden')
 selected.append(matches[0])
async def run():
 result=[]
 async with async_playwright() as runtime:
  for p in selected:
   suffix='-autodarts' if p.get('browser')=='chrome' else ''
   source=data/'profiles'/(p['id']+suffix)/'Default'/'Local Storage'
   if not source.exists():raise SystemExit('Gespeicherte Anmeldung nicht gefunden')
   with tempfile.TemporaryDirectory(prefix='portal-auth-transfer-') as temp:
    target=Path(temp)/'Default'/'Local Storage';target.parent.mkdir(parents=True)
    shutil.copytree(source,target)
    context=await runtime.chromium.launch_persistent_context(temp,headless=True,
      service_workers='block',args=['--disable-background-networking'])
    try:
     await context.route('**/*',lambda route:route.fulfill(status=200,body='<html></html>',content_type='text/html'))
     page=context.pages[-1] if context.pages else await context.new_page()
     await page.goto('https://play.autodarts.com/',wait_until='domcontentloaded')
     refresh=await page.evaluate("localStorage.getItem('autodarts_refresh_token')")
     if not isinstance(refresh,str) or not refresh:raise SystemExit('Erneute Anmeldung erforderlich')
     result.append({'name':p['name'],'refresh_token':refresh})
    finally:await context.close()
 return result
print(json.dumps(asyncio.run(run())))
'''

IMPORT = r'''
import json,sys,uuid
from pathlib import Path
from app.http_sessions import SessionStore
data=Path('/data');registry=data/'players.json'
players=json.loads(registry.read_text()) if registry.exists() else []
rows=json.load(sys.stdin);store=SessionStore(data/'http-sessions')
for row in rows:
 if any(p['name'].casefold()==row['name'].casefold() for p in players):raise SystemExit('Zielaccount existiert bereits; nichts überschrieben')
 if not row.get('refresh_token'):raise SystemExit('Anmeldung unvollständig')
for row in rows:
 ident=str(uuid.uuid4())
 store.save(ident,{'refresh_token':row['refresh_token']})
 players.append({'id':ident,'name':row['name'],'auto_accept':False})
temp=registry.with_suffix('.tmp');temp.write_text(json.dumps(players));temp.replace(registry)
print(str(len(rows))+' Anmeldungen importiert. Einladungsannahme bleibt zunächst aus.')
'''


def migrate(args):
    # Never continue automatically after unknown/changed SSH host keys.
    # A human can enter the SSH password in their own terminal (/dev/tty).
    # The password is not passed through this script or sent to the assistant.
    ssh = (['ssh'] + (['-S',args.ssh_control] if args.ssh_control else [])
           + ['-o','ConnectTimeout=8',args.ssh]) if args.ssh else []
    prefix=['pct','exec',str(args.lxc),'--'] if args.lxc else []
    command=prefix+['docker','exec','-i',args.source_container,'python','-',json.dumps(args.names)]
    remote = ssh + [shlex.join(command)] if ssh else command
    if args.pause_source:
        with urlopen(args.source_url+'/api/players',timeout=8) as r:players=json.load(r)
        ids=[]
        for name in args.names:
            matches=[p for p in players if p['name'].casefold()==name.casefold()]
            if len(matches)!=1:raise RuntimeError('Spielername fehlt oder ist mehrdeutig')
            ids.append(matches[0]['id'])
        for ident in ids:
            req=Request(args.source_url+'/api/players/'+ident+'/stop',data=b'{}',method='POST',
                        headers={'Origin':args.source_url,'Content-Type':'application/json'})
            with urlopen(req,timeout=15) as r:r.read()
    exported=subprocess.run(remote,input=EXPORT.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if exported.returncode:
        raise RuntimeError('Export fehlgeschlagen. SSH-Vertrauen, Quellcontainer und pausierte Profile prüfen.')
    # Validate everything before pausing/restarting the isolated destination.
    payload=json.loads(exported.stdout)
    if len(payload)!=len(args.names):raise RuntimeError('Anzahl der Anmeldungen nicht bestätigt')
    imported=subprocess.run(['docker','exec','-i',args.target_container,'python','-c',IMPORT],
        input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
    if imported.returncode:raise RuntimeError('Import fehlgeschlagen. Zielcontainer und vorhandene Accounts prüfen.')
    print(imported.stdout.decode().strip())
    subprocess.run(['docker','restart',args.target_container],check=True,stdout=subprocess.DEVNULL)
    print('Lokaler Testcontainer neu gestartet. Quellsitzungen bleiben pausiert.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh',help='z. B. root@192.168.178.137; Hostschlüssel vorher prüfen')
    parser.add_argument('--ssh-control',help='Vorhandener SSH-ControlMaster-Socket, kein Passwort')
    parser.add_argument('--lxc',type=int,help='Proxmox-Container, z. B. 137')
    parser.add_argument('--source-container',required=True)
    parser.add_argument('--target-container',default='dartportal-http-test-portal-1')
    parser.add_argument('--source-url',default='http://192.168.178.137:18080')
    parser.add_argument('--pause-source',action='store_true',help='Nur genannte Quellaccounts vor der Übernahme pausieren')
    parser.add_argument('names',nargs='+',help='Exakte Anzeigenamen im Quellportal, z. B. Muli und Die Rote')
    try:migrate(parser.parse_args())
    except Exception as error:
        # Do not print subprocess output, payloads, responses or exceptions with tokens.
        print('Migration nicht abgeschlossen: '+(str(error) if isinstance(error,RuntimeError) else type(error).__name__),file=sys.stderr)
        sys.exit(1)
