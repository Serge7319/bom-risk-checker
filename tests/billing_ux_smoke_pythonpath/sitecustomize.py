"""Test-only hook for Settings billing checkout UX smoke.

Stubs price-id lookup and checkout-session creation so the real Streamlit
handoff can be exercised without Stripe keys, Price IDs, or live charges.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.auth_gate_smoke_adapter import install_production_path_smoke_patches

install_production_path_smoke_patches()

import src.authenticated_runtime as runtime_mod
import src.stripe_helper as stripe_helper

_SMOKE_PRICE_IDS = {
    "STRIPE_STARTER_PRICE_ID",
    "STRIPE_PRO_PRICE_ID",
    "STRIPE_BUSINESS_PRICE_ID",
}
_ORIG_GET_SECRET = runtime_mod.get_secret


def _smoke_get_secret(name, *, default=None, required=False):
    if name in _SMOKE_PRICE_IDS:
        return "price_smoke_billing_ux"
    return _ORIG_GET_SECRET(name, default=default, required=required)


def _smoke_create_checkout_session(
    price_id,
    user_email,
    user_id,
    success_url,
    cancel_url,
    cadivor_plan=None,
    **_kwargs,
):
    del price_id, user_email, user_id, success_url, cancel_url
    return "https://checkout.stripe.com/c/pay/cs_test_billing_ux_smoke"


runtime_mod.get_secret = _smoke_get_secret
stripe_helper.create_checkout_session = _smoke_create_checkout_session
