import stripe
import streamlit as st

stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]