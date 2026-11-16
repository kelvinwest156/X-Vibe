"""
X (Twitter) Manual Login Assistant for X-VibeBot.
Launches your default browser (Brave, Chrome, or Edge) with your bot profile so you can log into X.
"""
import sys
import os
import asyncio

# Ensure project root is in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Critical fix for Windows: Playwright subprocesses require ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import time
import urllib.request
from browser_worker import get_default_chromium_path, kill_profile_browser_processes


def notify_server(endpoint: str):
    """Notifies the local FastAPI server (if running) to release or re-check the browser profile."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:8000{endpoint}", method="POST")
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass


def pause_background_agent():
    """
    Pauses the background agent in SQLite and notifies the local server
    so it does not compete for ./x_browser_profile while the user is logging in.
    """
    try:
        from database import SessionLocal, get_agent_config
        db = SessionLocal()
        try:
            cfg = get_agent_config(db)
            if cfg.is_active:
                cfg.is_active = False
                db.commit()
        finally:
            db.close()
    except Exception:
        pass
    notify_server("/api/browser/release")


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
    print(f"\n[1/4] Detected default browser: {browser_name}")
    if browser_path:
        print(f"      Path: {browser_path}")
    else:
        print("      Path: Using Playwright bundled Chromium")

    env_profile = os.getenv("BROWSER_PROFILE_DIR")
    if env_profile:
        profile_dir = os.path.abspath(env_profile)
    elif os.path.exists(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile")):
        profile_dir = os.path.abspath(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile"))
    elif os.path.exists(os.path.join(BASE_DIR, "x_browser_profile")):
        profile_dir = os.path.abspath(os.path.join(BASE_DIR, "x_browser_profile"))
    else:
        profile_dir = os.path.abspath(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile"))
    os.makedirs(profile_dir, exist_ok=True)

    print(f"\n[2/4] Releasing any existing lock on {profile_dir}...")
    pause_background_agent()
    kill_profile_browser_processes(profile_dir)
    await asyncio.sleep(1.0)

    print(f"\n[3/4] Opening {browser_name} window on your screen...")
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

        try:
            context = await p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            if "ProcessSingleton" in str(e) or "0x20" in str(e):
                print("      Cleaning up lingering profile lock and retrying...")
                kill_profile_browser_processes(profile_dir)
                await asyncio.sleep(1.5)
                context = await p.chromium.launch_persistent_context(**launch_kwargs)
            else:
                raise

        page = context.pages[0] if context.pages else await context.new_page()

        print(f"[4/4] Navigating to https://x.com/login in {browser_name} ...")
        try:
            await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation notice: {e}")

        print("\n" + "=" * 65)
        print(f" [OK] {browser_name} is now open on your desktop!")
        print(" 1. Sign into your X (Twitter) account in the browser window.")
        print(" 2. Once you reach your home feed, close the browser window.")
        print(f" 3. Your cookies and session will be saved in: {profile_dir}")
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

        print(f"\n[DONE] {browser_name} closed. Session saved permanently into {profile_dir}!")
        notify_server("/api/browser/check-session")
        print("You can now return to the dashboard (http://localhost:8000) and start the agent.")

if __name__ == "__main__":
    asyncio.run(main())
