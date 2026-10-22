"""Local integration check for the password-free portal."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chromium")
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto('http://127.0.0.1:8000')
        await page.locator('#name').fill('Browser-Test')
        await page.get_by_role('button', name='Spieler hinzufügen').click()
        try:
            await page.wait_for_function("document.querySelector('#frame').hasAttribute('src')", timeout=90000)
            assert await page.locator('#connection').inner_text() == 'Sitzung aktiv'
            await page.wait_for_timeout(5000)
            print('PASS: Portal-Anmeldung, echte getrennte Browser-Sitzung und Bildschirmübertragung')
            await page.screenshot(path='data/portal-preview.png', full_page=True)
        finally:
            page.once('dialog', lambda dialog: dialog.accept())
            await page.locator('#delete').click()
            await page.wait_for_function("document.querySelector('#empty').hidden === false")
            await browser.close()

asyncio.run(main())
