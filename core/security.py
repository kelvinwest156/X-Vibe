"""
Core Security Utilities for X-VibeBot.
Provides environment checks, HKDF-style key derivation, Fernet encryption at rest,
secret scrubbing, strict SSRF/URL validation, cookie sanitization, and rate limiting.
"""

import os
import re
import hmac
import time
import base64
import socket
import asyncio
import hashlib
import ipaddress
import threading
import urllib.parse
from collections import deque, defaultdict
from typing import Optional, Set, List, Dict, Any, Tuple
from fastapi import Request

_UNSAFE_SAMPLE_SECRETS = {
    "x-vibebot-creator-studio-secret-key-salt-2026",
    "changeme",
    "secret",
    "dev",
    "your-secret-key",
}

_EMAIL_RE = re.compile(
    r"^[^@\s<>()\"'\\,;]+@[^@\s<>()\"'\\,;]+\.[^@\s<>()\"'\\,;]{2,}$"
)

ALLOWED_X_COOKIE_DOMAINS = frozenset({".x.com", "x.com", ".twitter.com", "twitter.com"})
ALLOWED_X_HOSTS = frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"})
ALLOWED_MEDIA_HOSTS = frozenset({"pbs.twimg.com"})

_ephemeral_dev_secret: Optional[str] = None
_fernet_lock = threading.Lock()
_cached_fernet = None
_cached_fernet_secret: Optional[str] = None


def is_production_env() -> bool:
    """Returns True when running in production or on managed cloud hosting (Railway/Render)."""
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    if env in ("production", "prod"):
        return True
    if env in ("development", "dev", "local", "test"):
        return False
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RAILWAY_PROJECT_ID")
        or os.getenv("RENDER")
    )


def get_master_secret() -> str:
    """
    Retrieves and validates AUTH_SECRET_KEY.
    Fails closed in production if missing, weak, or equal to the sample secret.
    """
    global _ephemeral_dev_secret
    raw = (os.getenv("AUTH_SECRET_KEY") or "").strip()
    in_prod = is_production_env()

    if not raw or raw in _UNSAFE_SAMPLE_SECRETS or len(raw) < 16:
        if in_prod:
            raise RuntimeError(
                "FATAL: AUTH_SECRET_KEY must be set to a unique >=16-character secret in production."
            )
        if raw:
            return raw
        if _ephemeral_dev_secret is None:
            import secrets
            _ephemeral_dev_secret = secrets.token_hex(32)
        return _ephemeral_dev_secret
    return raw


def derive_subkey(purpose: str, base_secret: Optional[str] = None) -> bytes:
    """Derives an isolated 32-byte key per cryptographic purpose."""
    secret = (base_secret or get_master_secret()).encode("utf-8")
    return hmac.new(secret, f"x-vibebot::domain::{purpose}".encode("utf-8"), hashlib.sha256).digest()


def _get_fernet():
    """Returns cached cryptography.fernet.Fernet instance for at-rest encryption."""
    global _cached_fernet, _cached_fernet_secret
    from cryptography.fernet import Fernet

    env_enc = (os.getenv("ENCRYPTION_KEY") or "").strip()
    key_source = env_enc or get_master_secret()

    with _fernet_lock:
        if _cached_fernet is not None and _cached_fernet_secret == key_source:
            return _cached_fernet

        if env_enc:
            try:
                f = Fernet(env_enc.encode("utf-8"))
                _cached_fernet = f
                _cached_fernet_secret = key_source
                return f
            except Exception:
                # Derive deterministic Fernet key from arbitrary ENCRYPTION_KEY string
                digest = hmac.new(env_enc.encode("utf-8"), b"x-vibebot::fernet-v1", hashlib.sha256).digest()
                f = Fernet(base64.urlsafe_b64encode(digest))
                _cached_fernet = f
                _cached_fernet_secret = key_source
                return f

        derived = derive_subkey("data_encryption_v1", key_source)
        f = Fernet(base64.urlsafe_b64encode(derived))
        _cached_fernet = f
        _cached_fernet_secret = key_source
        return f


def encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    """Encrypts a sensitive DB string with Fernet ('enc::...'). Idempotent for already-encrypted strings."""
    if plaintext is None:
        return None
    s = str(plaintext)
    if not s:
        return s
    if s.startswith("enc::"):
        return s
    f = _get_fernet()
    token = f.encrypt(s.encode("utf-8")).decode("utf-8")
    return f"enc::{token}"


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypts an 'enc::...' string, or passes through legacy unencrypted values safely."""
    if value is None:
        return None
    s = str(value)
    if not s:
        return s
    if not s.startswith("enc::"):
        return s
    token = s[5:]
    f = _get_fernet()
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:
        # Also test fallback derived key with AUTH_SECRET_KEY if ENCRYPTION_KEY rotated cleanly
        return None


def scrub_secrets(text: Any) -> str:
    """Redacts API keys, tokens, DB credentials, and session secrets from strings before logging/returning."""
    s = str(text or "")
    s = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", s)
    s = re.sub(r"AIza[A-Za-z0-9_\-]{10,}", "AIza***", s)
    s = re.sub(r"([?&](?:key|api_key|token|secret)=)[^&\s]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"((?:postgres(?:ql)?(?:\+\w+)?)://[^:\s/]+:)[^@\s]+(@)", r"\1***\2", s, flags=re.IGNORECASE)
    s = re.sub(r"((?:auth_token|ct0)=)[^;\s\"']+", r"\1***", s, flags=re.IGNORECASE)
    return s


def validate_email_address(email: str) -> bool:
    """Validates email format strictly and blocks CRLF / HTML metacharacters."""
    if not email or len(email) > 254:
        return False
    if any(ch in email for ch in ("\r", "\n", "\x00", "<", ">", '"', "'")):
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def _is_forbidden_ip(ip_str: str) -> bool:
    """Returns True if the IP is loopback, private, link-local, multicast, reserved, or unspecified."""
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0])
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return True


def validate_external_url(
    url: str,
    *,
    allowed_hosts: Optional[Set[str]] = None,
    require_https: bool = True,
    resolve_dns: bool = False,
    max_length: int = 1024,
) -> str:
    """
    Validates an external URL against scheme, embedded credential, host allowlist,
    and private/loopback/link-local IP rules to block SSRF and browser hijacking.
    Raises ValueError if invalid.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")
    clean = url.strip()
    if len(clean) > max_length or any(c in clean for c in ("\r", "\n", "\x00")):
        raise ValueError("URL exceeds maximum length or contains invalid control characters.")

    parsed = urllib.parse.urlparse(clean)
    scheme = (parsed.scheme or "").lower()
    if require_https and scheme != "https":
        raise ValueError("Only HTTPS URLs are permitted.")
    if not require_https and scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS URLs are permitted.")

    if parsed.username or parsed.password:
        raise ValueError("Embedded credentials in URLs are forbidden.")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError("URL is missing a valid hostname.")

    if allowed_hosts is not None:
        normalized_allow = {h.lower().rstrip(".") for h in allowed_hosts}
        if hostname not in normalized_allow:
            raise ValueError(f"Host '{hostname}' is not in the allowed host list.")

    # Block literal internal IPs directly
    try:
        ipaddress.ip_address(hostname)
        if _is_forbidden_ip(hostname):
            raise ValueError(f"Forbidden internal/reserved IP address '{hostname}'.")
    except ValueError as ve:
        if "Forbidden internal" in str(ve):
            raise
        # Not an IP literal; hostname checks follow
        if hostname in ("localhost", "localhost.localdomain") or hostname.endswith(".internal") or hostname.endswith(".local"):
            raise ValueError(f"Forbidden internal hostname '{hostname}'.")

    if resolve_dns:
        port = parsed.port or (443 if scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as ge:
            raise ValueError(f"Could not resolve hostname '{hostname}': {ge}")
        if not infos:
            raise ValueError(f"No network addresses resolved for '{hostname}'.")
        for info in infos:
            addr = info[4][0]
            if _is_forbidden_ip(addr):
                raise ValueError(f"Hostname '{hostname}' resolved to forbidden internal IP '{addr}'.")

    return clean


async def async_validate_external_url(
    url: str,
    *,
    allowed_hosts: Optional[Set[str]] = None,
    require_https: bool = True,
    resolve_dns: bool = False,
    max_length: int = 1024,
) -> str:
    """Non-blocking wrapper for validate_external_url when DNS resolution is enabled."""
    if resolve_dns:
        return await asyncio.to_thread(
            validate_external_url,
            url,
            allowed_hosts=allowed_hosts,
            require_https=require_https,
            resolve_dns=True,
            max_length=max_length,
        )
    return validate_external_url(
        url,
        allowed_hosts=allowed_hosts,
        require_https=require_https,
        resolve_dns=False,
        max_length=max_length,
    )


def _normalize_origin(raw_url: str) -> Optional[str]:
    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except Exception:
        pass
    return None


def resolve_safe_app_base_url(requested_app_url: Optional[str]) -> str:
    """
    Resolves a safe reset/redirect origin against configured server origins,
    preventing attacker-controlled `app_url` open-redirect/phishing links.
    """
    server_default = (os.getenv("APP_BASE_URL") or "http://localhost:8000").strip().rstrip("/")
    allowed_origins: Set[str] = set()

    for candidate in [
        server_default,
        *(os.getenv("CORS_ORIGINS", "").split(",")),
    ]:
        norm = _normalize_origin(candidate) if candidate else None
        if norm:
            allowed_origins.add(norm)

    for domain_env in ("RAILWAY_PUBLIC_DOMAIN", "RENDER_EXTERNAL_HOSTNAME"):
        host = (os.getenv(domain_env) or "").strip()
        if host:
            allowed_origins.add(f"https://{host.lower()}")

    render_url = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
    if render_url:
        norm = _normalize_origin(render_url)
        if norm:
            allowed_origins.add(norm)

    if requested_app_url:
        req_norm = _normalize_origin(requested_app_url)
        if req_norm:
            if req_norm in allowed_origins:
                return req_norm
            if not is_production_env():
                parsed = urllib.parse.urlparse(req_norm)
                if (parsed.hostname or "").lower() in ("localhost", "127.0.0.1"):
                    return req_norm

    return server_default


def sanitize_x_cookies(
    cookies: List[Dict[str, Any]],
    max_cookies: int = 50,
) -> List[Dict[str, Any]]:
    """
    Normalizes and strictly validates X/Twitter cookies before injecting into Playwright:
    - Restricts domain to .x.com / x.com / .twitter.com / twitter.com
    - Maps sameSite variants safely to Strict | Lax | None
    - Caps count & length to prevent arbitrary cookie injection or memory exhaustion
    """
    if not isinstance(cookies, list):
        raise ValueError("Cookies payload must be a JSON array.")
    if len(cookies) > max_cookies:
        raise ValueError(f"Too many cookies supplied (max {max_cookies}).")

    same_site_map = {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
        "unspecified": "Lax",
    }

    sanitized: List[Dict[str, Any]] = []
    for raw in cookies:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        value = str(raw.get("value") or "").strip()
        if not name or not value or len(name) > 128 or len(value) > 4096:
            continue
        if any(c in name for c in ("\r", "\n", ";", "\x00")) or any(c in value for c in ("\r", "\n", "\x00")):
            continue

        domain = str(raw.get("domain") or ".x.com").strip().lower()
        if domain not in ALLOWED_X_COOKIE_DOMAINS:
            # Skip tracking/non-X cookies cleanly instead of poisoning other domains
            continue

        path = str(raw.get("path") or "/").strip()
        if not path.startswith("/"):
            path = "/"

        raw_ss = str(raw.get("sameSite") or "Lax").strip().lower()
        same_site = same_site_map.get(raw_ss, "Lax")

        clean_cookie: Dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path[:256],
            "secure": bool(raw.get("secure", True)),
            "httpOnly": bool(raw.get("httpOnly", name == "auth_token")),
            "sameSite": same_site,
        }
        # Chromium requires secure=True if sameSite="None"
        if same_site == "None":
            clean_cookie["secure"] = True

        exp = raw.get("expires") if "expires" in raw else raw.get("expirationDate")
        if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp > 0:
            clean_cookie["expires"] = float(exp)

        sanitized.append(clean_cookie)

    return sanitized


