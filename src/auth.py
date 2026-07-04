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

    v2.2: The landing page remains the marketing page, but Sign In / Get Started
    now jump directly to a compact workspace access form near the top of the page.
    """
    st.markdown(
        """
        <style>
        html, body, .stApp, [data-testid="stAppViewContainer"] {
            background:#F6F8FB!important;
            color:#0F172A!important;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif!important;
        }
        [data-testid="stHeader"] {
            background:rgba(246,248,251,.92)!important;
            border-bottom:1px solid #E5E7EB!important;
            backdrop-filter:blur(10px);
        }
        section[data-testid="stSidebar"] { display:none!important; }
        .block-container {
            width:95vw!important;
            max-width:1800px!important;
            padding-top:1.25rem!important;
            padding-left:1.25rem!important;
            padding-right:1.25rem!important;
            padding-bottom:4rem!important;
        }
        .brc-public-page { width:100%; margin:0 auto; }
        .auth-nav {
            width:100%;
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:24px;
            margin:0 0 34px 0;
        }
        .auth-logo {
            display:flex;
            align-items:center;
            gap:12px;
            color:#0F172A!important;
            font-weight:900;
            font-size:18px;
            letter-spacing:-.02em;
        }
        .auth-logo-mark {
            width:38px;
            height:38px;
            border-radius:12px;
            display:grid;
            place-items:center;
            background:linear-gradient(135deg,#3B82F6,#2563EB);
            color:white!important;
            font-weight:950;
            box-shadow:0 14px 30px rgba(37,99,235,.24);
        }
        .auth-nav-links {
            display:flex;
            gap:30px;
            align-items:center;
            color:#334155!important;
            font-size:14px;
            font-weight:750;
        }
        .auth-nav-links a { text-decoration:none!important; color:#334155!important; }
        .auth-nav-links a:hover { color:#2563EB!important; }
        .auth-nav-cta {
            display:inline-flex;
            align-items:center;
            justify-content:center;
            background:#2563EB;
            color:#FFFFFF!important;
            border-radius:12px;
            padding:11px 18px;
            font-weight:850;
            box-shadow:0 14px 28px rgba(37,99,235,.25);
        }
        .auth-hero-grid {
            display:grid;
            grid-template-columns:minmax(0, .92fr) minmax(560px, 1.08fr);
            gap:48px;
            align-items:center;
            background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 54%,#EFF6FF 100%);
            border:1px solid #E5E7EB;
            border-radius:28px;
            padding:58px;
            box-shadow:0 24px 70px rgba(15,23,42,.08);
            min-height:650px;
            overflow:hidden;
            position:relative;
        }
        .auth-hero-grid:before {
            content:"";
            position:absolute;
            inset:-25% -12% auto auto;
            width:620px;
            height:620px;
            border-radius:999px;
            background:radial-gradient(circle, rgba(37,99,235,.14), transparent 63%);
            pointer-events:none;
        }
        .auth-eyebrow {
            display:inline-flex;
            align-items:center;
            gap:8px;
            background:#EFF6FF;
            color:#2563EB!important;
            border:1px solid #BFDBFE;
            font-size:12px;
            font-weight:950;
            letter-spacing:.075em;
            text-transform:uppercase;
            border-radius:999px;
            padding:8px 13px;
            margin-bottom:22px;
        }
        .auth-title {
            color:#0F172A!important;
            font-size:clamp(52px,4.8vw,88px);
            line-height:.98;
            font-weight:950;
            letter-spacing:-.07em;
            max-width:760px;
            margin:0 0 24px 0;
        }
        .auth-title .blue { color:#2563EB!important; }
        .auth-subtitle {
            color:#475569!important;
            font-size:clamp(18px,1.3vw,22px);
            line-height:1.6;
            max-width:700px;
            margin:0 0 34px 0;
        }
        .auth-cta-row { display:flex; flex-wrap:wrap; align-items:center; gap:14px; margin:0 0 26px 0; }
        .auth-primary-cta, .auth-secondary-cta {
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:48px;
            border-radius:13px;
            padding:0 22px;
            font-weight:900;
            font-size:15px;
            text-decoration:none!important;
        }
        .auth-primary-cta { background:#2563EB; color:#FFFFFF!important; box-shadow:0 16px 34px rgba(37,99,235,.25); }
        .auth-secondary-cta { background:#FFFFFF; color:#0F172A!important; border:1px solid #CBD5E1; box-shadow:0 8px 18px rgba(15,23,42,.045); }
        .auth-proof-row { display:flex; flex-wrap:wrap; gap:22px; color:#475569!important; font-size:14px; font-weight:750; }
        .auth-proof-row span { display:inline-flex; align-items:center; gap:8px; }
        .auth-proof-dot { width:22px; height:22px; border-radius:7px; display:inline-grid; place-items:center; background:#EFF6FF; color:#2563EB!important; border:1px solid #BFDBFE; font-size:12px; }
        .product-window {
            position:relative;
            z-index:1;
            background:#FFFFFF;
            border:1px solid #E2E8F0;
            border-radius:24px;
            box-shadow:0 30px 80px rgba(15,23,42,.15);
            overflow:hidden;
            transform:translateX(8px);
        }
        .product-window-top {
            height:48px;
            display:flex;
            align-items:center;
            justify-content:space-between;
            padding:0 18px;
            border-bottom:1px solid #E5E7EB;
            background:#FFFFFF;
        }
        .product-brand { display:flex; align-items:center; gap:10px; font-weight:900; color:#0F172A!important; }
        .product-mini-logo { width:25px; height:25px; border-radius:8px; background:#2563EB; color:#fff!important; display:grid; place-items:center; font-size:12px; font-weight:950; }
        .product-app { display:grid; grid-template-columns:150px 1fr; min-height:470px; }
        .product-sidebar { background:#F8FAFC; border-right:1px solid #E5E7EB; padding:18px 12px; }
        .product-nav-item { display:flex; align-items:center; gap:8px; border-radius:10px; padding:10px 12px; color:#475569!important; font-size:13px; font-weight:800; margin-bottom:5px; }
        .product-nav-item.active { background:#EFF6FF; color:#2563EB!important; }
        .product-main { padding:24px; background:#FFFFFF; }
        .product-main-title { display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; }
        .product-main-title strong { color:#0F172A!important; font-size:22px; letter-spacing:-.035em; }
        .product-btn { background:#2563EB; color:#fff!important; padding:9px 12px; border-radius:10px; font-size:12px; font-weight:850; }
        .product-kpis { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px; }
        .product-kpi { border:1px solid #E5E7EB; border-radius:14px; padding:14px; background:#FFFFFF; box-shadow:0 8px 18px rgba(15,23,42,.035); }
        .product-kpi span { display:block; color:#64748B!important; font-size:11px; font-weight:850; text-transform:uppercase; letter-spacing:.04em; margin-bottom:8px; }
        .product-kpi strong { color:#0F172A!important; font-size:28px; }
        .product-panels { display:grid; grid-template-columns:1fr .86fr; gap:14px; margin-bottom:16px; }
        .product-panel { border:1px solid #E5E7EB; border-radius:16px; padding:16px; background:#FFFFFF; min-height:150px; }
        .line-chart { height:95px; position:relative; border-left:1px solid #E5E7EB; border-bottom:1px solid #E5E7EB; margin-top:20px; }
        .line-chart svg { width:100%; height:100%; overflow:visible; }
        .donut-wrap { display:flex; gap:18px; align-items:center; justify-content:center; height:120px; }
        .donut { width:100px; height:100px; border-radius:50%; background:conic-gradient(#16A34A 0 48%, #F59E0B 48% 78%, #EF4444 78% 100%); display:grid; place-items:center; }
        .donut-inner { width:58px; height:58px; border-radius:50%; background:#FFFFFF; display:grid; place-items:center; color:#0F172A!important; font-weight:950; }
        .risk-legend { font-size:12px; color:#475569!important; line-height:1.9; font-weight:750; }
        .legend-red,.legend-amber,.legend-green { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:7px; }
        .legend-red{background:#EF4444}.legend-amber{background:#F59E0B}.legend-green{background:#16A34A}
        .product-table { width:100%; border:1px solid #E5E7EB; border-radius:14px; overflow:hidden; }
        .product-row { display:grid; grid-template-columns:1.3fr .8fr .8fr .8fr .6fr; border-bottom:1px solid #EEF2F7; }
        .product-row:last-child { border-bottom:0; }
        .product-cell { padding:10px 12px; color:#334155!important; font-size:12px; font-weight:700; }
        .product-head .product-cell { background:#F8FAFC; color:#64748B!important; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
        .trusted-band { text-align:center; padding:38px 0 22px 0; }
        .trusted-label { color:#64748B!important; font-weight:750; margin-bottom:18px; }
        .trusted-logos { display:grid; grid-template-columns:repeat(6,1fr); gap:18px; align-items:center; color:#0F172A!important; font-size:26px; font-weight:950; opacity:.88; }
        .trusted-logos span:nth-child(2), .trusted-logos span:nth-child(3), .trusted-logos span:nth-child(4) { color:#2563EB!important; }
        .feature-section { padding:28px 0 10px 0; }
        .section-title { text-align:center; color:#0F172A!important; font-size:34px; font-weight:950; letter-spacing:-.045em; margin:0 0 26px 0; }
        .feature-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:18px; }
        .feature-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:18px; padding:22px; box-shadow:0 12px 30px rgba(15,23,42,.055); }
        .feature-icon { width:36px; height:36px; border-radius:12px; display:grid; place-items:center; background:#EFF6FF; color:#2563EB!important; font-weight:950; margin-bottom:16px; }
        .feature-card strong { display:block; color:#0F172A!important; font-size:17px; margin-bottom:8px; }
        .feature-card span { display:block; color:#64748B!important; font-size:14px; line-height:1.55; }
        .bottom-cta { margin:34px 0 0 0; background:linear-gradient(135deg,#0F172A,#1E3A8A); border-radius:20px; padding:26px 30px; display:flex; align-items:center; justify-content:space-between; gap:20px; box-shadow:0 22px 50px rgba(15,23,42,.18); }
        .bottom-cta strong { color:#FFFFFF!important; font-size:24px; display:block; margin-bottom:6px; }
        .bottom-cta span { color:#CBD5E1!important; font-size:14px; }
        .auth-form-shell { margin:30px auto 16px auto; max-width:900px; background:#FFFFFF; border:1px solid #E5E7EB; border-radius:24px; padding:28px; box-shadow:0 18px 45px rgba(15,23,42,.07); }
        .auth-form-title { color:#0F172A!important; font-size:26px; font-weight:950; letter-spacing:-.04em; margin:0 0 6px 0; }
        .auth-form-subtitle { color:#64748B!important; font-size:14px; margin:0 0 18px 0; }
        div[data-testid="stTextInput"] input {
            background:#FFFFFF!important;
            color:#0F172A!important;
            border:1px solid #CBD5E1!important;
            border-radius:11px!important;
            min-height:44px!important;
        }
        div[data-testid="stTextInput"] input:focus {
            border-color:#2563EB!important;
            box-shadow:0 0 0 3px rgba(37,99,235,.12)!important;
        }
        div.stButton > button {
            background:#2563EB!important;
            color:#FFFFFF!important;
            border:1px solid #2563EB!important;
            border-radius:11px!important;
            min-height:46px!important;
            font-weight:850!important;
            width:auto!important;
            min-width:150px!important;
            padding-left:22px!important;
            padding-right:22px!important;
            box-shadow:0 14px 28px rgba(37,99,235,.22)!important;
        }
        div.stButton > button:hover { background:#1D4ED8!important; border-color:#1D4ED8!important; color:#FFFFFF!important; }
        div.stButton > button * { color:#FFFFFF!important; }
        div[data-testid="stRadio"] label { color:#0F172A!important; font-weight:750!important; }
        @media(max-width:1200px){
            .auth-hero-grid{grid-template-columns:1fr; padding:38px;}
            .product-window{transform:none;}
            .trusted-logos{grid-template-columns:repeat(3,1fr);}
            .feature-grid{grid-template-columns:repeat(2,1fr);}
        }
        @media(max-width:760px){
            .block-container{width:100%!important; padding-left:1rem!important; padding-right:1rem!important;}
            .auth-nav{align-items:flex-start; flex-direction:column;}
            .auth-nav-links{flex-wrap:wrap; gap:16px;}
            .auth-hero-grid{padding:28px; min-height:auto; border-radius:22px;}
            .product-app{grid-template-columns:1fr;}
            .product-sidebar{display:none;}
            .product-kpis,.product-panels,.feature-grid{grid-template-columns:1fr;}
            .trusted-logos{grid-template-columns:repeat(2,1fr); font-size:20px;}
            .bottom-cta{flex-direction:column; align-items:flex-start;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="brc-public-page">
          <div class="auth-nav">
            <div class="auth-logo"><div class="auth-logo-mark">B</div><span>BOM Risk Checker</span></div>
            <div class="auth-nav-links">
              <a href="#features">Features</a>
              <a href="#solutions">Solutions</a>
              <a href="#pricing">Pricing</a>
              <a href="#resources">Resources</a>
              <a href="#workspace-access" class="auth-secondary-cta" style="min-height:40px;padding:0 16px;">Sign In</a>
              <a href="#workspace-access" class="auth-nav-cta">Get Started</a>
            </div>
          </div>
          <div class="auth-hero-grid">
            <div>
              <div class="auth-eyebrow">AI-powered supply chain intelligence</div>
              <h1 class="auth-title">Reduce BOM Risk.<br><span class="blue">Find Better Alternatives.</span></h1>
              <p class="auth-subtitle">Analyze component lifecycle, supplier risk, and market availability in seconds. Make smarter sourcing decisions and keep your products moving.</p>
              <div class="auth-cta-row">
                <a class="auth-primary-cta" href="#workspace-access">Start Free Trial</a>
                <a class="auth-secondary-cta" href="#features">See How It Works</a>
              </div>
              <div class="auth-proof-row">
                <span><span class="auth-proof-dot">✓</span>No credit card required</span>
                <span><span class="auth-proof-dot">✓</span>AI-powered risk scoring</span>
                <span><span class="auth-proof-dot">✓</span>CSV & Excel export</span>
              </div>
            </div>
            <div class="product-window">
              <div class="product-window-top">
                <div class="product-brand"><span class="product-mini-logo">B</span><span>BOM Risk Checker</span></div>
                <div style="color:#94A3B8;font-weight:850;font-size:12px;">Live workspace</div>
              </div>
              <div class="product-app">
                <div class="product-sidebar">
                  <div class="product-nav-item active">⌂ Dashboard</div>
                  <div class="product-nav-item">▦ BOM Analyzer</div>
                  <div class="product-nav-item">◌ Analyses</div>
                  <div class="product-nav-item">✦ Alternative Finder</div>
                  <div class="product-nav-item">▣ Reports</div>
                  <div class="product-nav-item">⚙ Settings</div>
                </div>
                <div class="product-main">
                  <div class="product-main-title"><strong>Dashboard</strong><span class="product-btn">+ New Analysis</span></div>
                  <div class="product-kpis">
                    <div class="product-kpi"><span>Overall BOM Risk</span><strong>72</strong></div>
                    <div class="product-kpi"><span>High Risk</span><strong>18</strong></div>
                    <div class="product-kpi"><span>Alternatives</span><strong>78</strong></div>
                  </div>
                  <div class="product-panels">
                    <div class="product-panel">
                      <strong style="color:#0F172A!important;">BOM Risk Trend</strong>
                      <div class="line-chart"><svg viewBox="0 0 420 100"><polyline points="0,30 60,35 120,62 180,50 240,76 300,80 360,54 420,38" fill="none" stroke="#2563EB" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><g fill="#2563EB"><circle cx="0" cy="30" r="4"/><circle cx="60" cy="35" r="4"/><circle cx="120" cy="62" r="4"/><circle cx="180" cy="50" r="4"/><circle cx="240" cy="76" r="4"/><circle cx="300" cy="80" r="4"/><circle cx="360" cy="54" r="4"/><circle cx="420" cy="38" r="4"/></g></svg></div>
                    </div>
                    <div class="product-panel">
                      <strong style="color:#0F172A!important;">Risk Distribution</strong>
                      <div class="donut-wrap"><div class="donut"><div class="donut-inner">100</div></div><div class="risk-legend"><div><span class="legend-red"></span>High Risk</div><div><span class="legend-amber"></span>Medium Risk</div><div><span class="legend-green"></span>Low Risk</div></div></div>
                    </div>
                  </div>
                  <div class="product-table">
                    <div class="product-row product-head"><div class="product-cell">File Name</div><div class="product-cell">Date</div><div class="product-cell">Components</div><div class="product-cell">Risk</div><div class="product-cell">Action</div></div>
                    <div class="product-row"><div class="product-cell">Industrial_Controller_BOM.xlsx</div><div class="product-cell">May 12</div><div class="product-cell">100</div><div class="product-cell">Medium</div><div class="product-cell">View</div></div>
                    <div class="product-row"><div class="product-cell">Power_Supply_RevB.csv</div><div class="product-cell">May 11</div><div class="product-cell">78</div><div class="product-cell">Low</div><div class="product-cell">View</div></div>
                    <div class="product-row"><div class="product-cell">IoT_Device_BOM.xlsx</div><div class="product-cell">May 10</div><div class="product-cell">80</div><div class="product-cell">High</div><div class="product-cell">View</div></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div id="workspace-access" class="auth-form-shell">
          <div class="auth-form-title">Access your workspace</div>
          <div class="auth-form-subtitle">Use Sign In for an existing account, or Create Account to start a new workspace.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    form_left, form_right = st.columns([0.42, 0.58], gap="large")
    with form_left:
        auth_mode = st.radio(
            "Choose an option",
            ["Login", "Create Account"],
            horizontal=True,
        )
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if auth_mode == "Create Account":
            submit = st.button("Create Account")
        else:
            submit = st.button("Login")
    with form_right:
        st.markdown(
            """
            <div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:18px;padding:22px;box-shadow:0 12px 30px rgba(15,23,42,.05);margin-top:30px;">
              <div style="font-weight:950;color:#0F172A;font-size:18px;margin-bottom:8px;">Secure engineering workspace</div>
              <div style="color:#64748B;line-height:1.6;font-size:14px;">Your BOMs, saved analyses, reports, alternative recommendations, and subscription usage stay connected to your account.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if submit:
        if not email or not password:
            st.warning("Please enter your email and password.")
            return
        if auth_mode == "Create Account":
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

    st.markdown(
        """
        <div class="brc-public-page" id="features">
          <div class="trusted-band">
            <div class="trusted-label">Trusted by engineering and supply chain teams</div>
            <div class="trusted-logos"><span>Honeywell</span><span>PHILIPS</span><span>flex</span><span>SIEMENS</span><span>BOSCH</span><span>molex</span></div>
          </div>
          <div class="feature-section">
            <h2 class="section-title">Everything you need to manage BOM risk</h2>
            <div class="feature-grid">
              <div class="feature-card"><div class="feature-icon">▣</div><strong>Lifecycle & Obsolescence Analysis</strong><span>Identify EOL, NRND, and at-risk components before they impact your product.</span></div>
              <div class="feature-card"><div class="feature-icon">◌</div><strong>Supplier & Market Intelligence</strong><span>Access supplier risk, lead times, and availability data in one place.</span></div>
              <div class="feature-card"><div class="feature-icon">↗</div><strong>AI-Powered Risk Scoring</strong><span>Score each component using lifecycle, sourcing, inventory, and supplier factors.</span></div>
              <div class="feature-card"><div class="feature-icon">↔</div><strong>Alternative Component Finder</strong><span>Find fit, form, and function alternatives ranked by risk, availability, and cost.</span></div>
            </div>
          </div>
          <div class="bottom-cta"><div><strong>Ready to reduce your BOM risk?</strong><span>Join engineering teams building more resilient products.</span></div><a class="auth-primary-cta" href="#workspace-access">Start Free Trial</a></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
