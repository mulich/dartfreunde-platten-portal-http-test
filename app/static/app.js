const $=id=>document.getElementById(id);let selected=null, socket=null, players=[], epoch=0, automationConfig={};
function notice(text){$('notice').textContent=text;$('notice').hidden=!text}
async function api(path,method='GET',body){const res=await fetch('/api/'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});if(!res.ok){let data;try{data=await res.json()}catch{}throw Error(data?.detail||'Anfrage fehlgeschlagen')}return res.json()}
async function refresh(){try{players=await api('players');$('count').textContent=players.length;const list=$('players');list.replaceChildren();for(const p of players){const b=document.createElement('button');b.className='player'+(p.id===selected?' selected':'');const icon=document.createElement('span');icon.className='avatar';icon.textContent=p.name.slice(0,2).toUpperCase();const text=document.createElement('span');text.className='player-name';text.textContent=p.name;const status=document.createElement('small');const game=activityText(p.id);status.textContent=game?game:p.status==='running'?(p.http_session?.active?(p.http_session.transport_connected?'● HTTP verbunden':'HTTP verbindet …'):'Anmelde-Browser'):p.status==='starting'?'Wird gestartet …':p.error?'Start fehlgeschlagen':'Pausiert';text.append(status);b.append(icon,text);b.onclick=()=>select(p.id);list.append(b)}renderAutomation();renderHttpSession()}catch(e){notice(e.message)}}
function disconnect(){epoch++;if(socket){socket.onclose=null;socket.close();socket=null}}
async function select(id){disconnect();const current=epoch;selected=id;const p=players.find(p=>p.id===id);$('title').textContent=p?.name||'Spieler';$('empty').hidden=true;renderAutomation();$('viewer').hidden=false;$('frame').removeAttribute('src');$('loading').hidden=false;$('loading').textContent='Sitzung wird geöffnet …';$('connection').textContent='Verbinde …';notice('');refresh();try{await api('players/'+id+'/start','POST');if(current!==epoch)return;await refresh();const active=players.find(p=>p.id===id);if(active?.browser_open)connect(id,current);else renderHttpSession()}catch(e){if(current===epoch){notice(e.message);$('loading').textContent='Start fehlgeschlagen. Spieler erneut auswählen.';$('connection').textContent='Nicht verbunden'}}}
function connect(id,current){socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws/'+id);socket.onmessage=e=>{if(current!==epoch)return;const data=JSON.parse(e.data);if(data.type==='frame'){$('frame').src='data:image/jpeg;base64,'+data.image;$('url').textContent=data.url;$('loading').hidden=true;$('connection').textContent='Sitzung aktiv'}};socket.onclose=()=>{if(current!==epoch)return;$('connection').textContent='Ansicht getrennt';$('loading').hidden=false;$('loading').textContent='Spieler erneut auswählen, um die Ansicht zu verbinden.'};socket.onerror=()=>notice('Die Ansicht konnte nicht verbunden werden. Spieler erneut auswählen.')}
function send(data){if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(data))}
$('add').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const p=await api('players','POST',{name:$('name').value});$('name').value='';await refresh();await select(p.id)}catch(e){notice(e.message)}finally{button.disabled=false}};
function position(e){const box=$('screen').getBoundingClientRect();return{x:(e.clientX-box.left)/box.width*1280,y:(e.clientY-box.top)/box.height*800}}
$('screen').onclick=e=>{$('screen').focus({preventScroll:true});send({type:'click',...position(e)})};
$('screen').addEventListener('wheel',e=>{e.preventDefault();send({type:'scroll',dy:e.deltaY*(e.deltaMode===1?20:e.deltaMode===2?800:1),...position(e)})},{passive:false});
$('screen').onkeydown=e=>{if(e.isComposing)return;const keys={Enter:'Enter',Backspace:'Backspace',Delete:'Delete',Tab:'Tab',Escape:'Escape',ArrowLeft:'ArrowLeft',ArrowRight:'ArrowRight',ArrowUp:'ArrowUp',ArrowDown:'ArrowDown',Home:'Home',End:'End',PageUp:'PageUp',PageDown:'PageDown'};if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='v')return;if(e.ctrlKey||e.metaKey){if(e.key.toLowerCase()==='a'){e.preventDefault();send({type:'key',key:'ControlOrMeta+a'})}return}if(keys[e.key]){e.preventDefault();send({type:'key',key:(e.shiftKey?'Shift+':'')+keys[e.key]})}else if(e.key.length===1){e.preventDefault();send({type:'text',text:e.key})}};
$('screen').onpaste=e=>{e.preventDefault();send({type:'text',text:e.clipboardData.getData('text/plain')})};
$('text-form').onsubmit=e=>{e.preventDefault();send({type:'text',text:$('text').value});$('text').value=''};
for(const name of ['home','back','reload'])$(name).onclick=()=>send({type:name});
$('stop').onclick=async()=>{const id=selected;disconnect();try{await api('players/'+id+'/stop','POST');$('connection').textContent='Pausiert';$('loading').hidden=false;$('loading').textContent='Spieler auswählen, um die Sitzung wieder zu öffnen.';refresh()}catch(e){notice(e.message)}};
$('pause-all').onclick=async()=>{
  const button=$('pause-all');button.disabled=true;
  try{
    await api('players/pause-all','POST');disconnect();selected=null;
    $('viewer').hidden=true;$('empty').hidden=false;renderAutomation();
    $('title').textContent='Alle Sitzungen pausiert';$('connection').textContent='Pausiert';
    notice('Alle Sitzungen pausiert. Gespeicherte Anmeldungen bleiben erhalten.');await refresh();
  }catch(e){notice(e.message);await refresh();}finally{button.disabled=false;}
};
$('delete').onclick=async()=>{const p=players.find(p=>p.id===selected);if(!confirm(`Sitzung von ${p?.name} und gespeicherte Anmeldung dauerhaft entfernen?`))return;const id=selected;disconnect();try{await api('players/'+id,'DELETE');selected=null;renderAutomation();$('viewer').hidden=true;$('empty').hidden=false;$('title').textContent='Alle Accounts. Ein Fenster.';$('connection').textContent='Keine Sitzung ausgewählt';refresh()}catch(e){notice(e.message)}};
refresh();setInterval(refresh,5000);

