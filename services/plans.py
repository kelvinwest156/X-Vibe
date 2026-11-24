"""
Subscription & Plan Catalog Service for X-VibeBot.
Defines the single source of truth for all subscription tiers, daily token quotas,
action limits, and trial lifecycle management.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

PLAN_CATALOG: Dict[str, Dict[str, Any]] = {
    "trial": {
        "id": "trial",
        "name": "Free 7-Day Trial",
        "price_usd": 0,
        "billing_period": "7_days",
        "daily_token_cap": 15000,
        "daily_action_cap": 10,
        "hourly_action_cap": 4,
        "daily_original_post_cap": 2,
        "max_pending_queue": 6,
        "trial_days": 7,
        "auto_pilot_included": True,
        "description": "Full access to X-VibeBot studio with 15,000 daily AI tokens for 7 days."
    },
    "starter": {
        "id": "starter",
        "name": "Starter",
        "price_usd": 9,
        "billing_period": "month",
        "daily_token_cap": 50000,
        "daily_action_cap": 15,
        "hourly_action_cap": 6,
        "daily_original_post_cap": 3,
        "max_pending_queue": 8,
        "trial_days": 0,
        "auto_pilot_included": True,
        "description": "Ideal for solo creators and builders growing an engaged organic audience."
    },
    "pro": {
        "id": "pro",
        "name": "Creator Pro",
        "price_usd": 24,
        "billing_period": "month",
        "daily_token_cap": 150000,
        "daily_action_cap": 35,
        "hourly_action_cap": 10,
        "daily_original_post_cap": 6,
        "max_pending_queue": 12,
        "trial_days": 0,
        "auto_pilot_included": True,
        "description": "For serious influencers and founders scaling high authority & daily presence."
    },
    "growth": {
        "id": "growth",
        "name": "Growth",
        "price_usd": 59,
        "billing_period": "month",
        "daily_token_cap": 400000,
        "daily_action_cap": 50,
        "hourly_action_cap": 12,
        "daily_original_post_cap": 6,
        "max_pending_queue": 20,
        "trial_days": 0,
        "auto_pilot_included": True,
        "description": "Maximum power: highest token quotas, priority AI scans, and unlimited manual posting."
    }
}


def get_plan(plan_id: str) -> Dict[str, Any]:
    """Retrieves plan dictionary by id, falling back to 'starter' if unknown."""
    return PLAN_CATALOG.get(plan_id) or PLAN_CATALOG["starter"]


def is_subscription_valid(config: Any) -> Tuple[bool, str, Optional[int]]:
    """
    Evaluates whether a tenant's subscription allows active bot operations.
    Returns:
        (is_allowed: bool, effective_status: str, trial_days_remaining: Optional[int])
    """
    tier = getattr(config, "plan_tier", "trial") or "trial"
    status = getattr(config, "subscription_status", "trialing") or "trialing"
    trial_ends = getattr(config, "trial_ends_at", None)

    # 1. Paid active subscriptions are always valid
    if tier in ("starter", "pro", "growth") and status == "active":
        return True, "active", None

    # 2. Grandfathered or manual admin override
    if status == "active":
        return True, "active", None

    # 3. Check Free Trial validity
    if tier == "trial" or status == "trialing":
        if trial_ends:
            now_utc = datetime.utcnow()
            if now_utc <= trial_ends:
                diff = trial_ends - now_utc
                days_left = max(0, diff.days + (1 if diff.seconds > 0 else 0))
                return True, "trialing", days_left
            else:
                return False, "expired", 0
        else:
            # No trial_ends_at set: default to 7 days from now
            return True, "trialing", 7

    # 4. Explicitly expired, canceled, or suspended
    if status in ("expired", "canceled", "suspended"):
        return False, status, 0

    return False, "expired", 0


def apply_plan_to_config(config: Any, plan_id: str, status: str = "active", trial_days: Optional[int] = None) -> None:
    """
    Applies the resource caps, token quotas, and post caps of a target plan to an AgentConfig instance.
    Does NOT commit the DB session; caller handles commit.
    """
    plan = get_plan(plan_id)
    config.plan_tier = plan["id"]
    config.subscription_status = status
    config.daily_token_cap = plan["daily_token_cap"]
    config.daily_action_cap = plan["daily_action_cap"]
    config.hourly_action_cap = plan["hourly_action_cap"]
    config.daily_original_post_cap = plan["daily_original_post_cap"]
    config.max_pending_queue = plan["max_pending_queue"]

    if plan["id"] == "trial" or status == "trialing":
        days = trial_days if trial_days is not None else plan["trial_days"]
        config.trial_ends_at = datetime.utcnow() + timedelta(days=days)
    elif status == "active":
        config.trial_ends_at = None
