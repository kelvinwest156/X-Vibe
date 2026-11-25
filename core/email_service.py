"""
Email Delivery Service for X-VibeBot.
Handles outbound transactional emails (e.g. password resets, security alerts) via standard SMTP.
Uses Python's built-in smtplib and email packages with non-blocking async execution.
"""

import os
import html
import smtplib
import asyncio
import logging
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Optional

from core.security import (
    validate_email_address,
    resolve_safe_app_base_url,
    scrub_secrets,
)

logger = logging.getLogger("x_vibebot.email")


def is_smtp_configured() -> bool:
    """Checks whether outbound SMTP environment variables are properly configured."""
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    return bool(host and user and password)


def _send_smtp_sync(to_email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Synchronous worker that connects to the SMTP server, authenticates, and dispatches an email."""
    clean_to = (to_email or "").strip()
    if not validate_email_address(clean_to):
        logger.warning("Refused to send email to invalid recipient address.")
        return False

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    raw_sender = (os.getenv("SMTP_FROM") or f"X-VibeBot <{user}>").replace("\r", "").replace("\n", "").strip()
    envelope_sender = parseaddr(raw_sender)[1] or user
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    if not host or not user or not password:
        logger.warning("Outbound SMTP not configured. Cannot send email.")
        return False

    clean_subject = str(subject or "").replace("\r", " ").replace("\n", " ").strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = clean_subject
    msg["From"] = raw_sender
    msg["To"] = clean_to

    # Plain text version for accessibility & spam filters
    part1 = MIMEText(text_content, "plain", "utf-8")
    # Rich HTML version
    part2 = MIMEText(html_content, "html", "utf-8")
    msg.attach(part1)
    msg.attach(part2)

    server = None
    try:
        if port == 465:
            # SSL context
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            # Standard TLS context
            server = smtplib.SMTP(host, port, timeout=15)
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()

        server.login(user, password)
        server.sendmail(envelope_sender, [clean_to], msg.as_string())
        logger.info(f"Successfully sent email '{clean_subject}' to '{clean_to}'.")
        return True
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed for configured account: {scrub_secrets(e)}")
        return False
    except Exception as e:
        logger.error(f"Failed to dispatch email to '{clean_to}' via {host}:{port}: {scrub_secrets(e)}")
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


async def send_email(to_email: str, subject: str, html_content: str, text_content: str) -> bool:
    """Asynchronous wrapper that dispatches email without blocking the FastAPI event loop."""
    return await asyncio.to_thread(_send_smtp_sync, to_email, subject, html_content, text_content)


async def send_password_reset_email(
    to_email: str,
    reset_token: str,
    app_url: Optional[str] = None
) -> bool:
    """
    Constructs a branded password reset email and dispatches it via SMTP.
    Returns True if sent, False if SMTP is unconfigured or failed.
    """
    clean_to = (to_email or "").strip()
    if not validate_email_address(clean_to):
        logger.warning("Refused password reset email for invalid recipient address.")
        return False

    base_url = resolve_safe_app_base_url(app_url).rstrip("/")
    safe_token = urllib.parse.quote(str(reset_token or ""), safe=".-_~")
    reset_link = f"{base_url}/reset-password?token={safe_token}"

    escaped_email = html.escape(clean_to, quote=True)
    escaped_link = html.escape(reset_link, quote=True)

    subject = "Reset your X-VibeBot password"

    text_content = f"""Hello,

We received a request to reset your password for your X-VibeBot account ({clean_to}).

To set a new password, visit the following link (valid for 60 minutes):
{reset_link}

If you did not request a password reset, you can safely ignore this email. Your current password remains active.

— The X-VibeBot Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #0c0c0c;
      color: #f5f5f5;
      margin: 0;
      padding: 30px 15px;
    }}
    .container {{
      max-width: 520px;
      margin: 0 auto;
      background-color: #161616;
      border: 1px solid #262626;
      border-radius: 16px;
      padding: 36px 32px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }}
    .logo {{
      display: inline-block;
      width: 36px;
      height: 36px;
      background: #f5f5f5;
      color: #111;
      border-radius: 10px;
      text-align: center;
      line-height: 36px;
      font-weight: 800;
      font-size: 18px;
      margin-bottom: 20px;
    }}
    h1 {{
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin: 0 0 12px 0;
      color: #ffffff;
    }}
    p {{
      font-size: 14px;
      line-height: 1.6;
      color: #a1a1aa;
      margin: 0 0 20px 0;
    }}
    .btn {{
      display: inline-block;
      background-color: #ea580c;
      color: #ffffff !important;
      text-decoration: none;
      font-weight: 600;
      font-size: 14px;
      padding: 12px 28px;
      border-radius: 10px;
      margin: 10px 0 24px 0;
      box-shadow: 0 4px 14px rgba(234, 88, 12, 0.4);
    }}
    .fallback {{
      font-size: 12px;
      word-break: break-all;
      color: #71717a;
      background: #111111;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid #222222;
      margin-top: 15px;
    }}
    .footer {{
      margin-top: 30px;
      padding-top: 20px;
      border-top: 1px solid #262626;
      font-size: 12px;
      color: #52525b;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="logo">𝕏</div>
    <h1>Reset your password</h1>
    <p>Hello,</p>
    <p>We received a request to reset the password for your X-VibeBot account (<strong>{escaped_email}</strong>).</p>
    <p>Click the button below to choose a new password. This link is valid for the next <strong>60 minutes</strong>:</p>
    
    <div style="text-align: center;">
      <a href="{escaped_link}" class="btn" target="_blank" rel="noopener noreferrer">Reset Password</a>
    </div>

    <p style="font-size: 12px; color: #71717a;">If the button above does not work, copy and paste this URL into your browser:</p>
    <div class="fallback">{escaped_link}</div>

    <div class="footer">
      If you did not request this password reset, you can safely ignore this email. Your account remains secure.<br>
      © 2026 X-VibeBot · Autonomous X Growth Engine
    </div>
  </div>
</body>
</html>
"""

    return await send_email(clean_to, subject, html_content, text_content)
