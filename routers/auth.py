"""
Authentication Router for X-VibeBot.
Handles user sign-up, sign-in, session verification, and sign-out with tenant isolation.
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from models import (
    SignUpRequest,
    SignInRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    UserResponse,
    AuthResponse
)
from database import (
    get_db,
    create_user,
    get_user_by_email,
    get_user_by_id,
    verify_password,
    create_auth_token,
    verify_auth_token,
    create_password_reset_token,
    verify_password_reset_token,
    update_user_password
)
from core.email_service import is_smtp_configured, send_password_reset_email

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


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Initiates password reset by issuing a secure HMAC token and dispatching via SMTP email."""
    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    user = get_user_by_email(db, email)
    if not user:
        # Don't leak user enumeration in public responses
        return ForgotPasswordResponse(
            success=True,
            message="If an account exists with this email, instructions to reset your password have been issued."
        )

    reset_token = create_password_reset_token(user.email, exp_minutes=60)
    print(f"[AUTH] Generated password reset token for {user.email}: {reset_token}")

    smtp_sent = False
    if is_smtp_configured():
        smtp_sent = await send_password_reset_email(user.email, reset_token, req.app_url)

    if smtp_sent:
        return ForgotPasswordResponse(
            success=True,
            message="A password reset link has been sent to your email inbox. Please check your messages.",
            reset_token=None
        )
    else:
        # If SMTP is not yet configured in .env, deliver reset token for seamless local developer testing
        return ForgotPasswordResponse(
            success=True,
            message="Password reset link prepared. Please enter your new password below.",
            reset_token=reset_token
        )


@router.post("/reset-password", response_model=AuthResponse)
async def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Validates the reset token, updates password hash, and logs user in directly."""
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")

    email = verify_password_reset_token(req.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token. Please request a new link.")

    user = update_user_password(db, email, req.new_password)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

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
        message="Your password has been reset successfully. Welcome back!"
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
