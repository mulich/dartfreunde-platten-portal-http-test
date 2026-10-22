// ==UserScript==
// @name         Dartfreunde Platten – Spieler automatisch lokal
// @namespace    dartfreunde-platten
// @version      1.0.0
// @description  Stellt eingeladene Spieler in privaten Gastgeber-Lobbys auf das Gastgeber-Board um.
// @match        https://play.autodarts.com/*
// @match        https://play.autodarts.io/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(() => {
  'use strict';
  const SETTINGS_KEY = 'dartfreunde-platten-local-players-v1';
  const DEFAULTS = { enabled: true, hosts: ['rot', 'schwarz', 'blau'] };

  function ancestors(element) {
    const key = Object.keys(element).find(k => k.startsWith('__reactFiber$'));
    const result = [];
    let fiber = key ? element[key] : null;
    // Read only committed props; do not invoke internal callbacks or change state.
    for (let depth = 0; fiber && depth < 100; depth++, fiber = fiber.return) {
      if (fiber.memoizedProps) result.push(fiber.memoizedProps);
    }
    return result;
  }

  function isLobby(value, id) {
    return value && value.id === id && typeof value.host?.id === 'string'
      && Array.isArray(value.players) && typeof value.setHostForIndex === 'function';
  }

  function scan(doc, pathname, settings) {
    const match = /^\/lobby\/([^/]+)\/?$/.exec(pathname);
    if (!match) return { message: 'Wartet auf eine Lobby', targets: [] };
    if (!settings.enabled) return { message: 'Automatik aus', targets: [] };
    const id = match[1];
    let lobby = null;
    let ownLobby = false;
    const rows = [];
    for (const button of doc.querySelectorAll('button')) {
      if (!button.isConnected || !button.getClientRects().length) continue;
      const props = ancestors(button);
      // The new lobby's native Start component receives the authenticated isHost.
      if (props.some(p => p.isHost === true && typeof p.onStart === 'function'
        && typeof p.hasNoPlayers === 'boolean' && typeof p.hasPendingPlayers === 'boolean')) {
        ownLobby = true;
      }
      for (const p of props) {
        if (isLobby(p.lobby, id)) lobby = p.lobby;
        if (isLobby(p.value, id)) lobby = p.value;
      }
      if (button.disabled || button.getAttribute('aria-disabled') === 'true'
        || !button.querySelector('svg[data-icon="globe"]')) continue;
      const row = props.find(p => p.player && typeof p.onLink === 'function'
        && typeof p.onUnlink === 'function' && typeof p.onRemove === 'function');
      if (row) rows.push({ button, player: row.player });
    }
    if (!lobby || !ownLobby) return { message: 'Keine eigene Lobby erkannt', targets: [] };
    if (lobby.isPrivate !== true || lobby.tournamentId) {
      return { message: 'Nur private Lobbys ohne Turnierzuordnung', targets: [] };
    }
    const hosts = settings.hosts.map(s => s.trim().toLocaleLowerCase());
    if (!hosts.includes(lobby.host.id.toLocaleLowerCase())
      && !hosts.includes((lobby.host.name || '').toLocaleLowerCase())) {
      return { message: 'Gastgeber ist nicht freigegeben', targets: [] };
    }
    const targets = rows.filter(({ player }) =>
      typeof player.userId === 'string' && player.userId
      && player.userId !== lobby.host.id && player.hostId !== lobby.host.id
      && !player.isPending && !player.cpuPPR
      && lobby.players.includes(player));
    const remote = lobby.players.filter(player => player.userId
      && player.userId !== lobby.host.id && player.hostId !== lobby.host.id
      && !player.isPending && !player.cpuPPR);
    return { lobbyId: id, targets, message: targets.length
      ? `${targets.length} Spieler werden lokal zugeordnet`
      : remote.length ? 'Globus-Schaltfläche nicht erkannt; manuell prüfen'
        : 'Alle erkannten Spieler sind lokal' };
  }

  // Export the detector only for isolated browser fixtures, without running it.
  if (typeof module === 'object' && module.exports) {
    module.exports = { scan };
    return;
  }
  let settings;
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || 'null');
    settings = { ...DEFAULTS, ...saved };
    if (!Array.isArray(settings.hosts) || !settings.hosts.every(h => typeof h === 'string')) {
      settings.hosts = [...DEFAULTS.hosts];
    }
  } catch { settings = { ...DEFAULTS }; }
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;left:12px;bottom:90px;z-index:10000;max-width:280px;padding:10px;border:1px solid #8ed3ff;border-radius:10px;background:#102235;color:#e6f4ff;font:12px system-ui;box-shadow:0 2px 10px #0005;';
  const toggle = document.createElement('button');
  const configure = document.createElement('button');
  const status = document.createElement('div');
  status.setAttribute('role', 'status');
  for (const button of [toggle, configure]) {
    button.type = 'button';
    button.style.cssText = 'background:#8ed3ff;color:#102235;border:0;border-radius:5px;padding:5px 8px;cursor:pointer;margin:0 5px 6px 0;font:inherit;';
  }
  configure.textContent = 'Board-Accounts';
  panel.append(toggle, configure, status);
  const attempts = new Map();
  let busy = false;
  let route = '';
  function save() {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    toggle.textContent = `Spieler lokal: ${settings.enabled ? 'AN' : 'AUS'}`;
  }
  toggle.onclick = () => { settings.enabled = !settings.enabled; attempts.clear(); save(); };
  configure.onclick = () => {
    const value = prompt('Erlaubte Gastgeber: Autodarts-Namen oder IDs, durch Komma getrennt.', settings.hosts.join(', '));
    if (value === null) return;
    settings.hosts = value.split(',').map(s => s.trim()).filter(Boolean);
    attempts.clear(); save();
  };
  save();
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function tick() {
    if (!document.body) return;
    const inLobby = /^\/lobby\/[^/]+\/?$/.test(location.pathname);
    panel.hidden = !inLobby;
    if (inLobby && !panel.isConnected) document.body.append(panel);
    if (route !== location.pathname) { route = location.pathname; attempts.clear(); }
    if (busy || !inLobby) return;
    const result = scan(document, location.pathname, settings);
    status.textContent = result.message;
    const target = result.targets.find(({ player }) => {
      const previous = attempts.get(`${result.lobbyId}:${player.userId}`);
      return !previous || previous.count < 3 && Date.now() - previous.time > 15000;
    });
    if (!target) {
      if (result.targets.length) status.textContent = 'Zuordnung noch nicht bestätigt; ggf. manuell prüfen';
      return;
    }
    busy = true;
    const key = `${result.lobbyId}:${target.player.userId}`;
    const previous = attempts.get(key);
    attempts.set(key, { time: Date.now(), count: (previous?.count || 0) + 1 });
    try {
      // Recheck immediately before clicking; never press a house or Start button.
      const fresh = scan(document, location.pathname, settings);
      if (!fresh.targets.some(t => t.button === target.button) || fresh.lobbyId !== result.lobbyId) return;
      target.button.click();
      status.textContent = 'Lokale Zuordnung angefordert …';
      await delay(1200);
    } finally { busy = false; }
  }
  setInterval(() => tick().catch(() => {
    status.textContent = 'Lobby-Struktur nicht erkannt; manuell zuordnen';
  }), 1500);
  tick().catch(() => { status.textContent = 'Lobby wird geladen …'; });
})();
