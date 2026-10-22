"""Exercise the detector in real Chromium with notification-shaped UI fixtures.

No requests reach Autodarts and no real invitations are accepted.
"""
import asyncio
from playwright.async_api import async_playwright
from app.invitations import SCAN


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel='chromium')
        page = await browser.new_page()
        await page.route('**/*', lambda route: route.fulfill(body='<main><button>Accept</button><button>Decline</button><button>Join</button></main>', content_type='text/html'))
        await page.goto('https://play.autodarts.com/')
        await page.evaluate('''() => {
          const buttons = document.querySelectorAll('button');
          const invite = {id:'lobby-notice', type:'lobby:invite', body:{user:{id:'u', name:'rot'}, lobby:{id:'l'}}};
          const friend = {id:'friend-notice', type:'friend-list:request', body:{user:{id:'u',name:'rot'}}};
          buttons[0].__reactFiber$fixture = {memoizedProps:{}, return:{memoizedProps:{notification:invite}}};
          buttons[1].__reactFiber$fixture = buttons[0].__reactFiber$fixture;
          buttons[2].__reactFiber$fixture = {memoizedProps:{},return:{memoizedProps:{notification:friend}}};
        }''')
        result = await page.evaluate(SCAN)
        assert len(result['invites']) == 1 and result['invites'][0]['sender'] == 'rot'
        assert not result['busy']
        await page.evaluate("history.pushState({}, '', '/lobby/l')")
        assert (await page.evaluate(SCAN))['busy']
        await page.evaluate("history.pushState({}, '', '/matches/m')")
        assert (await page.evaluate(SCAN))['busy']
        await page.evaluate('''() => {
          document.querySelector('main').__reactFiber$fixture = {memoizedProps:{value:{state:{finished:true}}}};
        }''')
        assert not (await page.evaluate(SCAN))['busy']
        # Unknown/new notification structures must never become join targets.
        await page.evaluate("document.querySelectorAll('button').forEach(b => delete b.__reactFiber$fixture)")
        assert (await page.evaluate(SCAN))['invites'] == []
        assert await page.locator('[data-portal-invitation]').count() == 0
        await browser.close()
        print('PASS: Lobby-Einladung erkannt; Freundesanfrage, laufendes Match, Lobby und unbekannte Struktur geschützt')


asyncio.run(main())
