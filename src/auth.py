import streamlit as st
from datetime import datetime, timedelta


def _remember_session(response, cookie_manager=None):
    """Store Supabase session when the provider returns one.

    Supabase returns response.session as None when email confirmation is required.
    In that case we should show a confirmation message, not crash.
    """
    if not getattr(response, "session", None):
        return False

    expires_at = datetime.now() + timedelta(days=7)
    auth_cookie_value = {
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
    }

    if cookie_manager:
        cookie_manager.set(
            cookie="bom_auth",
            val=auth_cookie_value,
            expires_at=expires_at,
            key="login_set_bom_auth",
        )

    st.session_state["user"] = response.user
    st.session_state["access_token"] = response.session.access_token
    st.session_state["refresh_token"] = response.session.refresh_token
    return True


def show_auth_ui(supabase, cookie_manager=None):
    st.markdown(
        """
        <div class="brc-hero">
            <div class="brc-eyebrow">BOM Risk Intelligence</div>
            <div class="brc-hero-title">Sign in to BOM Risk Checker</div>
            <p class="brc-hero-subtitle">Review BOM risk, find better alternatives, and monitor supply-chain exposure from one workspace.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

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

                if _remember_session(response, cookie_manager):
                    st.success("Account created and signed in successfully.")
                    st.rerun()
                else:
                    st.success(
                        "Account created. Please check your email and confirm your account before logging in."
                    )

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

                if _remember_session(response, cookie_manager):
                    st.success("Logged in successfully.")
                    st.rerun()
                else:
                    st.error("Login did not return a session. Please confirm your email and try again.")

            except Exception as error:
                st.error(f"Login failed: {error}")
