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
    PLAN_STUDENT,
    PLAN_ENTERPRISE,
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
            "Live Stripe keys are blocked in this environment."
            if mode == "live-blocked"
            else "Billing checkout is prepared for test-mode wiring only. "
            "No checkout sessions or charges are created yet."
        ),
    }


def plan_catalog() -> list[dict[str, Any]]:
    """Customer-facing plans from the same registry used by enforcement."""
    catalog = []
    for name in (PLAN_STUDENT, PLAN_STARTER, PLAN_PROFESSIONAL, PLAN_BUSINESS, PLAN_ENTERPRISE):
        plan = get_plan(name)
        catalog.append(
            {
                "name": name,
                "price": plan.get("price"),
                "description": plan.get("description"),
                "monthly_bom_limit": plan.get("monthly_bom_limit"),
                "max_parts_per_bom": plan.get("max_parts_per_bom"),
                "max_saved_boms": plan.get("max_saved_boms"),
                "ai_credits": plan.get("ai_credits"),
                "included_users": plan.get("included_users"),
                "monitored_parts_limit": plan.get("monitored_parts_limit"),
                "team_features": bool(plan.get("team_features")),
                "api_access": bool(plan.get("api_access")),
                "datasheet_comparison": bool(plan.get("datasheet_comparison")),
                "student_watermark": bool(plan.get("student_watermark")),
                "can_create_analyses": bool(plan.get("can_create_analyses")),
                "purchase_token": CHECKOUT_PLAN_TOKENS.get(name),
            }
        )
    return catalog


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


def checkout_readiness(
    *,
    workspace_id: str = "readiness-probe",
    user_id: str = "readiness-probe",
) -> dict[str, Any]:
    """Status for the checkout flow the app actually uses.

    The migration API still returns ``not_implemented`` from
    ``prepare_checkout_intent`` even when the enable flag and test Stripe keys
    are present. Ready is reserved for a successful checkout intent.
    """
    enabled = checkout_enabled()
    if not enabled:
        return {"status": "not_connected", "enabled": False}
    plan_token = next(iter(CHECKOUT_PLAN_TOKENS.values()), "")
    if not plan_token:
        return {"status": "unknown", "enabled": True}
    result = prepare_checkout_intent(
        workspace_id=workspace_id,
        plan_token=str(plan_token),
        user_id=user_id,
    )
    if result.get("ok"):
        return {"status": "ready", "enabled": True}
    code = str(result.get("code") or "")
    if code == "not_implemented":
        return {
            "status": "not_connected",
            "enabled": True,
            "code": "not_implemented",
        }
    if code in {"checkout_disabled", "live_blocked", "unknown_plan"}:
        return {"status": "not_connected", "enabled": enabled, "code": code}
    return {"status": "unknown", "enabled": enabled, "code": code or None}
