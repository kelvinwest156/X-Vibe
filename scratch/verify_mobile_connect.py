import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={'width': 390, 'height': 844},
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
        )
        page = await context.new_page()

        await page.goto("http://localhost:8000", wait_until="domcontentloaded")
        await page.evaluate("""() => {
            localStorage.setItem('xvibebot_auth_token', 'demo-token-alex');
            localStorage.setItem('xvibebot_user_email', 'alex@creator.io');
            localStorage.setItem('xvibebot_tenant_id', 'creator-alex');
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # On mobile, click the visible "Connect" button in the quick action bar
        connect_btn = page.locator("button:visible:has-text('Connect')")
        if await connect_btn.count() > 0:
            print("Found mobile visible Connect button, clicking...")
            await connect_btn.first.click()
            await page.wait_for_timeout(600)
            
            # Capture modal on mobile
            await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_connect_modal.png")
            print("Captured charcoal_mobile_connect_modal.png")

        await browser.close()
        print("Mobile verification complete!")

if __name__ == "__main__":
    asyncio.run(main())
