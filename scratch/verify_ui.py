import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        # 1. Desktop Auth View
        context_desktop = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context_desktop.new_page()
        await page.goto("http://localhost:8000")
        await page.evaluate("""() => {
            localStorage.clear();
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page.reload()
        await page.wait_for_timeout(2000)
        
        # Check title
        title = await page.title()
        content = await page.content()
        print("Page title:", title)
        print("Has 'Sign in':", "Sign in to your Creator Studio" in content)
        
        # Capture auth screenshot
        await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_auth_dark.png")
        print("Captured charcoal_auth_dark.png")
        
        # 2. Authenticate by setting xvibebot_auth_token and xvibebot_user_email
        await page.evaluate("""() => {
            localStorage.setItem('xvibebot_auth_token', 'demo-token-alex');
            localStorage.setItem('xvibebot_user_email', 'alex@creator.io');
            localStorage.setItem('xvibebot_tenant_id', 'creator-alex');
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page.reload()
        await page.wait_for_timeout(2000)
        
        # Click Settings Tab
        settings_button = page.locator("button:has-text('Settings')")
        if await settings_button.count() > 0:
            await settings_button.first.click()
            await page.wait_for_timeout(1000)
            await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_settings_dark.png")
            print("Captured charcoal_settings_dark.png")

        # 3. Mobile View (iPhone 13 / 390x844) - Dashboard
        context_mobile = await browser.new_context(
            viewport={'width': 390, 'height': 844},
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
        )
        page_mobile = await context_mobile.new_page()
        await page_mobile.goto("http://localhost:8000")
        await page_mobile.evaluate("""() => {
            localStorage.setItem('xvibebot_auth_token', 'demo-token-alex');
            localStorage.setItem('xvibebot_user_email', 'alex@creator.io');
            localStorage.setItem('xvibebot_tenant_id', 'creator-alex');
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page_mobile.reload()
        await page_mobile.wait_for_timeout(2000)
        await page_mobile.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_dashboard_dark.png")
        print("Captured charcoal_mobile_dashboard_dark.png")

        # 4. Mobile View - Auth
        await page_mobile.evaluate("""() => {
            localStorage.clear();
            localStorage.setItem('xvibebot_theme', 'dark');
            document.documentElement.classList.add('dark');
        }""")
        await page_mobile.reload()
        await page_mobile.wait_for_timeout(2000)
        await page_mobile.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_mobile_auth_dark.png")
        print("Captured charcoal_mobile_auth_dark.png")

        await browser.close()
        print("All screenshots captured successfully!")

if __name__ == "__main__":
    asyncio.run(main())
