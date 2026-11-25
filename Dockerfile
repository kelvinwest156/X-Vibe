# Official Microsoft Playwright Python image with Chromium & system libs pre-installed
FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HEADLESS=true
ENV BROWSER_PROFILE_DIR=/data/browser_profiles/x_browser_profile
ENV DATABASE_URL=sqlite:////data/vibebot.db
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Create non-root user and persistent directories
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --create-home appuser \
    && mkdir -p /data/browser_profiles /ms-playwright

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium \
    && chown -R appuser:appgroup /data /app /ms-playwright

COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health', timeout=4)" || exit 1

CMD ["python", "main.py"]