def deterministic_profile_dirname(tenant_id: str) -> str:
    """Produces a collision-free filesystem directory name for a tenant profile."""
    clean = (tenant_id or "default").strip()
    if clean == "default":
        return "x_browser_profile"
    safe_prefix = re.sub(r"[^a-zA-Z0-9_\-]", "_", clean)[:24].strip("_") or "tenant"
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]
    return f"x_browser_profile_{safe_prefix}_{digest}"


def get_client_ip(request: Optional[Request]) -> str:
    """Extracts client IP cleanly for rate limiting and audit logging."""
    if request is None:
        return "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return "unknown"


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter for sensitive auth/admin routes."""

    def __init__(self, max_buckets: int = 10000):
        self._hits: Dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_buckets = max_buckets

    def check_and_hit(
        self, bucket: str, key: str, limit: int, window_seconds: int
    ) -> Tuple[bool, int]:
        """
        Records an attempt for (bucket, key).
        Returns (allowed: bool, retry_after_seconds: int).
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        full_key = f"{bucket}:{key}"

        with self._lock:
            if len(self._hits) > self._max_buckets:
                # Prune empty/expired buckets to keep memory bounded
                expired_keys = [
                    k for k, dq in self._hits.items() if not dq or dq[-1] < cutoff
                ]
                for k in expired_keys[: self._max_buckets // 2]:
                    del self._hits[k]

            dq = self._hits[full_key]
            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= limit:
                retry_after = max(1, int(dq[0] + window_seconds - now) + 1)
                return False, retry_after

            dq.append(now)
            return True, 0


rate_limiter = SlidingWindowRateLimiter()
