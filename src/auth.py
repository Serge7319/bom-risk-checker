import streamlit as st
from datetime import datetime, timedelta


def show_auth_ui(supabase, cookie_manager=None):
    st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] {background:#F5F7FB!important; color:#0F172A!important;}
    [data-testid="stSidebar"] {background:#FFFFFF!important; border-right:1px solid #E2E8F0!important;}
    [data-testid="stSidebar"] * {color:#0F172A!important;}
    .block-container {max-width:1180px!important; padding-top:3rem!important;}
    div[data-testid="stTextInput"] input {background:#FFFFFF!important; border:1px solid #CBD5E1!important; color:#0F172A!important; border-radius:10px!important;}
    div.stButton > button {background:#2563EB!important; color:#FFFFFF!important; border:1px solid #2563EB!important; border-radius:10px!important; font-weight:750!important;}
    </style>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div style="max-width:920px;margin:40px auto 24px auto;padding:42px 46px;border:1px solid #E2E8F0;border-radius:18px;background:linear-gradient(135deg,#FFFFFF 0%,#EFF6FF 100%);box-shadow:0 18px 45px rgba(15,23,42,.08);">
      <div style="display:inline-block;background:#EFF6FF;color:#2563EB;font-weight:800;font-size:12px;letter-spacing:.08em;text-transform:uppercase;border-radius:999px;padding:7px 12px;margin-bottom:18px;">BOM Risk Intelligence</div>
      <h1 style="margin:0 0 10px 0;color:#0F172A;font-size:42px;line-height:1.05;">Sign in to BOM Risk Checker</h1>
      <p style="margin:0;color:#52647A;font-size:17px;">Review BOM risk, find better alternatives, and monitor supply-chain exposure from one workspace.</p>
    </div>
    """, unsafe_allow_html=True)

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

                if getattr(response, "session", None):
                    st.success("Account created and logged in successfully.")
                    st.session_state["user"] = response.user
                    st.session_state["access_token"] = response.session.access_token
                    st.session_state["refresh_token"] = response.session.refresh_token

                    if cookie_manager:
                        expires_at = datetime.now() + timedelta(days=7)
                        cookie_manager.set(
                            cookie="bom_auth",
                            val={
                                "access_token": response.session.access_token,
                                "refresh_token": response.session.refresh_token,
                            },
                            expires_at=expires_at,
                            key="signup_set_bom_auth",
                        )
                    st.rerun()
                else:
                    st.success("Account created. Please check your email to confirm your account, then return here to log in.")
                
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