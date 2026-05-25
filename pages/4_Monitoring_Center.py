import streamlit as st
import pandas as pd
from supabase import create_client

st.title("📡 Monitoring Center")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)

if "user" not in st.session_state:
    st.warning("Please log in.")
    st.stop()

current_user = st.session_state["user"]

user_id = current_user.id
user_email = current_user.email

st.success(f"Monitoring dashboard loaded for {user_email}")