function renderAutomation(){const p=players.find(p=>p.id===selected);$('automation-panel').hidden=!p;if(!p)return;$('auto-accept').checked=!!p.auto_accept;$('auto-status').textContent=p.auto_accept?(p.automation?.message||'Wartet auf Lobby-Einladung'):'Automatik aus';$('auto-last').textContent=p.automation?.last_accepted?'Letzter bestätigter Beitritt: '+new Date(p.automation.last_accepted*1000).toLocaleTimeString('de-DE')+' · '+(p.automation.last_sender||''):''}
$('auto-accept').onchange=async e=>{const input=e.target;input.disabled=true;try{await api('players/'+selected+'/auto-accept','PUT',{enabled:input.checked});await refresh()}catch(e){notice(e.message);renderAutomation()}finally{input.disabled=false}};
$('hosts-form').onsubmit=async e=>{e.preventDefault();try{const result=await api('automation','PUT',{hosts:$('hosts').value.split('\n'),boards:automationConfig.boards||{}});automationConfig=result;$('hosts').value=result.hosts.join('\n');notice('');await refresh()}catch(e){notice(e.message)}};
api('automation').then(result=>{$('hosts').value=result.hosts.join('\n')}).catch(e=>notice(e.message));

function renderHttpSession(){
  const p=players.find(p=>p.id===selected),http=p?.http_session;
  const active=!!http?.authenticated&&!p.browser_open;
  $('http-state').hidden=!active;
  if(active){disconnect();$('viewer').hidden=true;$('empty').hidden=true;
    $('connection').textContent=http.transport_connected?'HTTP-Verbindung aktiv':http.active?'HTTP verbindet …':'Pausiert';
    $('http-account').textContent=http.account_name||p.name;
    $('http-message').textContent=http.automation?.message||'HTTP-Sitzung wird vorbereitet';
  }
}
$('http-login').onclick=async()=>{try{
  await api('players/'+selected+'/login','POST');$('http-state').hidden=true;
  $('viewer').hidden=false;$('loading').hidden=false;$('loading').textContent='Anmeldung wird geöffnet …';
  disconnect();connect(selected,epoch);await refresh();
}catch(e){notice(e.message)}};
$('http-resume').onclick=async()=>{try{await api('players/'+selected+'/start','POST');await refresh()}catch(e){notice(e.message)}};
$('http-pause').onclick=async()=>{try{await api('players/'+selected+'/stop','POST');await refresh()}catch(e){notice(e.message)}};

