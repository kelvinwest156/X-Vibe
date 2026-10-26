# X-VibeBot: Minimal AI Browser-Agent for X (Twitter)

**X-VibeBot** is a clean, minimal, local-and-cloud browser-automation agent built with **FastAPI**, **Playwright**, and **Google Gemini AI** (`google-genai`). It detects your linked `@username`, evaluates posts with full context (engagement metrics, quoted posts, image descriptions), generates **3 human-styled reply angles** (*Witty*, *Question*, *Punchy*) with zero AI clichés, and schedules replies at **completely random times** within your active waking hours so your account never looks like a bot.

---

## ✨ Key Features

- **Anti-Robotic AI Engine (`ai_engine.py`)**:
  - Explicitly strips "AI tells" (no em-dashes `—`, no semicolons, no corporate buzzwords like *"delve"*, *"game-changer"*, or *"Let's see if..."*).
  - Generates **3 quick vibe pills** per post (**`Witty`**, **`Question`**, **`Punchy`**) plus a **1-click `↻` Regenerate** button.
  - Adapts to your custom **My Voice / Style** prompt and **Search Query**.
- **Randomized Scheduling & Active Hours (`database.py`, `main.py`)**:
  - **Queue Random Time**: Instead of posting on a predictable clockwork timer, each approved (or Autopilot) reply is scheduled at a **completely random future timestamp** down to the second between your `Min` and `Max` delay range.
  - **Active Hours Window (Sleep Schedule)**: Configure your waking hours (e.g. `08:00` to `23:00`). Outside those hours, the bot sleeps like a human and pushes queued replies to the next morning with random jitter.
- **Natural Browsing Flow (`browser_worker.py`)**:
  - Reads engagement counts (`likes · replies`), quoted tweets, and image alt text before evaluating.
  - Simulates human reading time, gentle scrolling, and naturally clicks **Like (❤️)** on ~40% of posts before typing a reply.
  - Automatically detects and displays your linked **`@username`** in the top header.
- **Cloud-Ready for Render (`Dockerfile`, `render.yaml`)**:
  - Includes built-in **Cookie Export / Import** (`Cookies` button in the top bar) so you can log in locally once and sync your session to a headless Render Docker deployment in one click.

---

## 🚀 Local Quick Start

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
playwright install chromium
```

### 2. Launch the Server
Double-click **`start_vibebot.bat`** or run:
```powershell
python main.py
```
Open **`http://localhost:8000`** in your browser.

### 3. Link Your X Account & Gemini Key
1. Paste your free **[Google Gemini API key](https://aistudio.google.com/app/apikey)** in the sidebar and click **Verify**.
2. Double-click **`login_browser.bat`** (or click **Login** in the top bar) to sign into X in your default browser (**Brave**, **Chrome**, or **Edge**).
3. Close the login window once your X home feed loads—your **`@username`** will appear in green in the top header!

---

## ☁️ Deploying on Render (Recommended over Vercel)

> **Why Render instead of Vercel?**  
> Vercel only runs short-lived serverless functions (10–60s timeout) with no persistent disk and cannot run a continuous Playwright Chromium browser or background random-schedule loop. **Render** supports long-running **Docker Web Services** with a **Persistent Disk** (`/data`) that preserves both your SQLite database (`vibebot.db`) and browser profile (`/data/x_browser_profile`).

### Step-by-Step Render Deployment
1. Push this repository to your GitHub account.
2. Go to **[Render Dashboard](https://dashboard.render.com/)** -> **New +** -> **Blueprint** (or **Web Service**) and connect your repository.
3. Render will automatically detect **`render.yaml`** and **`Dockerfile`**:
   - Sets up the official Microsoft Playwright Python container (`mcr.microsoft.com/playwright/python`).
   - Attaches a persistent disk mounted at `/data`.
4. Enter your `GEMINI_API_KEY` when prompted and deploy.
5. **Sync Your X Login to Render (No Password Typing Required)**:
   - On your local PC (`http://localhost:8000`), click **`Cookies`** in the top bar -> **`Export Current`** and copy the JSON.
   - Open your deployed Render URL, click **`Cookies`** -> paste the JSON -> click **`Import & Verify`**. Your Render instance will immediately link to your `@username`!
