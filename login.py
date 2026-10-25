"""
X (Twitter) Manual Login Assistant for X-VibeBot.
Launches your default browser (Brave, Chrome, or Edge) with your bot profile so you can log into X.
"""
import os
import sys
import time
import subprocess
import asyncio
from browser_worker import get_default_chromium_path

async def main():
    browser_path = get_default_chromium_path()
    browser_name = (
        "Brave Browser" if "brave" in (browser_path or "").lower()
        else ("Google Chrome" if "chrome" in (browser_path or "").lower()
        else ("Microsoft Edge" if "edge" in (browser_path or "").lower()
        else "Chromium"))
    )

    print("=" * 65)
    print("       X-VIBEBOT: MANUAL X (TWITTER) LOGIN LAUNCHER")
    print("=" * 65)
    print(f"\n[1/3] Detected default browser: {browser_name}")
    if browser_path:
        print(f"      Path: {browser_path}")
    else:
        print("      Path: Using Playwright bundled Chromium")

    profile_dir = os.path.abspath("./x_browser_profile")
    os.makedirs(profile_dir, exist_ok=True)

    print(f"\n[2/3] Opening {browser_name} window on your screen...")
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        launch_kwargs = {
            "user_data_dir": profile_dir,
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox"
            ],
            "no_viewport": True
        }
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"[3/3] Navigating to https://x.com/login in {browser_name} ...")
        try:
            await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation notice: {e}")

        print("\n" + "=" * 65)
        print(f" [OK] {browser_name} is now open on your desktop!")
        print(" 1. Sign into your X (Twitter) account in the browser window.")
        print(" 2. Once you reach your home feed, close the browser window.")
        print(" 3. Your cookies and session will be saved in ./x_browser_profile.")
        print("=" * 65 + "\n")

        # Keep running until the user closes the browser window
        while True:
            try:
                if not context.pages:
                    break
                _ = context.pages[0].url
                await asyncio.sleep(1.0)
            except Exception:
                break

        print(f"\n[DONE] {browser_name} closed. Session saved permanently into ./x_browser_profile!")
        print("You can now return to the dashboard (http://localhost:8000) and start the agent.")

if __name__ == "__main__":
    asyncio.run(main())
