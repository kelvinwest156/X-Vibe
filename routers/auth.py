"""
Authentication Router for X-VibeBot.
Handles user sign-up, sign-in, session verification, and sign-out with tenant isolation.
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.exc import IntegrityError
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
from core.security import (
    is_production_env,
    validate_email_address,
    rate_limiter,
    get_client_ip,
)
from core.dependencies import verify_supabase_jwt
from core.email_service import is_smtp_configured, send_password_reset_email
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

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _enforce_rate_limit(bucket: str, key: str, limit: int, window_seconds: int) -> None:
    allowed, retry_after = rate_limiter.check_and_hit(bucket, key, limit, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


@router.post("/signup", response_model=AuthResponse)
def signup(req: SignUpRequest, request: Request, db: Session = Depends(get_db)):
    """Registers a new creator user account with isolated tenant sandbox."""
    _enforce_rate_limit("auth_signup", get_client_ip(request), limit=5, window_seconds=300)

    email = req.email.strip().lower()
    if not validate_email_address(email):
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")

    existing = get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists. Please sign in.")

    try:
        user = create_user(db, email=email, password_plain=req.password, name=req.name)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="An account with this email already exists. Please sign in.")

    token = create_auth_token(
        user.user_id,
        user.email,
        user.tenant_id,
        token_version=getattr(user, "token_version", 1),
    )
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
def signin(req: SignInRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticates an existing user and returns a signed session token."""
    email = req.email.strip().lower()
    _enforce_rate_limit("auth_signin", f"{get_client_ip(request)}:{email}", limit=10, window_seconds=60)

    if not validate_email_address(email):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user = get_user_by_email(db, email)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_auth_token(
        user.user_id,
        user.email,
        user.tenant_id,
        token_version=getattr(user, "token_version", 1),
    )
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
async def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Initiates password reset by issuing a secure HMAC token and dispatching via SMTP email."""
    _enforce_rate_limit("auth_forgot_password", get_client_ip(request), limit=5, window_seconds=300)

    email = req.email.strip().lower()
    if not validate_email_address(email):
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    generic_msg = "If an account exists with this email, instructions to reset your password have been issued."
    user = get_user_by_email(db, email)
    if not user:
        # Don't leak user enumeration in public responses
        return ForgotPasswordResponse(
            success=True,
            message=generic_msg,
            reset_token=None,
        )

    reset_token = create_password_reset_token(
        user.email,
        exp_minutes=60,
        password_hash=user.password_hash,
    )

    smtp_sent = False
    if is_smtp_configured():
        smtp_sent = await send_password_reset_email(user.email, reset_token, req.app_url)

    if smtp_sent:
        return ForgotPasswordResponse(
            success=True,
            message="A password reset link has been sent to your email inbox. Please check your messages.",
            reset_token=None
        )

    allow_dev_token = (
        not is_production_env()
        and os.getenv("ALLOW_DEV_RESET_TOKEN", "false").strip().lower() == "true"
    )
    if allow_dev_token:
        return ForgotPasswordResponse(
            success=True,
            message="Password reset link prepared. Please enter your new password below.",
            reset_token=reset_token
        )

    return ForgotPasswordResponse(
        success=True,
        message=generic_msg,
        reset_token=None
    )


@router.post("/reset-password", response_model=AuthResponse)
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Validates the reset token, updates password hash, and logs user in directly."""
    _enforce_rate_limit("auth_reset_password", get_client_ip(request), limit=10, window_seconds=300)

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")

    email = verify_password_reset_token(req.token, db=db)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token. Please request a new link.")

    user = update_user_password(db, email, req.new_password)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    token = create_auth_token(
        user.user_id,
        user.email,
        user.tenant_id,
        token_version=getattr(user, "token_version", 1),
    )
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
def get_me(
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

    # 1. Check Supabase JWT first using cryptographic verification
    decoded = verify_supabase_jwt(token)
    if decoded and decoded.get("sub"):
        uid = str(decoded["sub"]).strip()
        user_meta = decoded.get("user_metadata") or {}
        email = decoded.get("email") or (user_meta.get("email") if isinstance(user_meta, dict) else None)
        name = (user_meta.get("name") if isinstance(user_meta, dict) else None) or (
            email.split("@")[0] if email else "Creator"
        )
        return {
            "uid": uid,
            "email": email,
            "name": name,
            "tenant_id": uid,
            "created_at": None
        }

    # 2. Check local signed session token fallback + verify token_version
    payload = verify_auth_token(token)
    if not payload or not payload.get("uid"):
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please sign in again.")

    user = get_user_by_id(db, str(payload["uid"]))
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    try:
        db_ver = int(getattr(user, "token_version", 1) or 1)
        tok_ver = int(payload.get("ver", 1) or 1)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please sign in again.")
    if db_ver != tok_ver:
        raise HTTPException(status_code=401, detail="Session expired or revoked. Please sign in again.")

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
