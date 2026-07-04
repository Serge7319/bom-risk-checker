import streamlit as st
from datetime import datetime, timedelta


def _set_auth_cookie(cookie_manager, session, key: str):
    if not cookie_manager or not session:
        return
    expires_at = datetime.now() + timedelta(days=7)
    cookie_manager.set(
        cookie="bom_auth",
        val={
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
        },
        expires_at=expires_at,
        key=key,
    )


def show_auth_ui(supabase, cookie_manager=None):
    """Premium public landing + auth flow.

    Handles Supabase email-confirmation correctly: signup may return session=None.
    In that case we show a confirmation message instead of reading session.access_token.
    """
    st.markdown(
        """
        <style>
        html, body, .stApp, [data-testid="stAppViewContainer"] {
            background:#F6F8FB!important;
            color:#0F172A!important;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif!important;
        }
        [data-testid="stHeader"] { background:rgba(246,248,251,.92)!important; border-bottom:1px solid #E5E7EB!important; }
        section[data-testid="stSidebar"] { display:none!important; }
        .block-container { max-width:1180px!important; padding-top:1.6rem!important; padding-left:2rem!important; padding-right:2rem!important; }
        .auth-nav { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:24px; }
        .auth-logo { display:flex; align-items:center; gap:11px; color:#0F172A!important; font-weight:900; font-size:16px; }
        .auth-logo-mark { width:34px; height:34px; border-radius:10px; display:grid; place-items:center; background:#2563EB; color:white!important; font-weight:900; box-shadow:0 12px 24px rgba(37,99,235,.22); }
        .auth-nav-links { display:flex; gap:18px; align-items:center; color:#64748B!important; font-size:13px; font-weight:750; }
        .auth-shell { display:grid; grid-template-columns:minmax(0,1.15fr) 420px; gap:34px; align-items:stretch; }
        .auth-hero { background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 48%,#EFF6FF 100%); border:1px solid #E5E7EB; border-radius:24px; padding:44px; box-shadow:0 18px 45px rgba(15,23,42,.07); min-height:620px; position:relative; overflow:hidden; }
        .auth-eyebrow { display:inline-flex; background:#EFF6FF; color:#2563EB!important; border:1px solid #BFDBFE; font-size:12px; font-weight:900; letter-spacing:.07em; text-transform:uppercase; border-radius:999px; padding:7px 12px; margin-bottom:20px; }
        .auth-title { color:#0F172A!important; font-size:54px; line-height:1.02; font-weight:950; letter-spacing:-.055em; max-width:760px; margin:0 0 18px 0; }
        .auth-subtitle { color:#52647A!important; font-size:18px; line-height:1.65; max-width:690px; margin:0 0 28px 0; }
        .auth-feature-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:28px 0; }
        .auth-feature { background:rgba(255,255,255,.72); border:1px solid #E5E7EB; border-radius:16px; padding:16px; }
        .auth-feature strong { display:block; color:#0F172A!important; font-size:14px; margin-bottom:6px; }
        .auth-feature span { display:block; color:#64748B!important; font-size:13px; line-height:1.45; }
        .auth-compatible { display:flex; flex-wrap:wrap; gap:10px; margin-top:24px; }
        .auth-chip { background:#FFFFFF; color:#334155!important; border:1px solid #E5E7EB; border-radius:999px; padding:7px 11px; font-size:12px; font-weight:800; }
        .auth-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:24px; padding:28px; box-shadow:0 18px 45px rgba(15,23,42,.08); align-self:start; }
        .auth-card h2 { color:#0F172A!important; font-size:28px; letter-spacing:-.035em; margin:0 0 6px 0; }
        .auth-card p { color:#64748B!important; font-size:14px; line-height:1.55; margin:0 0 18px 0; }
        div[data-testid="stTextInput"] input { background:#FFFFFF!important; color:#0F172A!important; border:1px solid #CBD5E1!important; border-radius:10px!important; min-height:42px!important; }
        div[data-testid="stTextInput"] input:focus { border-color:#2563EB!important; box-shadow:0 0 0 3px rgba(37,99,235,.12)!important; }
        div.stButton > button { background:#2563EB!important; color:#FFFFFF!important; border:1px solid #2563EB!important; border-radius:10px!important; min-height:44px!important; font-weight:800!important; width:100%!important; }
        div.stButton > button:hover { background:#1D4ED8!important; border-color:#1D4ED8!important; color:#FFFFFF!important; }
        div.stButton > button * { color:#FFFFFF!important; }
        div[data-testid="stRadio"] label { color:#0F172A!important; }
        @media(max-width:900px){ .auth-shell{grid-template-columns:1fr;} .auth-title{font-size:40px;} .auth-hero{min-height:auto;padding:30px;} }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="auth-nav">
          <div class="auth-logo"><div class="auth-logo-mark">B</div><span>BOM Risk Checker</span></div>
          <div class="auth-nav-links"><span>Features</span><span>Pricing</span><span>Docs</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([1.45, 1], gap="large")

    with left_col:
        st.markdown(
            """
            <div class="auth-hero">
              <div class="auth-eyebrow">Engineering Supply Chain Intelligence</div>
              <h1 class="auth-title">Analyze BOM risk. Detect obsolescence. Find better parts.</h1>
              <p class="auth-subtitle">Upload a CSV or Excel BOM and get lifecycle, sourcing, supplier, and alternative-component intelligence built for electronics teams.</p>
              <div class="auth-feature-grid">
                <div class="auth-feature"><strong>Lifecycle Intelligence</strong><span>Flag obsolete, NRND, replacement-suggested, and unknown lifecycle components.</span></div>
                <div class="auth-feature"><strong>Supplier Intelligence</strong><span>Review stock, supplier coverage, pricing, and sourcing concentration.</span></div>
                <div class="auth-feature"><strong>Alternative Finder</strong><span>Rank replacement candidates by compatibility, availability, and risk.</span></div>
                <div class="auth-feature"><strong>Executive Reports</strong><span>Export summaries and BOM risk reports for engineering and procurement review.</span></div>
              </div>
              <div class="auth-compatible">
                <span class="auth-chip">Mouser</span>
                <span class="auth-chip">DigiKey</span>
                <span class="auth-chip">Newark</span>
                <span class="auth-chip">CSV/XLSX</span>
                <span class="auth-chip">Octopart planned</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right_col:
        st.markdown(
            """
            <div class="auth-card">
              <h2>Welcome back</h2>
              <p>Sign in or create an account to continue to your BOM workspace.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        auth_mode = st.radio(
            "Choose an option",
            ["Login", "Create Account"],
            horizontal=True,
            label_visibility="collapsed",
        )

        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if auth_mode == "Create Account":
            if st.button("Create Account"):
                if not email or not password:
                    st.warning("Please enter an email and password.")
                    return
                try:
                    response = supabase.auth.sign_up({"email": email, "password": password})
                    if getattr(response, "session", None):
                        st.session_state["user"] = response.user
                        st.session_state["access_token"] = response.session.access_token
                        st.session_state["refresh_token"] = response.session.refresh_token
                        _set_auth_cookie(cookie_manager, response.session, "signup_set_bom_auth")
                        st.success("Account created and logged in successfully.")
                        st.rerun()
                    else:
                        st.success("Account created. Please check your email to confirm your account, then return here to log in.")
                except Exception as error:
                    st.error(f"Signup failed: {error}")
        else:
            if st.button("Login"):
                if not email or not password:
                    st.warning("Please enter your email and password.")
                    return
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    if not getattr(response, "session", None):
                        st.error("Login failed: no session was returned. Please confirm your email and try again.")
                        return
                    _set_auth_cookie(cookie_manager, response.session, "login_set_bom_auth")
                    st.session_state["user"] = response.user
                    st.session_state["access_token"] = response.session.access_token
                    st.session_state["refresh_token"] = response.session.refresh_token
                    st.success("Logged in successfully.")
                    st.rerun()
                except Exception as error:
                    st.error(f"Login failed: {error}")
