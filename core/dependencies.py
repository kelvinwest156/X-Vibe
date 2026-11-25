"""
FastAPI Dependencies for X-VibeBot.
Provides database session injection, verified multi-tenant isolation, active subscription guards,
and isolated Super Admin authentication.
"""

import os
import threading
import logging
from typing import Optional, Dict, Any, Tuple
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

import database as db_module
from database import (
    get_db,
    verify_auth_token,
    get_user_by_id,
    get_agent_config,
)
from models import User, AgentConfig
from core.security import is_production_env
from services.plans import is_subscription_valid

logger = logging.getLogger("x_vibebot.dependencies")

_jwks_lock = threading.Lock()
_jwks_client = None
_jwks_url_cached: Optional[str] = None


def _get_jwks_client():
    global _jwks_client, _jwks_url_cached
    supabase_url = (
        os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or ""
    ).strip().rstrip("/")
    if not supabase_url:
        return None
    jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
    with _jwks_lock:
        if _jwks_client is not None and _jwks_url_cached == jwks_url:
            return _jwks_client
        try:
            from jwt import PyJWKClient
            _jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
            _jwks_url_cached = jwks_url
            return _jwks_client
        except Exception as e:
            logger.debug(f"Could not initialize PyJWKClient: {e}")
            return None


def verify_supabase_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    Cryptographically verifies a Supabase JWT (never decodes with verify_signature=False):
    - Uses HS256 with SUPABASE_JWT_SECRET when configured and token header uses HS256
    - Uses ES256/RS256 via Supabase JWKS when SUPABASE_URL is configured
    """
    if not token or token.count(".") != 2:
        return None
    try:
        import jwt
        header = jwt.get_unverified_header(token)
        alg = str(header.get("alg") or "").upper()
        if not alg or alg == "NONE":
            return None

        supabase_secret = (os.getenv("SUPABASE_JWT_SECRET") or "").strip()
        if alg == "HS256":
            if not supabase_secret:
                return None
            return jwt.decode(
                token,
                supabase_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )

        if alg in ("RS256", "ES256"):
            jwk_client = _get_jwks_client()
            if jwk_client is None:
                return None
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience="authenticated",
            )
    except Exception:
        return None
    return None


def _extract_bearer_token(
    authorization: Optional[str], x_auth_token: Optional[str]
) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        tok = authorization.split("Bearer ", 1)[1].strip()
        return tok or None
    if x_auth_token and x_auth_token.strip():
        return x_auth_token.strip()
    return None


def _resolve_verified_token_identity(
    token: str, db: Session
) -> Optional[Tuple[str, Optional[User]]]:
    """
    Verifies a creator token (Supabase JWT or local HMAC session) against signature,
    expiration, and DB token_version. Returns (tenant_id, User | None) or None.
    """
    # 1. Verify Supabase JWT
    decoded = verify_supabase_jwt(token)
    if decoded and decoded.get("sub"):
        uid = str(decoded["sub"]).strip()
        user = get_user_by_id(db, uid)
        if not user:
            email = (
                decoded.get("email")
                or (decoded.get("user_metadata") or {}).get("email")
                or f"{uid}@auth.user"
            )
            name = (
                (decoded.get("user_metadata") or {}).get("name")
                or (email.split("@")[0] if email else "Creator")
            )
            user = User(
                user_id=uid,
                email=email,
                name=name,
                tenant_id=uid,
                password_hash="",
                token_version=1,
            )
        return uid, user

    # 2. Verify local HMAC-SHA256 session token + check DB revocation token_version
    payload = verify_auth_token(token)
    if payload and payload.get("uid"):
        user = get_user_by_id(db, str(payload["uid"]))
        if not user:
            return None
        db_ver = int(getattr(user, "token_version", 1) or 1)
        tok_ver = int(payload.get("ver", 1) or 1)
        if db_ver != tok_ver:
            return None
        return user.tenant_id, user

    return None


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Authentication dependency:
    Extracts and cryptographically verifies the authenticated User model.
    Returns None only if no valid credentials were provided.
    """
    token = _extract_bearer_token(authorization, x_auth_token)
    if not token:
        return None
    resolved = _resolve_verified_token_identity(token, db)
    return resolved[1] if resolved else None


async def require_current_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Mandatory authentication dependency raising HTTP 401 when unauthenticated."""
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication credentials required or session expired.",
        )
    return user


async def get_current_tenant(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """
    Strict multi-tenancy isolation dependency:
    Derives tenant_id EXCLUSIVELY from a cryptographically verified Bearer/X-Auth token.
    Never trusts spoofing via raw X-Tenant-Id headers.
    """
    token = _extract_bearer_token(authorization, x_auth_token)
    if token:
        resolved = _resolve_verified_token_identity(token, db)
        if resolved and resolved[0]:
            return resolved[0]
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication session.",
        )

    # Explicit opt-in single-user local development escape hatch ONLY
    if (
        not is_production_env()
        and os.getenv("ALLOW_UNAUTH_LOCAL_DEFAULT", "false").lower() == "true"
    ):
        return "default"

    raise HTTPException(
        status_code=401,
        detail="Authentication credentials required.",
    )


async def require_active_tenant_config(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> Tuple[str, AgentConfig]:
    """
    Enforces authentication + suspension + active subscription/trial status
    before executing AI generation, scraping, or publishing operations.
    """
    cfg = get_agent_config(db, tenant_id=tenant_id)
    if bool(getattr(cfg, "is_suspended", False)):
        raise HTTPException(
            status_code=403,
            detail="Workspace suspended by administrator. Please contact support.",
        )
    sub_ok, eff_status, _ = is_subscription_valid(cfg)
    if not sub_ok:
        raise HTTPException(
            status_code=402,
            detail=f"Subscription is {eff_status}. Please upgrade your plan in Billing to continue.",
        )
    return tenant_id, cfg


def _verify_super_admin_token_safe(token: str) -> Optional[Dict[str, Any]]:
    verifier = getattr(db_module, "verify_super_admin_token", None)
    if callable(verifier):
        return verifier(token)
    return None


def _is_regular_creator_token(token: str) -> bool:
    """Checks whether a non-admin token is a valid creator session or verified Supabase JWT."""
    payload = verify_auth_token(token)
    if payload and payload.get("role") != "super_admin":
        return True
    decoded = verify_supabase_jwt(token)
    if isinstance(decoded, dict) and decoded.get("sub"):
        return True
    return False


async def require_super_admin(
    authorization: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """
    Isolated Super Admin authentication dependency.
    Raises HTTP 401 if missing/expired/invalid, and HTTP 403 if a regular creator token is passed.
    """
    token: Optional[str] = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_admin_token and x_admin_token.strip():
        token = x_admin_token.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Super Admin authentication required.",
        )

    admin_payload = _verify_super_admin_token_safe(token)
    if admin_payload and admin_payload.get("role") == "super_admin":
        return admin_payload

    if _is_regular_creator_token(token):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Super Admin privileges required.",
        )

    raise HTTPException(
        status_code=401,
        detail="Invalid or expired Super Admin session.",
    )
