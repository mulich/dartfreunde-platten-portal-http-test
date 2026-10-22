"""Real Chromium fixtures for the current public lobby's React props and icons.

No actual Autodarts accounts, boards, lobbies or network mutations are used.
"""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

SOURCE = (Path(__file__).parent.parent / 'app/static/autodarts-local-players.user.js').read_text()


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as runtime:
        instance = runtime.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def lobby_page(browser):
    page = browser.new_page()
    page.route('**/*', lambda route: route.fulfill(body='''<main>
      <button id="start">Start Game</button>
      <button id="remote"><svg data-icon="globe"></svg></button>
      <button id="local"><svg data-icon="house"></svg></button>
      <button id="remove">Remove</button>
      <button id="unrelated"><svg data-icon="globe"></svg></button>
    </main>''', content_type='text/html'))
    page.goto('https://play.autodarts.com/lobby/test-lobby')
    page.evaluate('''() => {
      const remote = {userId:'player-1',hostId:'player-1',name:'Anna'};
      const local = {userId:'player-2',hostId:'board-host',name:'Ben'};
      const lobby = {id:'test-lobby',host:{id:'board-host',name:'rot'},
        isPrivate:true,players:[remote,local],setHostForIndex:()=>{}};
      const root = {memoizedProps:{value:lobby}};
      const start = {memoizedProps:{isHost:true,onStart:()=>{},
        hasNoPlayers:false,hasPendingPlayers:false},return:root};
      document.querySelector('#start').__reactFiber$fixture = start;
      const row = {memoizedProps:{player:remote,onLink:()=>{},onUnlink:()=>{},onRemove:()=>{}},return:root};
      document.querySelector('#remote').__reactFiber$fixture = row;
      document.querySelector('#remove').__reactFiber$fixture = row;
      document.querySelector('#local').__reactFiber$fixture = {memoizedProps:{
        player:local,onLink:()=>{},onUnlink:()=>{},onRemove:()=>{}},return:root};
      window.fixture = {lobby,remote,local,start};
      window.clicks = [];
      for (const button of document.querySelectorAll('button')) {
        button.onclick = () => {window.clicks.push(button.id); if(button.id==='remote'){
          remote.hostId='board-host';
          button.querySelector('svg').setAttribute('data-icon','house');
        }};
      }
    }''')
    # Module branch exposes only the detector for assertions, no runtime/timer.
    page.evaluate('(source) => {const module={exports:{}}; eval(source); window.detector=module.exports.scan}', SOURCE)
    yield page
    page.close()


def scan(page):
    return page.evaluate('''() => {
      const result=detector(document,location.pathname,{enabled:true,hosts:['rot','schwarz','blau']});
      return {...result,targets:result.targets.map(t=>t.button.id)};
    }''')


def test_only_remote_player_globe_is_selected(lobby_page):
    assert scan(lobby_page)['targets'] == ['remote']
    lobby_page.evaluate('''() => {
      const result=detector(document,location.pathname,{enabled:true,hosts:['rot']});
      result.targets[0].button.click();
    }''')
    assert scan(lobby_page)['targets'] == []
    assert lobby_page.evaluate('clicks') == ['remote']


@pytest.mark.parametrize('change', [
    "fixture.start.memoizedProps.isHost=false",
    "fixture.lobby.isPrivate=false",
    "fixture.lobby.tournamentId='tournament'",
    "fixture.lobby.host.name='unknown'",
    "fixture.remote.isPending=true",
    "fixture.remote.cpuPPR=60",
    "document.querySelector('#remote').disabled=true",
    "document.querySelector('#remote').style.display='none'",
    "history.pushState({},'', '/matches/match')",
    "delete document.querySelector('#remote').__reactFiber$fixture",
])
def test_unsafe_or_unknown_conditions_do_not_select_players(lobby_page, change):
    lobby_page.evaluate(change)
    assert scan(lobby_page)['targets'] == []


def test_runtime_clicks_once_and_keeps_host(lobby_page):
    lobby_page.evaluate(SOURCE)
    lobby_page.wait_for_function("fixture.remote.hostId==='board-host'")
    lobby_page.wait_for_timeout(1700)
    assert lobby_page.evaluate('clicks') == ['remote']
    assert lobby_page.evaluate('fixture.lobby.players.length') == 2
    assert lobby_page.get_by_role('button', name='Spieler lokal: AN').is_visible()
    lobby_page.get_by_role('button', name='Spieler lokal: AN').click()
    assert lobby_page.get_by_role('button', name='Spieler lokal: AUS').is_visible()
