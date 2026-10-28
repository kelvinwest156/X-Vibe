import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        # 1. Desktop Auth View
        context_desktop = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context_desktop.new_page()
        await page.goto("http://localhost:8000", wait_until="domcontentloaded")
        await page.evaluate("""() => {
            localStorage.clear();
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_auth_dark.png")
        print("Captured charcoal_auth_dark.png")

        # 2. Mobile Auth View
        context_mobile = await browser.new_context(
            viewport={'width': 390, 'height': 844},
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
        )
        page_mobile = await context_mobile.new_page()
        await page_mobile.goto("http://localhost:8000", wait_until="domcontentloaded")
        await page_mobile.evaluate("""() => {
            localStorage.clear();
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page_mobile.reload(wait_until="domcontentloaded")
        await page_mobile.wait_for_timeout(1500)
        await page_mobile.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_auth_dark.png")
        print("Captured charcoal_mobile_auth_dark.png")

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
