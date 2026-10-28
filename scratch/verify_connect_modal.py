import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
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

        # 1. Click "Connect X Account" button
        connect_btn = page.locator("button:has-text('Connect X Account')")
        if await connect_btn.count() > 0:
            print("Found Connect X Account button, clicking...")
            await connect_btn.first.click()
            await page.wait_for_timeout(600)
            
            # Capture modal open (Tab 1: Token Sync)
            await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_connect_modal.png")
            print("Captured charcoal_connect_modal.png")
            
            # Expand how-to guide
            guide_btn = page.locator("button:has-text('How to get your X auth_token in 10 seconds')")
            if await guide_btn.count() > 0:
                await guide_btn.first.click()
                await page.wait_for_timeout(400)
                await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_connect_modal_guide.png")
                print("Captured charcoal_connect_modal_guide.png")

            # Click "Browser Window" tab
            desktop_tab = page.locator("button:has-text('Browser Window')")
            if await desktop_tab.count() > 0:
                await desktop_tab.first.click()
                await page.wait_for_timeout(400)
                await page.screenshot(path=r"C:\Users\Administrator\.gemini\antigravity\brain\8bc5776f-9fd8-4ce3-8460-adc0e59e88e3\charcoal_connect_modal_desktop.png")
                print("Captured charcoal_connect_modal_desktop.png")
        else:
            print("Button not found! Checking page buttons...")
            btns = await page.locator("button").all_inner_texts()
            print("Buttons on page:", btns[:15])

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
