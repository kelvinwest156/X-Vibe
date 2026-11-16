"""
Browser Stealth & Human Biometrics Simulation Service for X-VibeBot.
Simulates randomized Cubic Bézier mouse trajectories, micro-jitters, variable typing
bursts with occasional typos, reading dwell intervals, and stealth DOM patches.
"""

import random
import asyncio
import logging
from playwright.async_api import Page

logger = logging.getLogger("x_vibebot.services.browser.stealth")


async def apply_stealth(page: Page):
    """Applies stealth overrides to mask automation signatures."""
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except Exception:
        pass

    try:
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = {
                runtime: {}
            };
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)
    except Exception:
        pass


async def human_delay(min_sec: float = 2.5, max_sec: float = 6.0):
    """Randomized human-like pause."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def move_mouse_humanlike(
    page: Page,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float
) -> tuple[float, float]:
    """
    Anti-Detection Biometrics: Moves the cursor along a randomized Cubic Bézier curve
    with variable steps (18-30) and natural hand micro-jitter (±2.5px).
    Returns the new current mouse coordinates (target_x, target_y).
    """
    steps = random.randint(18, 30)
    ctrl1_x = start_x + (target_x - start_x) * random.uniform(0.20, 0.45) + random.uniform(-45, 45)
    ctrl1_y = start_y + (target_y - start_y) * random.uniform(0.15, 0.40) + random.uniform(-45, 45)
    ctrl2_x = start_x + (target_x - start_x) * random.uniform(0.55, 0.85) + random.uniform(-35, 35)
    ctrl2_y = start_y + (target_y - start_y) * random.uniform(0.60, 0.85) + random.uniform(-35, 35)

    for step in range(1, steps + 1):
        t = step / steps
        inv = 1.0 - t
        bx = (inv ** 3) * start_x + 3 * (inv ** 2) * t * ctrl1_x + 3 * inv * (t ** 2) * ctrl2_x + (t ** 3) * target_x
        by = (inv ** 3) * start_y + 3 * (inv ** 2) * t * ctrl1_y + 3 * inv * (t ** 2) * ctrl2_y + (t ** 3) * target_y
        if step < steps:
            bx += random.uniform(-2.5, 2.5)
            by += random.uniform(-2.5, 2.5)
        try:
            await page.mouse.move(max(1.0, bx), max(1.0, by))
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.006, 0.019))

    return target_x, target_y


async def human_click(page: Page, element, current_mouse_pos: tuple[float, float]) -> tuple[float, float]:
    """
    Glides the mouse along a Bézier curve into a randomized inner coordinate of `element`,
    pauses briefly like a human finger, and clicks.
    Returns the updated mouse position.
    """
    start_x, start_y = current_mouse_pos
    try:
        await element.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    box = None
    try:
        box = await element.bounding_box()
    except Exception:
        box = None

    if box and box.get("width", 0) > 4 and box.get("height", 0) > 4:
        tx = box["x"] + box["width"] * random.uniform(0.25, 0.75)
        ty = box["y"] + box["height"] * random.uniform(0.25, 0.75)
        new_pos = await move_mouse_humanlike(page, start_x, start_y, tx, ty)
        await asyncio.sleep(random.uniform(0.12, 0.36))
        await page.mouse.click(tx, ty, delay=random.randint(35, 95))
        return new_pos
    else:
        await element.click()
        return current_mouse_pos


async def simulate_reading_dwell(
    page: Page,
    text_length: int = 140,
    current_mouse_pos: tuple[float, float] = (640.0, 400.0)
) -> tuple[float, float]:
    """
    Simulates proportional human reading time and viewport dwell before any interaction.
    """
    read_seconds = max(2.4, min(8.5, text_length / 26.0)) + random.uniform(0.8, 2.2)
    await asyncio.sleep(read_seconds * 0.45)
    new_pos = current_mouse_pos
    try:
        new_pos = await move_mouse_humanlike(
            page,
            current_mouse_pos[0],
            current_mouse_pos[1],
            random.uniform(360, 820),
            random.uniform(240, 560)
        )
        await page.mouse.wheel(0, random.randint(75, 210))
    except Exception:
        pass
    await asyncio.sleep(read_seconds * 0.55)
    return new_pos


async def human_type(
    page: Page,
    selector: str,
    text: str,
    current_mouse_pos: tuple[float, float]
) -> tuple[float, float]:
    """Types text character-by-character with natural bursts, curved mouse focus, and occasional typo/backspace."""
    element = await page.wait_for_selector(selector, state="visible", timeout=15000)
    new_pos = await human_click(page, element, current_mouse_pos)
    await human_delay(0.4, 1.0)

    for i, char in enumerate(text):
        # 1.5% chance on lowercase letters to make a human key-slip and immediately backspace
        if char.isalpha() and char.islower() and random.random() < 0.015:
            wrong_char = random.choice("aeiourstln")
            if wrong_char != char:
                await page.keyboard.type(wrong_char)
                await asyncio.sleep(random.uniform(0.06, 0.16))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.05, 0.14))

        await page.keyboard.type(char)
        delay = random.uniform(0.03, 0.13)
        if char in " ,.!?":
            delay += random.uniform(0.08, 0.28)
        elif i > 0 and i % random.randint(12, 22) == 0:
            delay += random.uniform(0.15, 0.4)  # Brief thinking micro-pause
        await asyncio.sleep(delay)

    return new_pos
