"""
X (Twitter) Manual Login Assistant for X-VibeBot.
Launches a visible Chromium window on your desktop with your bot profile so you can log into X.
"""
import os
import sys
import time
import subprocess
import asyncio

def kill_lingering_chrome():
    """Releases profile locks if Chrome was left running in background."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)
        except Exception:
            pass

async def main():
    print("=" * 65)
    print("       X-VIBEBOT: MANUAL X (TWITTER) LOGIN LAUNCHER")
    print("=" * 65)
    print("\n[1/3] Ensuring profile lock is free...")
    kill_lingering_chrome()

    print("[2/3] Launching Chromium browser on your screen...")
    profile_dir = os.path.abspath("./x_browser_profile")
    os.makedirs(profile_dir, exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox"
            ],
            no_viewport=True
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print("[3/3] Navigating to https://x.com/login ...")
        try:
            await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Notice: {e}")

        print("\n" + "=" * 65)
        print(" [OK] Browser is open on your desktop!")
        print(" 1. Sign into your X (Twitter) account in the Chromium window.")
        print(" 2. Once you see your home feed, close the browser window.")
        print(" 3. Your cookies and session will be saved in ./x_browser_profile.")
        print("=" * 65 + "\n")

        # Keep running until the user closes the browser window
        while True:
            try:
                if not context.pages:
                    break
                # Poll active page
                _ = context.pages[0].url
                await asyncio.sleep(1.0)
            except Exception:
                break

        print("\n[DONE] Browser closed. Session saved permanently into ./x_browser_profile!")
        print("You can now return to the dashboard and start the agent.")

if __name__ == "__main__":
    asyncio.run(main())
