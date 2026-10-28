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
        await page.goto("http://localhost:8000")
        await page.evaluate("""() => {
            localStorage.setItem('xvibebot_auth_token', 'demo-token-alex');
            localStorage.setItem('xvibebot_user_email', 'alex@creator.io');
            localStorage.setItem('xvibebot_tenant_id', 'creator-alex');
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page.reload()
        await page.wait_for_timeout(1000)
        
        # Click Queue Tab using visible locator
        queue_tab = page.locator("button:visible:has-text('Queue')")
        if await queue_tab.count() > 0:
            await queue_tab.first.click()
            await page.wait_for_timeout(500)
            await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_queue_dark.png")
            print("Captured charcoal_mobile_queue_dark.png")
            
        # Click Settings Tab using visible locator
        settings_tab = page.locator("button:visible:has-text('Settings')")
        if await settings_tab.count() > 0:
            await settings_tab.first.click()
            await page.wait_for_timeout(500)
            await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_settings_dark.png")
            print("Captured charcoal_mobile_settings_dark.png")

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
