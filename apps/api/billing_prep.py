"""Stripe test-mode preparation for the migration API.

Does not create Checkout sessions or charges. Surfaces configured price secret
*names* from ``src.plans`` and reports whether test-mode keys appear present
without exposing secret values.
"""
from __future__ import annotations

import os
from typing import Any

from src.plans import (
    CHECKOUT_PLAN_TOKENS,
    CHECKOUT_PRICE_SECRETS,
    PLAN_BUSINESS,
    PLAN_PROFESSIONAL,
    PLAN_STARTER,
    get_plan,
)


def _has_secret(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def stripe_mode() -> str:
    key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not key:
        return "unconfigured"
    if key.startswith("sk_test_"):
        return "test"
    if key.startswith("sk_live_"):
        return "live-blocked"
    return "unknown"


def checkout_enabled() -> bool:
    if (os.environ.get("CADIVOR_MIGRATION_STRIPE_CHECKOUT_ENABLED") or "").strip() == "1":
        return stripe_mode() == "test"
    return False


def billing_status() -> dict[str, Any]:
    mode = stripe_mode()
    plans = []
    for plan_name in (PLAN_STARTER, PLAN_PROFESSIONAL, PLAN_BUSINESS):
        env_name = CHECKOUT_PRICE_SECRETS.get(plan_name, "")
        plan = get_plan(plan_name)
        plans.append(
            {
                "name": plan_name,
                "token": CHECKOUT_PLAN_TOKENS.get(plan_name),
                "price_env": env_name,
                "price_id_configured": _has_secret(env_name) if env_name else False,
                "monthly_bom_limit": plan.get("monthly_bom_limit"),
                "max_parts_per_bom": plan.get("max_parts_per_bom"),
                "max_saved_boms": plan.get("max_saved_boms"),
            }
        )
    return {
        "ok": True,
        "stripe_mode": mode,
        "checkout_enabled": checkout_enabled(),
        "charges_created": False,
        "webhook_configured": _has_secret("STRIPE_WEBHOOK_SECRET"),
        "plans": plans,
        "gap": (
            "Live Stripe keys are blocked on the migration API."
            if mode == "live-blocked"
            else "Stripe Checkout is prepared for test-mode wiring only. "
            "No sessions or charges are created by the migration API."
        ),
    }


def prepare_checkout_intent(
    *,
    workspace_id: str,
    plan_token: str,
    user_id: str,
) -> dict[str, Any]:
    token = str(plan_token or "").strip().lower()
    reverse = {v: k for k, v in CHECKOUT_PLAN_TOKENS.items()}
    plan_name = reverse.get(token)
    if not plan_name:
        return {"ok": False, "detail": "Unknown plan token", "code": "unknown_plan"}
    status = billing_status()
    if status["stripe_mode"] == "live-blocked":
        return {"ok": False, "detail": "Live Stripe keys are not allowed", "code": "live_blocked"}
    prepared = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "plan": plan_name,
        "token": token,
        "price_env": CHECKOUT_PRICE_SECRETS.get(plan_name),
    }
    if not checkout_enabled():
        return {
            "ok": False,
            "detail": "Migration Stripe checkout is disabled (test-mode prep only)",
            "code": "checkout_disabled",
            "prepared": prepared,
            "billing": status,
        }
    return {
        "ok": False,
        "detail": "Checkout session creation is not implemented on the migration API yet",
        "code": "not_implemented",
        "prepared": prepared,
        "billing": status,
    }
