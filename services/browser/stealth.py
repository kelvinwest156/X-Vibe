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
    """Applies playwright-stealth v2 overrides cleanly to mask automation signatures."""
    stealth_applied = False
    try:
        from playwright_stealth import Stealth
        await Stealth().apply_stealth_async(page)
        stealth_applied = True
    except Exception as exc:
        logger.debug(f"playwright-stealth apply notice: {exc}")

    try:
        if stealth_applied:
            await page.add_init_script("""
                if (navigator.webdriver) {
                    try {
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined,
                            configurable: true
                        });
                    } catch (_) {}
                }
            """)
        else:
            await page.add_init_script("""
                if (navigator.webdriver) {
                    try {
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined,
                            configurable: true
                        });
                    } catch (_) {}
                }
                try {
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en'],
                        configurable: true
                    });
                } catch (_) {}
            """)
    except Exception as exc:
        logger.debug(f"Stealth init_script fallback notice: {exc}")


async def human_delay(min_sec: float = 0.5, max_sec: float = 1.4):
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
    with variable steps (12-18) and natural hand micro-jitter (±1.5px).
    Returns the new current mouse coordinates (target_x, target_y).
    """
    steps = random.randint(12, 18)
    ctrl1_x = start_x + (target_x - start_x) * random.uniform(0.20, 0.45) + random.uniform(-25, 25)
    ctrl1_y = start_y + (target_y - start_y) * random.uniform(0.15, 0.40) + random.uniform(-25, 25)
    ctrl2_x = start_x + (target_x - start_x) * random.uniform(0.55, 0.85) + random.uniform(-20, 20)
    ctrl2_y = start_y + (target_y - start_y) * random.uniform(0.60, 0.85) + random.uniform(-20, 20)

    for step in range(1, steps + 1):
        t = step / steps
        inv = 1.0 - t
        bx = (inv ** 3) * start_x + 3 * (inv ** 2) * t * ctrl1_x + 3 * inv * (t ** 2) * ctrl2_x + (t ** 3) * target_x
        by = (inv ** 3) * start_y + 3 * (inv ** 2) * t * ctrl1_y + 3 * inv * (t ** 2) * ctrl2_y + (t ** 3) * target_y
        if step < steps:
            bx += random.uniform(-1.5, 1.5)
            by += random.uniform(-1.5, 1.5)
        try:
            await page.mouse.move(max(1.0, bx), max(1.0, by))
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.003, 0.009))

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
        await asyncio.sleep(random.uniform(0.04, 0.12))
        await page.mouse.click(tx, ty, delay=random.randint(25, 60))
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
    Fast and natural: ~0.8s to 1.6s.
    """
    read_seconds = max(0.6, min(1.6, text_length / 160.0)) + random.uniform(0.1, 0.35)
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
        await page.mouse.wheel(0, random.randint(50, 150))
    except Exception:
        pass
    await asyncio.sleep(read_seconds * 0.55)
    return new_pos


async def _ensure_element_focus(element) -> None:
    """Verifies that `element` (or a child inside it) holds focus, focusing it if not."""
    try:
        is_focused = await element.evaluate(
            "el => el === document.activeElement || el.contains(document.activeElement)"
        )
        if is_focused is False:
            await element.focus()
            await asyncio.sleep(0.05)
    except Exception:
        try:
            await element.focus()
        except Exception:
            pass


async def human_type(
    page: Page,
    selector: str,
    text: str,
    current_mouse_pos: tuple[float, float]
) -> tuple[float, float]:
    """
    Types text character-by-character with natural fast bursts and curved mouse focus.
    Uses Shift+Enter for newlines so X inputs never accidentally submit mid-draft.
    """
    element = await page.wait_for_selector(selector, state="visible", timeout=15000)
    if not element:
        raise RuntimeError(f"Input element not visible for selector: {selector}")

    new_pos = await human_click(page, element, current_mouse_pos)
    await _ensure_element_focus(element)
    await human_delay(0.15, 0.35)

    clean_text = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    for i, char in enumerate(clean_text):
        if char == "\n":
            await page.keyboard.press("Shift+Enter")
            await asyncio.sleep(random.uniform(0.05, 0.12))
            continue

        # Micro typo-slip simulation (0.6% chance, strictly mid-word so Backspace never crosses line boundaries)
        if (
            i > 0
            and clean_text[i - 1].isalpha()
            and char.isalpha()
            and char.islower()
            and random.random() < 0.006
        ):
            wrong_char = random.choice("aeiourstln")
            if wrong_char != char:
                await page.keyboard.type(wrong_char)
                await asyncio.sleep(random.uniform(0.025, 0.05))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.02, 0.04))

        await page.keyboard.type(char)
        # Fast natural human cadence (10-25ms per character)
        delay = random.uniform(0.008, 0.022)
        if char in " ,.!?":
            delay += random.uniform(0.02, 0.05)
        elif i > 0 and i % random.randint(22, 38) == 0:
            delay += random.uniform(0.04, 0.09)  # Brief thinking micro-pause
        await asyncio.sleep(delay)

    return new_pos
