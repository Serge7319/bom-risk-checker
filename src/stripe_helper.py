import stripe

from src.secrets import get_secret


def _ensure_stripe_api_key() -> None:
    if stripe.api_key:
        return
    stripe.api_key = get_secret("STRIPE_SECRET_KEY", required=True)


def create_checkout_session(price_id, user_email, user_id, success_url, cancel_url):
    _ensure_stripe_api_key()
    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        customer_email=user_email,
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
        },
        subscription_data={
            "metadata": {
                "user_id": user_id,
            }
        },
    )

    return session.url


def create_billing_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Billing Portal session and return its hosted URL.

    ``customer_id`` must come from the authenticated user's stored profile row
    (never from query params, browser state, or user-entered input).
    """
    resolved_customer = str(customer_id or "").strip()
    resolved_return = str(return_url or "").strip()
    if not resolved_customer:
        raise ValueError("Missing Stripe customer id")
    if not resolved_return:
        raise ValueError("Missing billing portal return URL")

    _ensure_stripe_api_key()
    session = stripe.billing_portal.Session.create(
        customer=resolved_customer,
        return_url=resolved_return,
    )
    return str(session.url)


def customer_may_manage_billing(*, role: str | None, stripe_customer_id: str | None) -> bool:
    """True when a non-admin customer has a stored Stripe customer id for portal access."""
    if str(role or "").strip().lower() == "admin":
        return False
    return bool(str(stripe_customer_id or "").strip())
