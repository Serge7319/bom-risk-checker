import stripe
import streamlit as st

stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]


def create_checkout_session(price_id, user_email, user_id, success_url, cancel_url):
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