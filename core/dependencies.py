"""
FastAPI Dependencies for X-VibeBot.
Provides database session injection, tenant isolation context, and user authentication dependencies.
"""

import os
from typing import Optional, Dict, Any
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

import database as db_module
from database import get_db, verify_auth_token, get_user_by_id
from models import User


async def get_current_tenant(
    authorization: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None)
) -> str:
    """
    Multi-tenancy isolation dependency:
    Extracts tenant ID from signed session token, Supabase/Firebase JWT Bearer token, or 'X-Tenant-Id' header.
    Defaults cleanly to 'default' when running in single-user or local mode.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token and x_auth_token.strip():
        token = x_auth_token.strip()

    if token:
        # 1. Check Supabase JWT first
        try:
            import jwt
            supabase_secret = os.getenv("SUPABASE_JWT_SECRET")
            if supabase_secret:
                decoded = jwt.decode(token, supabase_secret, algorithms=["HS256"], audience="authenticated")
            else:
                decoded = jwt.decode(token, options={"verify_signature": False})
            sub = decoded.get("sub")
            if sub:
                return sub
        except Exception:
            pass

        # 2. Check signed session token fallback
        payload = verify_auth_token(token)
        if payload and payload.get("tenant_id"):
            return payload["tenant_id"]

    if x_tenant_id and x_tenant_id.strip():
        return x_tenant_id.strip()

    return "default"


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Authentication dependency:
    Extracts and verifies the authenticated User model from session or JWT token.
    Returns None if unauthenticated.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token and x_auth_token.strip():
        token = x_auth_token.strip()

    if not token:
        return None


    # 1. Check Supabase JWT
    try:
        import jwt
        supabase_secret = os.getenv("SUPABASE_JWT_SECRET")
        if supabase_secret:
            decoded = jwt.decode(token, supabase_secret, algorithms=["HS256"], audience="authenticated")
        else:
            decoded = jwt.decode(token, options={"verify_signature": False})
        uid = decoded.get("sub")
        if uid:
            user = get_user_by_id(db, uid)
            if not user:
                email = decoded.get("email") or decoded.get("user_metadata", {}).get("email") or f"{uid}@auth.user"
                name = decoded.get("user_metadata", {}).get("name") or (email.split("@")[0] if email else "Creator")
                user = User(user_id=uid, email=email, name=name, tenant_id=uid, password_hash="")
            return user
    except Exception:
        pass

    # 2. Check signed session token fallback
    payload = verify_auth_token(token)
    if payload and payload.get("uid"):
        return get_user_by_id(db, payload["uid"])

    return None


async def require_current_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """
    Mandatory authentication dependency:
    Extracts and validates current user, raising HTTP 401 if unauthenticated or token expired.
    """
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication credentials required or session expired."
        )
    return user


def _verify_super_admin_token_safe(token: str) -> Optional[Dict[str, Any]]:
    """Verifies a Super Admin signed token via database.verify_super_admin_token with safe fallback."""
    verifier = getattr(db_module, "verify_super_admin_token", None)
    if callable(verifier):
        return verifier(token)
    payload = verify_auth_token(token)
    if payload and payload.get("role") == "super_admin":
        return payload
    return None


def _is_regular_creator_token(token: str) -> bool:
    """Checks whether a non-admin token is a valid creator session or Supabase JWT."""
    payload = verify_auth_token(token)
    if payload and payload.get("role") != "super_admin":
        return True
    try:
        import jwt
        supabase_secret = os.getenv("SUPABASE_JWT_SECRET")
        if supabase_secret:
            decoded = jwt.decode(token, supabase_secret, algorithms=["HS256"], audience="authenticated")
        else:
            decoded = jwt.decode(token, options={"verify_signature": False})
        if isinstance(decoded, dict) and decoded.get("sub"):
            return True
    except Exception:
        pass
    return False


async def require_super_admin(
    authorization: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """
    Isolated Super Admin authentication dependency.
    Accepts Authorization: Bearer <token> or X-Admin-Token header.
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


