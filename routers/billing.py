"""
Billing & Subscription Router for X-VibeBot.
Manages subscription tiers, plan status, trial life-cycle, payment checkout, and webhooks.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db, get_agent_config, get_tenant_daily_tokens
from core.dependencies import get_current_tenant
from services.plans import PLAN_CATALOG, get_plan, is_subscription_valid, apply_plan_to_config

logger = logging.getLogger("x_vibebot.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


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
    payload: CheckoutRequest,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Initiates payment checkout for a plan.
    Supports plug-and-play Stripe or Paystack when keys are provided,
    with a graceful manual upgrade fallback.
    """
    plan_id = payload.plan_id.lower().strip()
    if plan_id not in PLAN_CATALOG or plan_id == "trial":
        raise HTTPException(status_code=400, detail="Invalid plan selected for paid checkout.")

    target_plan = PLAN_CATALOG[plan_id]
    stripe_key = os.getenv("STRIPE_SECRET_KEY")
    paystack_key = os.getenv("PAYSTACK_SECRET_KEY")

    # 1. Stripe Checkout Integration
    if stripe_key:
        try:
            import stripe
            stripe.api_key = stripe_key
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"X-VibeBot {target_plan['name']} Plan",
                            "description": target_plan["description"],
                        },
                        "unit_amount": target_plan["price_usd"] * 100,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }],
                mode="subscription",
                success_url=payload.success_url or "http://localhost:3000/?billing=success",
                cancel_url=payload.cancel_url or "http://localhost:3000/?billing=cancel",
                client_reference_id=tenant_id,
                metadata={"tenant_id": tenant_id, "plan_id": plan_id},
            )
            return {"checkout_url": session.url, "provider": "stripe"}
        except Exception as e:
            logger.error(f"Stripe checkout error: {e}")

    # 2. Paystack Checkout Integration
    if paystack_key:
        try:
            import httpx
            headers = {"Authorization": f"Bearer {paystack_key}", "Content-Type": "application/json"}
            data = {
                "amount": target_plan["price_usd"] * 100,
                "email": f"{tenant_id}@vibebot.ai",
                "metadata": {"tenant_id": tenant_id, "plan_id": plan_id},
                "callback_url": payload.success_url or "http://localhost:3000/?billing=success",
            }
            async with httpx.AsyncClient() as client:
                res = await client.post("https://api.paystack.co/transaction/initialize", json=data, headers=headers)
                if res.status_code == 200:
                    d = res.json()
                    return {"checkout_url": d["data"]["authorization_url"], "provider": "paystack"}
        except Exception as e:
            logger.error(f"Paystack checkout error: {e}")

    # 3. Direct/Sandbox Mode: Instant Super Admin or Self-Serve activation for testing
    config = get_agent_config(db, tenant_id=tenant_id)
    apply_plan_to_config(config, plan_id, status="active")
    db.commit()
    logger.info(f"Tenant '{tenant_id}' upgraded to plan '{plan_id}' via direct checkout mode.")

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
    Automatically applies plan quotas to the corresponding tenant upon successful payment.
    """
    body = await request.body()
    stripe_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    stripe_sig = request.headers.get("stripe-signature")

    if stripe_secret and stripe_sig:
        try:
            import stripe
            event = stripe.Webhook.construct_event(body, stripe_sig, stripe_secret)
            if event["type"] in ("checkout.session.completed", "invoice.payment_succeeded"):
                obj = event["data"]["object"]
                metadata = obj.get("metadata") or {}
                tenant_id = metadata.get("tenant_id") or obj.get("client_reference_id")
                plan_id = metadata.get("plan_id", "starter")
                if tenant_id:
                    config = get_agent_config(db, tenant_id=tenant_id)
                    apply_plan_to_config(config, plan_id, status="active")
                    config.payment_customer_id = obj.get("customer")
                    db.commit()
                    logger.info(f"Webhook applied plan '{plan_id}' to tenant '{tenant_id}'.")
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Stripe webhook verification error: {e}")
            raise HTTPException(status_code=400, detail="Invalid Stripe signature.")

    return {"status": "ignored", "message": "No active payment provider webhook configured."}
