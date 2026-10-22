// ==UserScript==
// @name         Dartfreunde Platten – Turnier-Board Rot
// @namespace    dartfreunde-platten-turnierplaner
// @version      2.4.3
// @description  Feste Scheibenzuordnung, Steuerungsrechte, Vollbild und Ergebnisübernahme.
// @match        https://play.autodarts.com/*
// @run-at       document-start
// @noframes
// @grant        unsafeWindow
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_xmlhttpRequest
// @connect      turnier.mulich.de
// @connect      dartportal.mulich.de
// @connect      192.168.178.137
// @connect      api.autodarts.com
// @downloadURL  https://dartportal.mulich.de/static/turnier-rot.user.js
// @updateURL    https://dartportal.mulich.de/static/turnier-rot.user.js
// ==/UserScript==

(() => {
  'use strict';
  const BOARDS = [{"name": "Blau", "account": "blau", "id": "faa2cd5f-5d19-4e68-9749-1b7b95c753d4"}, {"name": "Rot", "account": "rot", "id": "ad381dc0-7e86-45a1-9fa8-61c8b18ec89b"}, {"name": "Schwarz", "account": "schwarz", "id": "6e390006-cdba-4ac5-b0bb-0e03eb880af6"}];
  const FIXED_BOARD = {"name": "Rot", "account": "rot", "id": "ad381dc0-7e86-45a1-9fa8-61c8b18ec89b"};
  let BOARD = FIXED_BOARD?.name || 'Account erkennen';
  let BOARD_ID = '';
  function boardForAccount(user) {
    if(!user?.id || typeof user.name!=='string')return null;
    return BOARDS.find(board=>normalize(board.account)===normalize(user.name)) || null;
  }
  function tokenSubject(token) {
    try {
      const sub=JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub;
      return typeof sub==='string' && sub ? sub : '';
    } catch {return '';}
  }
  const SERVER = 'https://turnier.mulich.de';
  const PORTAL = 'https://dartportal.mulich.de';
  const API = 'https://api.autodarts.com';
  const normalize = value => String(value || '').trim().toLocaleLowerCase('de');
  function resolvePlayers(names, friends, me) {
    const users = [me, ...friends.filter(f => f.requestStatus === 'Accepted').map(f => f.user)].filter(Boolean);
    return names.map(name => {
      const found = [...new Map(users.filter(u => normalize(u.name) === normalize(name)).map(u => [u.id, u])).values()];
      if (found.length !== 1 || !found[0].id) throw new Error(`Account „${name}“ nicht eindeutig gefunden. Im Board-Account als Freund hinzufügen und Anfrage annehmen.`);
      return found[0];
    });
  }
  function entries(job) {
    return job.participants || [job.match.player1,job.match.player2].map(name=>({name,account_name:name}));
  }
  function localKey(name) {return 'local:'+normalize(name);}
  function matchesPlayer(player,index,job,stats=false) {
    const entry=entries(job)[index];
    if(!entry.account_name)return !player.userId && !player.user?.id && normalize(player.name)===normalize(entry.name);
    const id=job.user_ids[index];
    const ident=player.userId || player.user?.id || (job.user_ids.includes(player.id)?player.id:null);
    return ident ? ident===id : stats && normalize(player.name)===normalize(entry.account_name);
  }
  function finalResult(state, stats, job) {
    if (state?.finished !== true || !Array.isArray(stats?.players) || stats.players.length !== 2 || !Array.isArray(stats.matchStats) || stats.matchStats.length !== 2) return null;
    const scores = job.user_ids.map((id, expectedIndex) => {
      const matches = stats.players.map((p, index) => ({p, index})).filter(({p})=>matchesPlayer(p,expectedIndex,job,true));
      if (matches.length !== 1) return null;
      const legs = stats.matchStats[matches[0].index]?.legsWon;
      return Number.isInteger(legs) && legs >= 0 ? legs : null;
    });
    if (scores.some(s => s === null) || Math.max(...scores) !== job.lobby_payload.legs || Math.min(...scores) >= job.lobby_payload.legs) return null;
    return {score1:scores[0], score2:scores[1], user_ids:job.user_ids, autodarts_match_id:job.autodarts_match_id};
  }
  function completedArchiveResult(stats,job) {
    if(stats?.id && stats.id!==job.autodarts_match_id)return null;
    if(stats?.matchId && stats.matchId!==job.autodarts_match_id)return null;
    // Only the persisted analytics endpoint for this exact match is used.
    // The expected players and exact first-to target must independently confirm the outcome.
    return finalResult({finished:true},stats,job);
  }
  function normalizeLobby(lobby, id) {
    if(!lobby || lobby.id!==id || !Object.hasOwn(lobby,'players'))throw new Error('Lobby-Antwort unvollständig. Wartet auf aktuellen Autodarts-Status.');
    // An empty Autodarts lobby may serialize its player list as null.
    const players=lobby.players===null?[]:lobby.players;
    if(!Array.isArray(players) || players.some(p=>!p || typeof p!=='object'))throw new Error('Lobby-Spielerliste nicht verfügbar. Wartet auf aktuellen Autodarts-Status.');
    return {...lobby,players};
  }
  function completePlayers(lobby,job) {
    return lobby.players.length===2 && !lobby.players.some(p=>p.isPending || p.cpuPPR)
      && job.user_ids.every((id,index)=>lobby.players.filter(p=>matchesPlayer(p,index,job)).length===1);
  }
  function correctLobby(lobby, job, boardId=BOARD_ID, account='') {
    if (!lobby?.isPrivate || lobby.hasReferee===true || !Array.isArray(lobby.players)) return false;
    const expected=job.lobby_payload;
    if(lobby.variant!==expected.variant || lobby.legs!==expected.legs || lobby.bullOffMode!==expected.bullOffMode || Object.entries(expected.settings).some(([key,value])=>lobby.settings?.[key]!==value))return false;
    const players = lobby.players;
    return players.length === 2 && players.every(p => !p.isPending && !p.cpuPPR && p.boardId === boardId && (!account || p.userId===account || p.hostId===account))
      && job.user_ids.every((id, index) => matchesPlayer(players[index],index,job));
  }
  function parseResponse(response, url, accountPortal=PORTAL) {
    const origin=new URL(url).origin;
    const service = origin===SERVER ? 'planner' : origin===API ? 'autodarts' : origin===new URL(accountPortal).origin ? 'portal' : 'unknown';
    const label = ({planner:'Turnierplaner',autodarts:'Autodarts',portal:'Accountzentrale',unknown:'Server'})[service];
    const fail = text => { const error=new Error(`${label}: HTTP ${response.status} – ${text}`); error.status=response.status; error.service=service; throw error; };
    const successful=response.status>=200 && response.status<300;
    const text=typeof response.responseText==='string'?response.responseText.trim():'';
    if(response.status===401 && /(?:^|\r?\n)www-authenticate:\s*Basic\b/i.test(response.responseHeaders || '')) {
      fail(service==='planner'?'Website-Passwortschutz: turnier.mulich.de auf diesem PC im selben Browser öffnen und anmelden.':service==='portal'?'Website-Passwortschutz: Accountzentrale auf diesem PC im selben Browser öffnen und anmelden (Tampermonkey-Menü „Accountzentrale anmelden“).':service==='autodarts'?'Autodarts-Anmeldung abgelehnt. Autodarts auf diesem PC neu laden und gegebenenfalls erneut anmelden.':'Website-Passwortschutz blockiert diesen Server.');
    }
    if(response.status===401 && service==='autodarts')fail('Autodarts-Anmeldung abgelaufen oder abgelehnt. Seite neu laden und gegebenenfalls erneut anmelden.');
    let body;
    if(response.response && typeof response.response==='object')body=response.response;
    else if(!text && successful)return null;
    else {
      try{body=JSON.parse(text);}catch {
        fail(/^(?:<!doctype|<html|<head|<body)/i.test(text)?'HTML-Seite statt JSON. Passwortschutz, Weiterleitung und Proxy-Ziel prüfen.':'Keine JSON-Antwort. Proxy-Ziel und Serverstatus prüfen.');
      }
    }
    if(!successful)fail(typeof body?.detail==='string'?body.detail:body?.error?.message || 'Anfrage abgelehnt.');
    return body;
  }
  // Pure adapters are exercised using fixtures; requiring this file never enables automation.
  if (typeof module === 'object' && module.exports) {
    module.exports = {resolvePlayers, finalResult, correctLobby, parseResponse, matchesPlayer, localKey, normalizeLobby, boardForAccount, completedArchiveResult};
    return;
  }
  // Legacy download links remain supported; only one agent may run in this page.
  if(unsafeWindow.__dfpTournamentAgent)return;
  unsafeWindow.__dfpTournamentAgent=true;
  const instance = crypto.randomUUID();
  let storage = FIXED_BOARD ? `dfp-turnier-${FIXED_BOARD.id}` : 'dfp-turnier-auto';
  let accountSubject = '';
  let accountChanged = false;
  let config = {enabled:GM_getValue(storage, {enabled:true}).enabled!==false};
  let bearer = '';
  let message = 'Automatik aus';
  let ticking = false;
  let panel;
  let currentJob;
  let cacheKey = storage + '-pending';
  const acceptedUrl = url => {
    try { return new URL(url, location.href).origin === API; } catch { return false; }
  };
  function capture(value) {
    const match = typeof value === 'string' && value.match(/^Bearer\s+(.+)$/i);
    if (match) {
      const sub=tokenSubject(match[1]);
      if(!sub)return; // Ignore malformed or unrelated authorization headers.
      bearer = match[1];
      if(accountSubject && sub!==accountSubject)accountChanged=true;
    }
  }
  // Observe only requests to the exact Autodarts API origin; never log or transmit credentials to the planner.
  const requests = new WeakMap();
  const observed = new WeakSet();
  const authUrl=url=>{try{const u=new URL(url,location.href);return u.origin===API && u.pathname.startsWith('/auth/v1/');}catch{return false;}};
  function captureAuth(body) {if(typeof body?.access_token==='string')capture('Bearer '+body.access_token);}
  const xhr = unsafeWindow.XMLHttpRequest.prototype;
  const open = xhr.open, header = xhr.setRequestHeader;
  xhr.open = function(method, url, ...rest) {
    requests.set(this,{api:acceptedUrl(url),auth:authUrl(url)});
    if(!observed.has(this)) {
      observed.add(this);
      this.addEventListener?.('load',()=>{
        if(!requests.get(this)?.auth || this.status<200 || this.status>=300)return;
        try{captureAuth(typeof this.response==='object'?this.response:JSON.parse(this.responseText));}catch{}
      });
    }
    return open.call(this, method, url, ...rest);
  };
  xhr.setRequestHeader = function(name, value) { if(requests.get(this)?.api && String(name).toLowerCase() === 'authorization')capture(value); return header.call(this, name, value); };
  const originalFetch = unsafeWindow.fetch;
  unsafeWindow.fetch = function(input, options) {
    const url = typeof input === 'string' ? input : input?.url;
    if(acceptedUrl(url)) {
      const headers = new Headers(options?.headers || input?.headers);
      capture(headers.get('authorization'));
    }
    const pending=originalFetch.call(this, input, options);
    if(authUrl(url))pending.then(async response=>{
      if(response.ok)try{captureAuth(await response.clone().json());}catch{}
    }).catch(()=>{});
    return pending;
  };
  function show(text) { message = text; if(panel)panel.querySelector('[data-status]').textContent=text; }
  function request(url, method='GET', data, headers={}, timeout=12000) {
    if(accountChanged)throw new Error('Autodarts-Account gewechselt. Seite neu laden, um die Scheibe neu zu erkennen.');
    return new Promise((resolve, reject) => GM_xmlhttpRequest({url, method, timeout, anonymous:![SERVER,portalUrl()].includes(new URL(url).origin),
      headers:{'Content-Type':'application/json', ...headers}, data:data===undefined?undefined:JSON.stringify(data),
      onload:r=>{
        try{resolve(parseResponse(r,url,portalUrl()));}catch(error){reject(error);}
      }, onerror:()=>reject(new Error('Verbindung fehlgeschlagen.')), ontimeout:()=>reject(new Error('Zeitüberschreitung.'))
    }));
  }
  const planner = (path, data) => request(SERVER+path, 'POST', {instance, ...data}, {'X-Board-ID':BOARD_ID});
  function portalUrl() {return GM_getValue(storage+'-portal-url',PORTAL);}
  const autodarts = async (path, method='GET', data) => {
    if(!bearer)throw new Error('Wartet auf erneuerte Autodarts-Anmeldung. Bei Bedarf Autodarts-Seite neu laden.');
    const usedToken=bearer;
    try{return await request(API+path,method,data,{Authorization:'Bearer '+usedToken});}
    catch(error) {
      if(error.status===401 && bearer===usedToken)bearer='';
      throw error; // Never retry an ambiguous lobby write automatically.
    }
  };
  async function identifyBoard() {
    if(accountChanged)throw new Error('Autodarts-Account gewechselt. Seite neu laden, um die Scheibe neu zu erkennen.');
    if(!bearer){show('Wartet auf Autodarts-Anmeldung');return false;}
    if(BOARD_ID)return true;
    const sub=tokenSubject(bearer);
    if(!sub)throw new Error('Account-Sitzung nicht erkannt.');
    let board=FIXED_BOARD;
    if(!board) {
      const user=await autodarts(`/us/v0/users/${encodeURIComponent(sub)}`);
      if(user?.id!==sub)throw new Error('Account-Antwort stimmt nicht mit der Sitzung überein.');
      board=boardForAccount(user);
    }
    if(tokenSubject(bearer)!==sub)throw new Error('Account während Erkennung gewechselt. Seite neu laden.');
    if(!board) {show('Kein Board-Account: als rot, blau oder schwarz anmelden.');return false;}
    accountSubject=sub;BOARD=board.name;BOARD_ID=board.id;
    storage=`dfp-turnier-${BOARD_ID}`;cacheKey=storage+'-pending';
    config={enabled:GM_getValue(storage,{enabled:true}).enabled!==false};
    show(config.enabled?'Automatik aktiv':'Board-Script pausiert');
    if(panel){panel.remove();mount();}
    return true;
  }
  async function phase(job, next, extra={}) {
    const r=await planner(`/api/bridge/jobs/${job.id}/state`, {phase:next, ...extra});
    currentJob=r.job;
    return r.job;
  }
  async function boardReady() {
    if(!bearer)return false;
    const info=await autodarts(`/bs/v0/boards/${BOARD_ID}`);
    if(info.id!==BOARD_ID)throw new Error('Board-ID stimmt nicht.');
    if(!info.matchId)return true;
    // A completed match may still be displayed on the board. Never displace an unrelated game.
    const last=GM_getValue(storage+'-last-match', '');
    if(info.matchId!==last)return false;
    try {
      const state=await autodarts(`/gs/v0/matches/${info.matchId}/state`);
      return state?.finished===true;
    }catch(error) {
      if(error.status===404)return true; // This exact match already had a validated result imported.
      throw error;
    }
  }
  async function prepare(job) {
    const planned=entries(job);
    let sub;
    try{sub=JSON.parse(atob(bearer.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub;}catch{throw new Error('Account-Sitzung nicht erkannt.');}
    let friends=[],me=null;
    if(planned.some(p=>p.account_name)) {
      friends=await autodarts('/as/v0/friends');
      if(!Array.isArray(friends))throw new Error('Freundesliste nicht erkannt.');
      me=await autodarts(`/us/v0/users/${encodeURIComponent(sub)}`);
    }
    const users=planned.map(p=>p.account_name?resolvePlayers([p.account_name],friends,me)[0]:{id:localKey(p.name),name:p.name});
    if(users[0].id===users[1].id)throw new Error('Beide Spieler sind derselbe Teilnehmer.');
    // Commit the creation intent BEFORE the external write. An ambiguous failure cannot create a second lobby.
    job=await phase(job,'creating');
    GM_setValue(cacheKey,{job:job.id, stage:'creating'});
    const lobby=await autodarts('/gs/v0/lobbies','POST',job.lobby_payload);
    if(!lobby?.id)throw new Error('Lobby wurde nicht bestätigt. Automatik pausieren und in Autodarts prüfen.');
    GM_setValue(cacheKey,{job:job.id,lobby_id:lobby.id,user_ids:users.map(u=>u.id),host:sub});
    return phase(job,'lobby',{lobby_id:lobby.id,user_ids:users.map(u=>u.id)});
  }
  async function loadLobby(job) {
    return normalizeLobby(await autodarts(`/gs/v0/lobbies/${job.lobby_id}`),job.lobby_id);
  }
  async function arrange(job) {
    let lobby=await loadLobby(job);
    let account;try{account=JSON.parse(atob(bearer.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub;}catch{}
    if(!account||lobby.host?.id!==account||lobby.isPrivate!==true)throw new Error('Private Gastgeber-Lobby nicht bestätigt.');
    // Newly created lobbies may contain the board account. Keep it only if it is one of the scheduled players.
    const hostIndex=lobby.players.findIndex(p=>p.userId===lobby.host.id && !job.user_ids.includes(p.userId));
    if(hostIndex>=0) {
      await autodarts(`/gs/v0/lobbies/${job.lobby_id}/players/by-index/${hostIndex}`,'DELETE');
      lobby=await loadLobby(job);
    }
    if(lobby.players.some(p=>!job.user_ids.some((id,index)=>matchesPlayer(p,index,job))))throw new Error('Unerwarteter Teilnehmer in der Lobby. Manuell prüfen.');
    let record=GM_getValue(cacheKey,null);
    const valid=record && typeof record==='object' && !Array.isArray(record)
      && record.job===job.id && record.lobby_id===job.lobby_id
      && (record.invited===undefined || Array.isArray(record.invited))
      && (record.locals===undefined || Array.isArray(record.locals));
    if(!valid) {
      // Recover from confirmed lobby participants only. A lost cache must never
      // repeat an invitation/local-player write whose outcome is unknown.
      if(!job.user_ids.every((id,index)=>lobby.players.some(p=>matchesPlayer(p,index,job))))
        throw new Error('Lokaler Einladungsstatus fehlt. Lobby unvollständig: Notfall-Neustart im Turnierplaner verwenden.');
      record={job:job.id,lobby_id:job.lobby_id,
        invited:job.user_ids.filter((id,index)=>entries(job)[index].account_name),
        locals:job.user_ids.filter((id,index)=>!entries(job)[index].account_name)};
      GM_setValue(cacheKey,record);
    }
    record.invited=record.invited || [];
    record.locals=record.locals || [];
    for(let index=0;index<job.user_ids.length;index++) {
      const id=job.user_ids[index],entry=entries(job)[index];
      if(lobby.players.some(p=>matchesPlayer(p,index,job)))continue;
      if(!entry.account_name) {
        if(record.locals.includes(id))throw new Error('Lokaler Spieler nicht bestätigt. Automatik pausieren und Lobby prüfen; Zuordnung ggf. zurücksetzen.');
        record.locals.push(id);GM_setValue(cacheKey,record);
        await autodarts(`/gs/v0/lobbies/${job.lobby_id}/players`,'POST',{name:entry.name,boardId:BOARD_ID});
      }else if(!record.invited.includes(id)) {
        record.invited.push(id);GM_setValue(cacheKey,record);
        await autodarts(`/gs/v0/lobbies/${job.lobby_id}/invitations/${encodeURIComponent(id)}`,'POST');
      }
      lobby=await loadLobby(job);
    }
    lobby=await loadLobby(job);
    if(lobby.players.length!==2 || lobby.players.some(p=>p.isPending)) {show('Wartet auf die Annahme der Account-Einladungen');return job;}
    for(let index=0;index<lobby.players.length;index++) {
      if(lobby.players[index].boardId!==BOARD_ID || (lobby.players[index].userId!==account && lobby.players[index].hostId!==account))await autodarts(`/gs/v0/lobbies/${job.lobby_id}/players/by-index/${index}/host`,'PUT',{boardId:BOARD_ID});
    }
    lobby=await loadLobby(job);
    if(!completePlayers(lobby,job)){show('Wartet auf vollständige Lobby-Spielerliste');return job;}
    for(let target=0;target<job.user_ids.length;target++) {
      const index=lobby.players.findIndex(p=>matchesPlayer(p,target,job));
      if(index<0){show('Wartet auf bestätigte Teilnehmer');return job;}
      if(index!==target) {
        await autodarts(`/gs/v0/lobbies/${job.lobby_id}/players/move/to-index`,'POST',{index,toIndex:target});
        lobby=await loadLobby(job);
        if(!completePlayers(lobby,job)){show('Wartet auf vollständige Lobby-Spielerliste');return job;}
      }
    }
    if(!await boardReady()){show('Scheibe inzwischen belegt · wartet');return job;}
    if(!correctLobby(lobby,job,BOARD_ID,account))throw new Error('Spieler, Scheibe oder Anwurf konnten nicht bestätigt werden.');
    job=await phase(job,'starting');
    const started=await autodarts(`/gs/v0/lobbies/${job.lobby_id}/start`,'POST');
    if(!started?.id)throw new Error('Matchstart nicht bestätigt. Manuell prüfen.');
    GM_setValue(cacheKey,{job:job.id,lobby_id:job.lobby_id,user_ids:job.user_ids,autodarts_match_id:started.id});
    job=await phase(job,'playing',{autodarts_match_id:started.id});
    // Autodarts may already navigate on its match-start event. Avoid reloading that live view.
    if(location.pathname!==`/matches/${started.id}`)unsafeWindow.location.assign(`https://play.autodarts.com/matches/${started.id}`);
    return job;
  }
  let fullscreenMatch='';
  let fullscreenOwned=false;
  let fullscreenAttempt=0;
  let fullscreenDismissed='';
  const onMatchPage=id=>!!id && [`/matches/${id}`,`/match/${id}`].includes(location.pathname);
  async function enterFullscreen() {
    if(document.fullscreenElement){
      // Tools for Autodarts may already have entered document fullscreen.
      // Adopt that match view too, so it leaves fullscreen when the match ends.
      if(onMatchPage(currentJob?.autodarts_match_id) && document.fullscreenElement===document.documentElement)fullscreenOwned=true;
      return;
    }
    try {
      if(!document.documentElement?.requestFullscreen)throw new Error('unsupported');
      await document.documentElement.requestFullscreen({navigationUI:'hide'});
      fullscreenOwned=true;
      fullscreenNotice('');
    }catch{fullscreenNotice('Automatisches Vollbild im Browser für play.autodarts.com erlauben. Alternativ einmal in die Spielansicht oder auf ⛶ klicken.');}
  }
  async function leaveMatchFullscreen(id=fullscreenMatch) {
    fullscreenDismissed=id || fullscreenDismissed;
    fullscreenMatch='';fullscreenAttempt=0;
    if(fullscreenOwned && document.fullscreenElement) {
      fullscreenOwned=false;
      try{await document.exitFullscreen();}catch{fullscreenOwned=!!document.fullscreenElement;fullscreenNotice('Vollbild verlassen: Esc drücken.');return;}
    }
    fullscreenOwned=false;
    fullscreenNotice('');
  }
  function fullscreenNotice(text) {if(panel)panel.querySelector('[data-fullscreen-status]').textContent=text;}
  async function matchFullscreen(job) {
    if(!onMatchPage(job.autodarts_match_id) || document.hidden || fullscreenDismissed===job.autodarts_match_id)return;
    if(document.fullscreenElement===document.documentElement && document.fullscreenElement){
      fullscreenMatch=job.autodarts_match_id;fullscreenOwned=true;return;
    }
    if(fullscreenMatch===job.autodarts_match_id && (document.fullscreenElement || Date.now()-fullscreenAttempt<15000))return;
    fullscreenMatch=job.autodarts_match_id;
    fullscreenAttempt=Date.now();
    await enterFullscreen();
  }
  // A real click supplies the user activation required by browsers without an
  // automatic-fullscreen permission. Never simulate keystrokes or trusted clicks.
  document.addEventListener('pointerdown',()=>{
    if(config.enabled && currentJob?.phase==='playing' && !currentJob.paused && onMatchPage(currentJob.autodarts_match_id) && fullscreenDismissed!==currentJob.autodarts_match_id)enterFullscreen();
  },{capture:true});
  document.addEventListener('fullscreenchange',()=>{
    if(fullscreenOwned && !document.fullscreenElement){fullscreenOwned=false;fullscreenDismissed=fullscreenMatch;}
  });
  async function watch(job) {
    let state,gone=false;
    try{state=await autodarts(`/gs/v0/matches/${job.autodarts_match_id}/state`);}
    catch(error){if(error.status!==404)throw error;gone=true;}
    if(!gone && state?.finished!==true) {await matchFullscreen(job);show('Match läuft · Ergebnisübernahme aktiv');return;}
    if(state?.finished===true)await leaveMatchFullscreen(job.autodarts_match_id);
    let stats;
    try{stats=await autodarts(`/as/v0/matches/${job.autodarts_match_id}/stats`);}catch(e){if(e.status===404){show('Wartet auf gespeicherte Match-Statistik');return;}throw e;}
    const result=gone?completedArchiveResult(stats,job):finalResult(state,stats,job);
    if(!result){show(gone?'Live-Match nicht mehr verfügbar · wartet auf bestätigtes gespeichertes Endergebnis':'Kein eindeutiges Endergebnis. Bitte Spielstand prüfen.');return;}
    await leaveMatchFullscreen(job.autodarts_match_id);
    await planner(`/api/bridge/jobs/${job.id}/result`,result);
    GM_setValue(storage+'-last-match',job.autodarts_match_id);
    GM_setValue(cacheKey,null);
    show(`Ergebnis ${result.score1}:${result.score2} übernommen`);
  }
  async function restartLobby(job) {
    const progress=async step=>{
      const reply=await planner(`/api/bridge/jobs/${job.id}/restart`,{restart_id:job.restart_id,step});
      currentJob=reply.job;return reply.job;
    };
    if(job.restart_step==='delete') {
      show('Lobby-Neustart · alte Lobby löschen');
      if(!await boardReady())throw new Error('Lobby-Neustart blockiert: auf der Scheibe ist noch ein Match aktiv. Zuerst beenden.');
      let lobby;
      try{lobby=await loadLobby(job);}catch(error){if(error.status!==404)throw error;}
      if(lobby) {
        if(lobby.host?.id!==tokenSubject(bearer))throw new Error('Lobby-Neustart blockiert: Board-Account ist nicht Gastgeber.');
        try{await autodarts(`/gs/v0/lobbies/${job.lobby_id}`,'DELETE');}catch(error){if(error.status!==404)throw error;}
        try{await loadLobby(job);throw new Error('Lobby noch vorhanden · Löschung nicht bestätigt.');}catch(error){if(error.status!==404)throw error;}
      }
      job=await progress('deleted');
    }
    if(!job.restart_ready){show('Lobby-Neustart · kurze Wartezeit');return;}
    if(job.restart_step==='accounts') {
      show('Lobby-Neustart · betroffene Accounts zur Startseite');
      const users=(job.user_ids || []).filter(id=>!id.startsWith('local:') && id!==tokenSubject(bearer));
      const reply=users.length?await request(portalUrl()+'/api/automation/lobby-recovery','POST',{
        operation_id:job.restart_id,board_account:BOARD.toLowerCase(),lobby_id:job.lobby_id,user_ids:users,completed_match_ids:job.completed_match_ids || []
      },{Origin:portalUrl()},45000):{operation_id:job.restart_id,recovered:[]};
      if(reply.operation_id!==job.restart_id || !Array.isArray(reply.recovered) || [...users].sort().join('|')!==[...reply.recovered].sort().join('|'))throw new Error('Accountzentrale: Neustart nicht vollständig bestätigt.');
      job=await progress('accounts');
      show('Lobby-Neustart · wartet auf neue Einladungen');return;
    }
    if(job.restart_step==='wait') {
      await progress('complete');
      GM_setValue(cacheKey,null);
      show('Lobby-Neustart bestätigt · neue Lobby wird vorbereitet');
    }
  }
  async function tick() {
    if(ticking)return;
    ticking=true;
    try {
      if(!await identifyBoard() || !config.enabled)return;
      let ready=false;
      try{ready=await boardReady();}catch(error){show(error.message);}
      const reply=await planner('/api/bridge/poll',{ready,status:bearer?message:'Wartet auf Autodarts-Anmeldung'});
      if(reply.completed_match_id)GM_setValue(storage+'-last-match',reply.completed_match_id);
      if(!reply || typeof reply!=='object' || !Object.hasOwn(reply,'job'))throw new Error('Turnierplaner: Board-Antwort unvollständig. Container-Version und Proxy-Ziel prüfen.');
      currentJob=reply.job;
      if(!currentJob){if(!reply.message)await leaveMatchFullscreen();show(reply.message || (ready?'Wartet auf nächste Begegnung':bearer?'Scheibe belegt · bestehendes Spiel zuerst beenden':'Autodarts anmelden und Seite neu laden'));return;}
      if(currentJob.paused){
        if(fullscreenOwned && currentJob.phase==='playing') {
          const state=await autodarts(`/gs/v0/matches/${currentJob.autodarts_match_id}/state`);
          if(state?.finished===true)await leaveMatchFullscreen();
        }
        show('Turnier-Automatik pausiert oder beendet');return;
      }
      if(fullscreenMatch && !onMatchPage(fullscreenMatch))await leaveMatchFullscreen();
      let job=currentJob;
      if(job.phase==='restarting'){await restartLobby(job);return;}
      if(['queued','lobby'].includes(job.phase)&&!ready){show('Scheibe belegt oder Autodarts nicht bereit · wartet');return;}
      if(job.phase==='queued')job=await prepare(job);
      const cached=GM_getValue(cacheKey,null);
      if(job.phase==='creating') {
        if(cached?.job===job.id&&cached.lobby_id)job=await phase(job,'lobby',{lobby_id:cached.lobby_id,user_ids:cached.user_ids});
        else throw new Error('Lobby-Erstellung unklar. Automatik pausieren, Autodarts prüfen und Auftrag im Planer zurücksetzen.');
      }
      if(job.phase==='lobby')job=await arrange(job);
      if(job.phase==='starting') {
        if(cached?.job===job.id&&cached.autodarts_match_id)job=await phase(job,'playing',{autodarts_match_id:cached.autodarts_match_id});
        else throw new Error('Matchstart unklar. Automatik pausieren und Match in Autodarts prüfen.');
      }
      if(job.phase==='playing')await watch(job);
      currentJob=job;
    } catch(error) {
      show(error.message);
      if(currentJob && !accountChanged)try{await planner(`/api/bridge/jobs/${currentJob.id}/state`,{phase:currentJob.phase,error:error.message.slice(0,240)});}catch{}
    } finally {ticking=false;}
  }
  function configure() {
    unsafeWindow.open(SERVER+'/#integration','_blank','noopener');
    show('Turnierplaner im geöffneten Tab anmelden; danach Script fortsetzen.');
  }
  function toggle() {config.enabled=!config.enabled;GM_setValue(storage,config);show(config.enabled?'Automatik aktiv':'Board-Script pausiert');tick();}
  GM_registerMenuCommand(`Turnier-Board: Website anmelden`,configure);
  GM_registerMenuCommand(`Turnier-Board: starten/pausieren`,toggle);
  GM_registerMenuCommand('Turnier-Board: Accountzentrale anmelden',()=>unsafeWindow.open(portalUrl(),'_blank','noopener'));
  GM_registerMenuCommand('Turnier-Board: Accountzentrale-Adresse',()=>{
    const value=unsafeWindow.prompt('Accountzentrale: https://dartportal.mulich.de oder http://192.168.178.137:18080',portalUrl());
    if(value===null)return;
    try{const u=new URL(value);if(![PORTAL,'http://192.168.178.137:18080'].includes(u.origin))throw new Error();GM_setValue(storage+'-portal-url',u.origin);show('Adresse der Accountzentrale gespeichert.');}
    catch{show('Ungültige Adresse der Accountzentrale.');}
  });
  function mount() {
    if(!document.body)return;
    panel=document.createElement('div');
    panel.style.cssText='position:fixed;bottom:12px;right:12px;z-index:9999;background:#142a40;color:#cce6ff;border:1px solid #395f80;border-radius:8px;padding:12px;font:12px system-ui;max-width:340px;box-shadow:0 4px 18px #0005';
    let collapsed=GM_getValue(storage+'-collapsed',true);
    const title=document.createElement('button');title.type='button';
    title.style.cssText='display:block;background:transparent;color:#cce6ff;border:0;padding:0;cursor:pointer;font:600 12px system-ui;line-height:20px';
    const details=document.createElement('div');details.id='dfp-board-details-'+BOARD_ID;
    title.setAttribute('aria-controls',details.id);
    function renderFold() {
      title.textContent=collapsed?`Darts · ${BOARD} ▸`:`Turnierplaner · ${BOARD} ▾`;
      title.setAttribute('aria-label',collapsed?'Turnierfenster ausklappen':'Turnierfenster einklappen');
      title.setAttribute('aria-expanded',String(!collapsed));
      details.hidden=collapsed;details.style.display=collapsed?'none':'block';
      panel.style.padding=collapsed?'5px 8px':'12px';
    }
    title.onclick=()=>{collapsed=!collapsed;GM_setValue(storage+'-collapsed',collapsed);renderFold();};

    const status=document.createElement('p');status.dataset.status='';status.style.cssText='margin:6px 0;overflow-wrap:anywhere';status.textContent=message;
    const setup=document.createElement('button');setup.textContent='Website anmelden';setup.onclick=configure;
    const pause=document.createElement('button');pause.textContent='Start / Pause';pause.onclick=toggle;
    for(const button of [setup,pause])button.style.cssText='background:#254b6a;color:#fff;border:1px solid #527795;border-radius:4px;padding:5px 8px;margin-right:6px;cursor:pointer';
    const full=document.createElement('button');full.type='button';full.textContent='⛶';full.title='Vollbild ein / aus';full.setAttribute('aria-label','Vollbild ein / aus');full.onclick=()=>{
      if(document.fullscreenElement)leaveMatchFullscreen();
      else{fullscreenDismissed='';enterFullscreen();}
    };
    full.style.cssText='border:0;background:transparent;color:#cce6ff;padding:0 5px;cursor:pointer;font-size:18px';
    const heading=document.createElement('div');heading.style.cssText='display:flex;align-items:center;gap:7px';heading.append(title,full);
    const fullStatus=document.createElement('p');fullStatus.dataset.fullscreenStatus='';fullStatus.style.cssText='margin:6px 0;font-size:11px';
    details.append(status,setup,pause,fullStatus);panel.append(heading,details);renderFold();document.body.append(panel);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
  setInterval(tick,4000);
})();
