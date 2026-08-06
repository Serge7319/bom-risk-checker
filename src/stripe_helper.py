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
