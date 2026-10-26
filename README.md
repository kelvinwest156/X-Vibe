# X-VibeBot: Monolithic AI Browser-Agent for X (Twitter)

**X-VibeBot** is a minimal, local-first browser-automation agent built with **FastAPI**, **Playwright**, and **Google Gemini AI** (`google-genai`). It automatically detects and launches your default Chromium browser (such as **Brave**, **Chrome**, or **Edge**) with a persistent profile, evaluates posts relevant to your chosen topic or search query, filters out spam/scams, and drafts witty 1–2 sentence replies for either human-in-the-loop review or full autopilot execution.

---

## 🏗️ Architecture & File Structure

```plaintext
Xbot/
│
├── main.py              # FastAPI monolith controller, background loop, & REST API routes
├── database.py          # SQLite database connection & query helpers (audit logs & deduplication)
├── models.py            # SQLAlchemy database tables & Pydantic request/response schemas
├── ai_engine.py         # Google Gemini AI engine (topic-aware prompting & sticky model failover)
├── browser_worker.py    # Default browser detection (Brave/Chrome/Edge), stealth & humanized typing
├── login.py             # Standalone manual X login launcher with automatic profile-lock cleanup
├── start_vibebot.bat    # One-click Windows launcher for the X-VibeBot server
├── login_browser.bat    # One-click Windows launcher to sign into X in your default browser
├── static/
│   └── index.html       # Minimal dark-mode dashboard (Tailwind CSS) with hover info tooltips
├── requirements.txt     # Python dependencies (FastAPI, Playwright, google-genai, SQLAlchemy)
├── .env.example         # Template configuration for API keys & runtime defaults
├── .env                 # Local configuration (auto-updated when saving from the dashboard)
├── vibebot.db           # Local SQLite database (stores settings, pending drafts, & audit history)
└── x_browser_profile/   # Persistent browser profile folder (stores X login cookies & session)
```

---

## 🚀 Quick Start Guide (Beginner-Friendly)

### 1. Install Dependencies
Run in your terminal:
```powershell
pip install -r requirements.txt
playwright install chromium
```

### 2. Get Your Free Google Gemini API Key
1. Visit **[Google AI Studio](https://aistudio.google.com/app/apikey)** and generate a free API key.
2. You can paste it directly into the **Dashboard Sidebar** (`http://localhost:8000`) and click **"Verify Key & Fetch Models"** (which automatically validates and saves it to `.env`), or add it manually to `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-flash
```
*(Optional: DeepSeek keys starting with `sk-` are also supported as a fallback provider).*

### 3. Launch X-VibeBot
Double-click **`start_vibebot.bat`** in File Explorer, or run in PowerShell:
```powershell
python main.py
```

Open your browser to:
👉 **`http://localhost:8000`**

---

## 🔐 First-Time X Login (Bootstrap Session)

> **Important**: Never use an automated script to type your X password. X monitors login form keystrokes—signing in manually once saves your session cookies permanently in `./x_browser_profile/`.

1. Double-click **`login_browser.bat`** in the project folder (or click **"Browser Login"** on the dashboard).
2. The script automatically releases any background lock on `./x_browser_profile` (without touching your personal browser tabs) and opens your default browser (**Brave**, **Chrome**, or **Edge**) to `https://x.com/login`.
3. Sign into your X account normally.
4. Once your X home feed loads, **close that browser window**.
5. The dashboard (`http://localhost:8000`) will automatically verify your session and show **"X Session Active"** in green.

---

## ✨ Key Features & Reliability

- **Default Browser Auto-Detection**: Reads your Windows registry settings to launch your preferred Chromium browser (**Brave Browser**, **Google Chrome**, or **Microsoft Edge**) instead of a generic test browser.
- **Smart Profile-Lock Cleanup (`ProcessSingleton`)**: Safely closes only orphaned bot browser workers targeting `x_browser_profile` while leaving your personal browser windows untouched.
- **Sticky Multi-Model Failover**: Uses `gemini-3.8-flash` by default and automatically fails over across `gemini-3.7-flash`, `gemini-3.6-flash`, and `gemini-3.5-flash` if Google's servers experience temporary `503 UNAVAILABLE` high-demand spikes.
- **Topic-Aware Filtering**: Dynamically adapts the AI system prompt to your active **Target Feed / Search Query** (e.g., `#elclassico`, `buildinpublic`, `#ai`) while automatically skipping ticket scams, promo bots, and engagement bait.
- **Built-In Info Tooltips (`ⓘ`)**: Hover over any `ⓘ` icon in the dashboard for a simple, plain-English explanation of what each control or setting does.

---

## 🛡️ Anti-Suspension & Safety Rules

1. **Persistent Browser Profile**: Re-uses your authentic local cookies in `./x_browser_profile/` instead of creating disposable incognito sessions.
2. **Stealth Masking**: Masks `navigator.webdriver` and automation fingerprints.
3. **Humanized Keystrokes**: Types replies character-by-character with randomized 50ms–150ms delays and punctuation pauses.
4. **Daily Action Cap**: Enforces a configurable daily limit (default: 15 replies/day).
5. **Mandatory Cooldown Timer**: Enforces a minimum wait time (default: 15–25 minutes) between posted replies.
6. **Deduplication & Audit Trail**: Tracks every evaluated tweet in `vibebot.db` so the bot never replies to the same post twice, while allowing tweets skipped due to temporary API errors to be re-evaluated.
7. **Human-in-the-Loop Review (Default)**: Drafts wait in the **Pending Approvals** queue where you can edit the text, click **Approve & Post**, or **Skip** with one click.