$('test-host-form').onsubmit=async e=>{e.preventDefault();const name=$('test-host').value.trim();if(!name)return;
  try{automationConfig=await api('automation','PUT',{
    hosts:[...new Set([...(automationConfig.hosts||[]),name])],
    boards:{...(automationConfig.boards||{}),[name.toLowerCase()]:$('test-board').value}});
    $('hosts').value=automationConfig.hosts.join('\n');notice('Test-Gastgeber gespeichert. Das Board muss in der echten Lobby übereinstimmen.');
  }catch(error){notice(error.message)}
};

let activity={players:[],boards:[]};
function gameText(g){const others=g.opponents?.length?g.opponents.join(', '):'niemandem';return (g.kind==='match'?'Im Spiel mit ':'In Lobby'+(g.host?' von '+g.host:'')+' mit ')+others+(g.boards?.length?' · '+g.boards.join('/'):'')+(g.pending?' (eingeladen)':'')}
function activityText(id){const games=activity.players.find(p=>p.id===id)?.games||[];return games.length?'● '+games.map(gameText).join(' · '):''}
function idLink(kind,id){const path=(kind==='match'?'matches/':'lobby/')+encodeURIComponent(id);const a=document.createElement('a');a.href='https://play-v1.autodarts.com/'+path;a.target='_blank';a.rel='noopener';a.textContent=id;return a}
function abortButton(label,question,run){const b=document.createElement('button');b.type='button';b.className='danger';b.textContent=label;b.onclick=async()=>{if(!confirm(question))return;b.disabled=true;try{await run();notice('Abgebrochen. Es wurde nichts gewertet.');await loadActivity()}catch(e){notice(e.message);b.disabled=false}};return b}
function renderActivity(){
  const box=$('boards-status');box.replaceChildren();
  for(const b of activity.boards){const row=document.createElement('div');row.className='game-row';const title=document.createElement('strong');title.textContent=b.name+': ';row.append(title);
    if(!b.visible)row.append('nicht sichtbar (Board-Besitzer nicht angemeldet)');
    else if(!b.match)row.append('frei');
    else{row.append((b.match.players.length?b.match.players.join(' – '):'Match')+' ',idLink('match',b.match.id),' ',abortButton('Abbrechen',`Match auf ${b.name} (${b.match.players.join(' – ')||b.match.id}) ohne Wertung abbrechen?`,()=>api('boards/'+b.id+'/abort','POST',{match_id:b.match.id})))}
    box.append(row)}
  const lobbies=new Map();for(const p of activity.players)for(const g of p.games||[])if(g.kind==='lobby')lobbies.set(g.id,g);
  for(const g of lobbies.values()){const row=document.createElement('div');row.className='game-row';row.append('Lobby '+(g.host?'von '+g.host+' ':'')+'('+g.players.join(', ')+') ',idLink('lobby',g.id),' ',abortButton('Löschen',`Lobby von ${g.host||'?'} löschen?`,()=>api('lobbies/'+encodeURIComponent(g.id)+'/abort','POST')));box.append(row)}
  const errors=activity.players.filter(p=>p.error);for(const p of errors){const row=document.createElement('p');row.textContent=(p.name?p.name+': ':'')+p.error;box.append(row)}
  if(!box.children.length)box.textContent='Keine laufenden Spiele.';
}
async function loadActivity(){try{activity=await api('activity');renderActivity();refresh();const log=await api('autodarts-ids?limit=30');const list=$('id-log');list.replaceChildren(...log.map(e=>{const row=document.createElement('div');row.className='game-row';row.append(new Date(e.at*1000).toLocaleString('de-DE')+' · '+e.event+' · '+(e.board||e.account||'')+' · '+(e.players||[]).join(' – ')+' ',idLink(e.kind,e.id));return row}));if(!log.length)list.textContent='Noch keine IDs.'}catch(e){$('boards-status').textContent=e.message}}
loadActivity();setInterval(()=>{if(!document.hidden)loadActivity()},15000);
