# X-VibeBot: Monolithic AI Browser-Agent for X (Twitter)

**X-VibeBot** is a minimal, monolithic browser-automation agent built with **FastAPI**, **Playwright**, and **DeepSeek AI**. It navigates X safely using persistent browser sessions, evaluates posts using DeepSeek, and manages replies through a built-in real-time dashboard with human-in-the-loop manual review.

---

## 🏗️ Architecture & File Structure

```plaintext
Xbot/
│
├── main.py              # FastAPI monolith controller, background loop, & API routes
├── database.py          # SQLite database connection & query helpers (logs actions & avoids loops)
├── models.py            # SQLAlchemy database tables & Pydantic request/response schemas
├── ai_engine.py         # DeepSeek AI decision engine (prompting & evaluation)
├── browser_worker.py    # Playwright browser automation, stealth flags, & humanized keystrokes
├── static/
│   └── index.html       # Minimal dashboard (Tailwind CSS via CDN) for manual review & stats
├── requirements.txt     # Python dependencies
├── requirements.dev     # Developer dependencies
├── .env.example         # Template configuration for API keys & settings
├── .env                 # Local configuration (API keys, caps, search terms)
└── x_browser_profile/   # Persistent browser profile folder (stores login session & cookies)
```

---

## 🚀 Quick Start Guide (Beginner-Friendly)

### 1. Install Dependencies
Run in your terminal:
```powershell
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure DeepSeek API Key
Open `.env` in this directory and paste your DeepSeek API key:
```env
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
```
*(If you don't have a key yet, get one at [platform.deepseek.com](https://platform.deepseek.com/)).*

### 3. Launch X-VibeBot
Run the FastAPI monolith server:
```powershell
python main.py
```
Or with Uvicorn live reload:
```powershell
uvicorn main:app --reload --port 8000
```

Open your browser to:
👉 **`http://localhost:8000`**

---

## 🔐 The First-Time Login (Bootstrap Login)

> **Important**: Never use an automated script to enter your X password. X's bot detection monitors keystrokes and timing on the login form.

1. Start X-VibeBot and open `http://localhost:8000`.
2. Click the purple button **"Open Browser for Login"**.
3. A real Chromium browser window will open to `x.com/login`.
4. Log into your X account manually (including 2FA if enabled).
5. Once you are on the X home timeline, close that window or return to the dashboard.
6. Click the refresh button next to **"X Session"** on the dashboard. It will now show **"Logged In"** in green!
7. All your login cookies and tokens are safely saved in `./x_browser_profile/` so you don't need to log in again.

---

## 🛡️ Anti-Suspension & Safety Rules Built In

To keep your X account completely safe:
1. **Persistent Browser Session**: Re-uses authentic local cookies instead of firing temporary incognito sessions.
2. **Stealth Evasion**: Injects stealth properties to hide `navigator.webdriver` and automation artifacts.
3. **Character-by-Character Humanized Typing**: Simulates human typing cadence with 50ms–150ms randomized delays and micro-pauses.
4. **Volume Cap**: Default limit of 15 automated actions per day (anti-spam protection).
5. **Mandatory Cooldown Gap**: Enforces a 15–30 minute gap between actions.
6. **Duplicate Prevention**: Every scraped tweet ID is recorded in the SQLite database (`vibebot.db`). The bot will **never** interact with the same tweet twice.
7. **Human-in-the-Loop Mode (Default)**: DeepSeek drafts witty replies, but they sit in the **Manual Review Queue** on your dashboard. You can read, edit, approve, or reject them with one click.
