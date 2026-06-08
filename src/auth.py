import streamlit as st
from datetime import datetime, timedelta


def show_auth_ui(supabase, cookie_manager):
    st.subheader("Sign in to BOM Risk Checker")

    auth_mode = st.radio(
        "Choose an option",
        ["Login", "Create Account"],
        horizontal=True,
    )

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if auth_mode == "Create Account":
        if st.button("Create Account"):
            try:
                response = supabase.auth.sign_up(
                    {
                        "email": email,
                        "password": password,
                    }
                )

                st.success("Account created. Please check your email if confirmation is required.")

                st.session_state["user"] = response.user
                st.session_state["access_token"] = response.session.access_token
                st.session_state["refresh_token"] = response.session.refresh_token
                st.rerun()
                
            except Exception as error:
                st.error(f"Signup failed: {error}")

    else:
        if st.button("Login"):
            try:
                response = supabase.auth.sign_in_with_password(
                    {
                        "email": email,
                        "password": password,
                    }
                )

                st.success("Logged in successfully.")
                expires_at = datetime.now() + timedelta(days=7)

                auth_cookie_value = {
                    "access_token": response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                }

                cookie_manager.set(
                    cookie="bom_auth",
                    val=auth_cookie_value,
                    expires_at=expires_at,
                    key="login_set_bom_auth",
                )

                st.session_state["user"] = response.user
                st.session_state["access_token"] = response.session.access_token
                st.session_state["refresh_token"] = response.session.refresh_token
                st.rerun()

            except Exception as error:
                st.error(f"Login failed: {error}")