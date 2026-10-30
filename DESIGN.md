---
version: alpha
name: X-VibeBot Studio
description: Clean monochrome design system for X-VibeBot AI studio and onboarding.
colors:
  canvas: "#fafafa"
  card: "#ffffff"
  line: "#e4e4e7"
  ink: "#111111"
  ink-secondary: "#52525b"
  ink-muted: "#a1a1aa"
  accent: "#ea580c"
  success: "#10b981"
  error: "#f43f5e"
typography:
  sans:
    fontFamily: Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif
  display:
    fontFamily: Plus Jakarta Sans, Inter, sans-serif
  mono:
    fontFamily: JetBrains Mono, monospace
rounded:
  base: 0.75rem
  lg: 1rem
  full: 9999px
---

# Design System

## Overview
X-VibeBot delivers an industry-standard, focused AI workspace for social creators and indie builders. Its visual language eliminates clutter, relying on strict monochrome surfaces (#0E0E0E in dark mode, #FAFAFA in light mode) paired with deliberate high-contrast micro-affordances in warm signal orange (#EA580C) and verified emerald (#10B981).

## Colors
- Use `--canvas` for screen and viewport backgrounds.
- Use `--card` for content modules, input surfaces, and dialogs.
- Use `--line` for hairline dividers and 1px borders.
- Use `--ink` for primary headings and prominent labels.
- Use `--ink-2` for descriptive subtext, timestamps, and secondary controls.
- Use `--accent` (#EA580C) strictly for active operational states, draft indicators, and warm action accents.
- Use `--success` (#10B981) strictly for verified session status and live operational flags.

## Themes
| Token | Light Value | Dark Value | Purpose |
|---|---|---|---|
| `--canvas` | `#fafafa` | `#0E0E0E` | Page root & app background |
| `--card` | `#ffffff` | `#171717` | Cards, dialogs & panels |
| `--line` | `#e4e4e7` | `#262626` | 1px borders & dividers |
| `--ink` | `#111111` | `#F5F5F5` | Headings & primary text |
| `--ink-2` | `#52525b` | `#9E9E9E` | Secondary body text |
| `--ink-3` | `#a1a1aa` | `#6E6E6E` | Micro text & placeholders |

## Typography
- Apply `font-display` (`Plus Jakarta Sans`) to major onboarding and studio section headings with `text-balance`.
- Apply `font-sans` (`Inter`) to all UI controls, body copy, and labels with `text-pretty`.
- Apply `font-mono` (`JetBrains Mono`) with `tabular-nums` to usernames, handles, token counts, character metrics, and system log streams.

## Layout
- Use `h-dvh` or `min-h-dvh` for full-height viewports; never use `h-screen`.
- Maintain a single-column focused form structure on mobile and a balanced 2-column split (provisioning ledger on left, interaction card on right) at `lg:` viewports.
- Keep primary content cards centered with `max-w-[420px]` on onboarding and `max-w-6xl` on the Studio dashboard.

## Elevation & Depth
- Rely primarily on 1px borders (`border-[#E4E4E7]` light / `border-[#262626]` dark) rather than diffuse colored dropshadows.
- Use shallow neutral elevation (`shadow-xs` / `shadow-[0_1px_2px_rgba(0,0,0,0.03)]`) for interactive cards.
- Restrict blur layers to low-radius backdrop overlays (`backdrop-blur-xs`) on modal backdrops.

## Motion & Interaction
- Animate only GPU compositor properties: `opacity`, `transform` (`y`, `scale`).
- Keep entrance micro-durations under 200ms (`duration-160` or `0.2s`).
- Honor `prefers-reduced-motion` across all transition loops.
- Never animate layout properties (`height`, `width`, `margin`, `padding`).

## Do's and Don'ts
### Do:
- Use `text-balance` for headings and `text-pretty` for paragraph text.
- Provide clear accessible names (`aria-label`) on all icon-only buttons.
- Connect form feedback banners using `role="alert"` and `aria-live="polite"`.
- Keep authentication and connection flows focused on direct interactive browser window verification.

### Don't:
- Never use multi-colored or purple gradient backgrounds.
- Never use neon glow effects as primary interaction affordances.
- Never show raw token copy-paste forms when a direct browser sign-in window is available.
- Never leave modal dialogs without keyboard `Escape` listeners or `role="dialog"`.
