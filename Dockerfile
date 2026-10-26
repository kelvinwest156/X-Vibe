# Official Microsoft Playwright Python image with Chromium & system libs pre-installed
FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HEADLESS=true
ENV BROWSER_PROFILE_DIR=/data/x_browser_profile
ENV DATABASE_URL=sqlite:////data/vibebot.db

# Create persistent data directory
RUN mkdir -p /data/x_browser_profile

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
