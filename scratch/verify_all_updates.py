import asyncio
from playwright.async_api import async_playwright

VALID_TOKEN = "eyJ1aWQiOiJ1X2FsZXgiLCJlbWFpbCI6ImFsZXhAY3JlYXRvci5pbyIsInRlbmFudF9pZCI6ImNyZWF0b3ItYWxleCIsImV4cCI6MTgyNDczODA1OH0.d3d1cc07f019db3ed3f056e434aada43c16fe807cdc9e3eae63cc4c3a49bf9b1"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        # 1. Desktop Dashboard with Log Out button in header
        context_desktop = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context_desktop.new_page()
        await page.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
        await page.evaluate(f"""() => {{
            localStorage.setItem('xvibebot_auth_token', '{VALID_TOKEN}');
            localStorage.setItem('xvibebot_user_email', 'alex@creator.io');
            localStorage.setItem('xvibebot_tenant_id', 'creator-alex');
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }}""")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_dashboard_with_logout.png")
        print("Captured charcoal_dashboard_with_logout.png")

        # 2. Desktop Settings View showing Account & Session section
        settings_button = page.locator("button:has-text('Settings')")
        if await settings_button.count() > 0:
            await settings_button.first.click()
            await page.wait_for_timeout(800)
            await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_settings_with_session.png")
            print("Captured charcoal_settings_with_session.png")

        # 3. Mobile View showing Log Out icon in header
        context_mobile = await browser.new_context(
            viewport={'width': 390, 'height': 844},
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
        )
        page_mobile = await context_mobile.new_page()
        await page_mobile.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
        await page_mobile.evaluate(f"""() => {{
            localStorage.setItem('xvibebot_auth_token', '{VALID_TOKEN}');
            localStorage.setItem('xvibebot_user_email', 'alex@creator.io');
            localStorage.setItem('xvibebot_tenant_id', 'creator-alex');
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }}""")
        await page_mobile.reload(wait_until="domcontentloaded")
        await page_mobile.wait_for_timeout(1500)
        await page_mobile.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_with_logout.png")
        print("Captured charcoal_mobile_with_logout.png")

        await browser.close()
        print("All verification screenshots captured!")

if __name__ == "__main__":
    asyncio.run(main())
