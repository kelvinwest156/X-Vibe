"""
Authentication Router for X-VibeBot.
Handles user sign-up, sign-in, session verification, and sign-out with tenant isolation.
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from models import SignUpRequest, SignInRequest, UserResponse, AuthResponse
from database import (
    get_db,
    create_user,
    get_user_by_email,
    get_user_by_id,
    verify_password,
    create_auth_token,
    verify_auth_token
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse)
async def signup(req: SignUpRequest, db: Session = Depends(get_db)):
    """Registers a new creator user account with isolated tenant sandbox."""
    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")

    existing = get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists. Please sign in.")

    user = create_user(db, email=email, password_plain=req.password, name=req.name)
    token = create_auth_token(user.user_id, user.email, user.tenant_id)
    return AuthResponse(
        success=True,
        token=token,
        user=UserResponse(
            uid=user.user_id,
            email=user.email,
            name=user.name,
            tenant_id=user.tenant_id,
            created_at=user.created_at
        ),
        tenant_id=user.tenant_id,
        message="Account created successfully."
    )


@router.post("/signin", response_model=AuthResponse)
async def signin(req: SignInRequest, db: Session = Depends(get_db)):
    """Authenticates an existing user and returns a signed session token."""
    email = req.email.strip().lower()
    user = get_user_by_email(db, email)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_auth_token(user.user_id, user.email, user.tenant_id)
    return AuthResponse(
        success=True,
        token=token,
        user=UserResponse(
            uid=user.user_id,
            email=user.email,
            name=user.name,
            tenant_id=user.tenant_id,
            created_at=user.created_at
        ),
        tenant_id=user.tenant_id,
        message="Signed in successfully."
    )


@router.get("/me")
async def get_me(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Retrieves current user identity from Supabase JWT or local HMAC session token."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token and x_auth_token.strip():
        token = x_auth_token.strip()

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    # 1. Check Supabase JWT first
    try:
        import jwt
        supabase_secret = os.getenv("SUPABASE_JWT_SECRET")
        if supabase_secret:
            decoded = jwt.decode(token, supabase_secret, algorithms=["HS256"], audience="authenticated")
        else:
            decoded = jwt.decode(token, options={"verify_signature": False})
        uid = decoded.get("sub")
        if uid:
            email = decoded.get("email") or decoded.get("user_metadata", {}).get("email")
            name = decoded.get("user_metadata", {}).get("name") or (email.split("@")[0] if email else "Creator")
            return {
                "uid": uid,
                "email": email,
                "name": name,
                "tenant_id": uid,
                "created_at": None
            }
    except Exception:
        pass

    # 2. Check local signed session token fallback
    payload = verify_auth_token(token)
    if not payload or not payload.get("uid"):
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please sign in again.")

    user = get_user_by_id(db, payload["uid"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "uid": user.user_id,
        "email": user.email,
        "name": user.name,
        "tenant_id": user.tenant_id,
        "created_at": user.created_at.isoformat() if user.created_at else None
    }


@router.post("/signout")
async def signout():
    """Clears client session state."""
    return {"success": True, "message": "Signed out successfully."}
