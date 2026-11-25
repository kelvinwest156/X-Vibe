"""
Billing & Subscription Router for X-VibeBot.
Manages subscription tiers, plan status, trial life-cycle, payment checkout, and webhooks.
"""

import os
import json
import hmac
import hashlib
import asyncio
import logging
import urllib.parse
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from models import User, AgentConfig
from core.dependencies import get_current_tenant, get_current_user
from core.security import (
    is_production_env,
    resolve_safe_app_base_url,
    validate_email_address,
    scrub_secrets,
)
from database import (
    get_db,
    get_agent_config,
    get_tenant_daily_tokens,
    check_and_record_webhook_event,
)
from services.plans import PLAN_CATALOG, get_plan, is_subscription_valid, apply_plan_to_config

logger = logging.getLogger("x_vibebot.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


def _resolve_safe_redirect_url(requested_url: Optional[str], fallback_suffix: str) -> str:
    """Validates success/cancel redirect URLs against configured server origins."""
    safe_origin = resolve_safe_app_base_url(requested_url).rstrip("/")
    if requested_url:
        try:
            parsed = urllib.parse.urlparse(requested_url.strip())
            req_origin = (
                f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
                if parsed.scheme in ("http", "https") and parsed.netloc
                else None
            )
            if req_origin and req_origin == safe_origin.lower():
                path = parsed.path or "/"
                if not path.startswith("/"):
                    path = f"/{path}"
                qs = f"?{parsed.query}" if parsed.query else ""
                return f"{safe_origin}{path}{qs}"
        except Exception:
            pass
    return f"{safe_origin}{fallback_suffix}"


def _resolve_tenant_config_for_webhook(
    db: Session,
    tenant_id: Optional[str],
    customer_id: Optional[str],
) -> Optional[AgentConfig]:
    """Resolves a tenant's AgentConfig from webhook metadata or external payment_customer_id."""
    if tenant_id:
        return get_agent_config(db, tenant_id=str(tenant_id))
    if customer_id:
        return (
            db.query(AgentConfig)
            .filter(AgentConfig.payment_customer_id == str(customer_id))
            .first()
        )
    return None


@router.get("/plans")
async def list_plans():
    """Returns available subscription tiers, daily token quotas, and prices."""
    return {
        "plans": list(PLAN_CATALOG.values()),
        "currency": "USD",
        "default_plan": "starter",
    }


@router.get("/status")
async def get_subscription_status(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Returns the current tenant's subscription tier, active status, trial countdown, and token quota."""
    config = get_agent_config(db, tenant_id=tenant_id)
    plan = get_plan(getattr(config, "plan_tier", "trial"))
    is_valid, eff_status, days_left = is_subscription_valid(config)
    tokens_used = get_tenant_daily_tokens(db, tenant_id=tenant_id)
    token_cap = int(getattr(config, "daily_token_cap", plan["daily_token_cap"]) or plan["daily_token_cap"])

    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "subscription_status": eff_status,
        "is_active_allowed": is_valid,
        "trial_days_remaining": days_left,
        "trial_ends_at": config.trial_ends_at.isoformat() if config.trial_ends_at else None,
        "daily_tokens_used": tokens_used,
        "daily_token_cap": token_cap,
        "daily_token_remaining": max(0, token_cap - tokens_used),
        "daily_action_cap": config.daily_action_cap,
        "daily_original_post_cap": int(getattr(config, "daily_original_post_cap", 3) or 3),
        "max_pending_queue": int(getattr(config, "max_pending_queue", 8) or 8),
    }


@router.post("/checkout")
async def create_checkout_session(
    req: CheckoutRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Initiates payment checkout for a plan via Stripe or Paystack.
    Fails closed (HTTP 502/503) unless explicit non-production dev bypass is enabled.
    """
    plan_id = req.plan_id.lower().strip()
    if plan_id not in PLAN_CATALOG or plan_id == "trial":
        raise HTTPException(status_code=400, detail="Invalid plan selected for paid checkout.")

    target_plan = PLAN_CATALOG[plan_id]
    safe_success_url = _resolve_safe_redirect_url(req.success_url, "/?billing=success")
    safe_cancel_url = _resolve_safe_redirect_url(req.cancel_url, "/?billing=cancel")

    user_row = db.query(User.email).filter(User.tenant_id == tenant_id).first()
    customer_email = (user_row[0] if user_row and user_row[0] else None) or (
        getattr(current_user, "email", None) if current_user is not None else None
    )
    if customer_email:
        customer_email = customer_email.strip()

    stripe_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    paystack_key = (os.getenv("PAYSTACK_SECRET_KEY") or "").strip()

    # 1. Stripe Checkout Integration
    if stripe_key:
        try:
            import stripe
            stripe.api_key = stripe_key
            session_kwargs: Dict[str, Any] = {
                "payment_method_types": ["card"],
                "line_items": [{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"X-VibeBot {target_plan['name']} Plan",
                            "description": target_plan["description"],
                        },
                        "unit_amount": int(target_plan["price_usd"]) * 100,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }],
                "mode": "subscription",
                "success_url": safe_success_url,
                "cancel_url": safe_cancel_url,
                "client_reference_id": tenant_id,
                "metadata": {"tenant_id": tenant_id, "plan_id": plan_id},
            }
            if customer_email and validate_email_address(customer_email):
                session_kwargs["customer_email"] = customer_email
            session = await asyncio.to_thread(stripe.checkout.Session.create, **session_kwargs)
            return {"checkout_url": session.url, "provider": "stripe"}
        except Exception as e:
            logger.error(f"Stripe checkout error for tenant '{tenant_id}': {scrub_secrets(e)}")
            raise HTTPException(
                status_code=502,
                detail="Payment provider error creating checkout session. Please try again shortly.",
            )

    # 2. Paystack Checkout Integration
    if paystack_key:
        try:
            import httpx
            paystack_email = (
                customer_email
                if (customer_email and validate_email_address(customer_email))
                else f"{tenant_id}@vibebot.local"
            )
            headers = {"Authorization": f"Bearer {paystack_key}", "Content-Type": "application/json"}
            data = {
                "amount": int(target_plan["price_usd"]) * 100,
                "currency": "USD",
                "email": paystack_email,
                "metadata": {"tenant_id": tenant_id, "plan_id": plan_id},
                "callback_url": safe_success_url,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    "https://api.paystack.co/transaction/initialize",
                    json=data,
                    headers=headers,
                )
            if res.status_code != 200:
                logger.error(f"Paystack checkout returned HTTP {res.status_code} for tenant '{tenant_id}'.")
                raise HTTPException(
                    status_code=502,
                    detail="Payment provider error creating checkout session. Please try again shortly.",
                )
            d = res.json()
            auth_url = (d.get("data") or {}).get("authorization_url")
            if not d.get("status") or not auth_url:
                logger.error(f"Paystack checkout returned invalid payload for tenant '{tenant_id}'.")
                raise HTTPException(
                    status_code=502,
                    detail="Payment provider error creating checkout session. Please try again shortly.",
                )
            return {"checkout_url": auth_url, "provider": "paystack"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Paystack checkout error for tenant '{tenant_id}': {scrub_secrets(e)}")
            raise HTTPException(
                status_code=502,
                detail="Payment provider error creating checkout session. Please try again shortly.",
            )

    # 3. Fail closed unless explicit non-production dev bypass is enabled
    allow_dev_bypass = (
        not is_production_env()
        and os.getenv("ALLOW_DEV_BILLING_BYPASS", "false").strip().lower() == "true"
    )
    if not allow_dev_bypass:
        raise HTTPException(
            status_code=503,
            detail="Payment checkout is not configured on this server.",
        )

    config = get_agent_config(db, tenant_id=tenant_id)
    apply_plan_to_config(config, plan_id, status="active")
    db.commit()
    logger.info(f"Tenant '{tenant_id}' upgraded to plan '{plan_id}' via explicit dev bypass.")

    return {
        "checkout_url": None,
        "direct_upgrade": True,
        "provider": "direct",
        "message": f"Successfully subscribed to {target_plan['name']}! Daily quota upgraded to {target_plan['daily_token_cap']:,} tokens/day.",
        "plan": target_plan,
    }


@router.post("/webhook")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Universal webhook receiver for Stripe & Paystack subscription events.
    Enforces cryptographic signature verification, paid-status checks, and replay protection.
    """
    body = await request.body()
    stripe_secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    paystack_secret = (os.getenv("PAYSTACK_SECRET_KEY") or "").strip()

    stripe_sig = request.headers.get("stripe-signature")
    paystack_sig = request.headers.get("x-paystack-signature")

    # 1. Stripe Webhook Handling
    if stripe_sig is not None:
        if not stripe_secret:
            raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured.")
        try:
            import stripe
            event = stripe.Webhook.construct_event(body, stripe_sig, stripe_secret)
        except Exception as e:
            logger.warning(f"Stripe webhook signature verification failed: {scrub_secrets(e)}")
            raise HTTPException(status_code=400, detail="Invalid Stripe signature.")

        event_id = str(event.get("id") or "").strip() or f"stripe:{hashlib.sha256(body).hexdigest()}"
        if not check_and_record_webhook_event(db, event_id, "stripe"):
            return {"status": "duplicate", "message": "Event already processed."}

        event_type = str(event.get("type") or "")
        obj = (event.get("data") or {}).get("object") or {}
        metadata = obj.get("metadata") or {}
        if not metadata and isinstance(obj.get("subscription_details"), dict):
            metadata = obj["subscription_details"].get("metadata") or {}

        tenant_id = metadata.get("tenant_id") or obj.get("client_reference_id")
        customer_id = obj.get("customer")

        if event_type in ("checkout.session.completed", "invoice.payment_succeeded"):
            if event_type == "checkout.session.completed":
                if str(obj.get("payment_status") or "").lower() != "paid":
                    db.commit()
                    logger.info(f"Ignored unpaid Stripe checkout session '{event_id}'.")
                    return {"status": "ignored", "message": "Checkout session not paid."}
            elif obj.get("paid") is False or (
                obj.get("status") is not None and str(obj.get("status")).lower() != "paid"
            ):
                db.commit()
                return {"status": "ignored", "message": "Invoice not marked paid."}

            plan_id = str(metadata.get("plan_id") or "starter").strip().lower()
            if plan_id not in PLAN_CATALOG or plan_id == "trial":
                plan_id = "starter"

            config = _resolve_tenant_config_for_webhook(db, tenant_id, customer_id)
            if config is not None:
                apply_plan_to_config(config, plan_id, status="active")
                if customer_id:
                    config.payment_customer_id = str(customer_id)
                logger.info(f"Stripe webhook applied plan '{plan_id}' to tenant '{config.tenant_id}'.")

        elif event_type in ("customer.subscription.deleted", "invoice.payment_failed", "charge.refunded"):
            should_revoke = True
            if event_type == "charge.refunded":
                refunded_flag = obj.get("refunded")
                amt = obj.get("amount")
                amt_ref = obj.get("amount_refunded")
                if refunded_flag is False and isinstance(amt, (int, float)) and isinstance(amt_ref, (int, float)):
                    should_revoke = amt_ref >= amt

            if should_revoke:
                config = _resolve_tenant_config_for_webhook(db, tenant_id, customer_id)
                if config is not None:
                    config.subscription_status = (
                        "expired" if event_type == "invoice.payment_failed" else "canceled"
                    )
                    config.is_active = False
                    logger.info(
                        f"Stripe webhook '{event_type}' deactivated subscription for tenant '{config.tenant_id}'."
                    )

        db.commit()
        return {"status": "success"}

    # 2. Paystack Webhook Handling (HMAC-SHA512 over raw body)
    if paystack_sig is not None:
        if not paystack_secret:
            raise HTTPException(status_code=503, detail="Paystack webhook secret is not configured.")
        expected_sig = hmac.new(
            paystack_secret.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, paystack_sig.strip().lower()):
            logger.warning("Paystack webhook signature verification failed.")
            raise HTTPException(status_code=400, detail="Invalid Paystack signature.")

        try:
            payload_data = json.loads(body.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Paystack webhook payload.")

        event_type = str(payload_data.get("event") or "")
        data_obj = payload_data.get("data") or {}
        if not isinstance(data_obj, dict):
            data_obj = {}

        raw_id = data_obj.get("id") or data_obj.get("reference") or payload_data.get("id")
        event_id = (
            f"paystack:{event_type}:{raw_id}"
            if raw_id
            else f"paystack:{hashlib.sha256(body).hexdigest()}"
        )
        if not check_and_record_webhook_event(db, event_id, "paystack"):
            return {"status": "duplicate", "message": "Event already processed."}

        raw_meta = data_obj.get("metadata")
        if isinstance(raw_meta, str):
            try:
                metadata = json.loads(raw_meta)
            except Exception:
                metadata = {}
        elif isinstance(raw_meta, dict):
            metadata = raw_meta
        else:
            metadata = {}

        customer_obj = data_obj.get("customer")
        customer_code = (
            customer_obj.get("customer_code")
            if isinstance(customer_obj, dict)
            else None
        )
        tenant_id = metadata.get("tenant_id")

        if event_type == "charge.success":
            tx_status = str(data_obj.get("status") or "success").lower()
            if tx_status == "success":
                plan_id = str(metadata.get("plan_id") or "starter").strip().lower()
                if plan_id not in PLAN_CATALOG or plan_id == "trial":
                    plan_id = "starter"
                config = _resolve_tenant_config_for_webhook(db, tenant_id, customer_code)
                if config is not None:
                    apply_plan_to_config(config, plan_id, status="active")
                    if customer_code:
                        config.payment_customer_id = str(customer_code)
                    logger.info(f"Paystack webhook applied plan '{plan_id}' to tenant '{config.tenant_id}'.")

        elif event_type in (
            "subscription.disable",
            "subscription.not_renew",
            "invoice.payment_failed",
            "refund.processed",
        ):
            config = _resolve_tenant_config_for_webhook(db, tenant_id, customer_code)
            if config is not None:
                config.subscription_status = (
                    "expired" if event_type == "invoice.payment_failed" else "canceled"
                )
                config.is_active = False
                logger.info(
                    f"Paystack webhook '{event_type}' deactivated subscription for tenant '{config.tenant_id}'."
                )

        db.commit()
        return {"status": "success"}

    if stripe_secret or paystack_secret:
        raise HTTPException(status_code=400, detail="Missing payment webhook signature.")

    return {"status": "ignored", "message": "No active payment provider webhook configured."}
