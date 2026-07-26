import streamlit as st
import plotly.graph_objects as go

CADIVOR_PRIMARY = "#2563EB"
CADIVOR_TEXT = "#0F172A"
CADIVOR_MUTED = "#64748B"
CADIVOR_BORDER = "#E5E7EB"
CADIVOR_BG = "#F6F8FB"
CADIVOR_SURFACE = "#FFFFFF"


def inject_premium_css():
    """Inject the Cadivor Design System v1.0 CSS.

    Supports both the original `src/css/premium.css` path and the current
    `src/assets/css/premium.css` project path so the styling layer loads
    reliably regardless of which milestone ZIP the project came from.
    """
    css = ""
    for css_path in ("src/css/premium.css", "src/assets/css/premium.css"):
        try:
            with open(css_path, "r", encoding="utf-8") as css_file:
                css = css_file.read()
            if css.strip():
                break
        except Exception:
            continue
    if css.strip():
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _safe_text(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _profile_from_user(current_user=None):
    current_user = current_user if isinstance(current_user, dict) else {}
    email = _safe_text(current_user.get("email"))
    full_name = _safe_text(current_user.get("full_name"), _safe_text(current_user.get("name")))
    first_name = _safe_text(current_user.get("first_name"))
    last_name = _safe_text(current_user.get("last_name"))
    if not full_name and (first_name or last_name):
        full_name = f"{first_name} {last_name}".strip()
    if not full_name and email:
        full_name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
    company = _safe_text(current_user.get("company_name"), _safe_text(current_user.get("company")))
    role_title = _safe_text(current_user.get("role_title"), _safe_text(current_user.get("job_title")))
    avatar_url = _safe_text(current_user.get("profile_image_url"), _safe_text(current_user.get("avatar_url")))
    plan = _safe_text(current_user.get("plan"), "Starter")
    initials_source = full_name or email or "Cadivor"
    initials = "".join([part[0] for part in initials_source.replace("@", " ").split()[:2]]).upper()[:2] or "C"
    return {
        "email": email,
        "full_name": full_name or "Cadivor user",
        "company": company,
        "role_title": role_title,
        "avatar_url": avatar_url,
        "plan": plan,
        "initials": initials,
    }


def render_topbar(current_user=None, app_mode="Dashboard"):
    """Render the Cadivor application top bar with profile menu foundation."""
    profile = _profile_from_user(current_user)
    secondary = profile["company"] or profile["role_title"] or profile["plan"]
    avatar = f'<img src="{profile["avatar_url"]}" alt="Profile photo" />' if profile.get("avatar_url") else profile["initials"]

    st.markdown(
        f"""
        <style>
        .cadivor-user-wrap {{ position:relative; justify-self:end; }}
        .cadivor-user-wrap:hover .cadivor-user-menu {{ opacity:1; transform:translateY(0); pointer-events:auto; }}
        .cadivor-user {{ cursor:pointer; }}
        .cadivor-user-menu {{
            position:absolute; right:0; top:100%; min-width:248px;
            background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px;
            box-shadow:0 24px 52px rgba(15,23,42,.14); padding:8px;
            opacity:0; transform:translateY(-4px); pointer-events:none; transition:opacity .14s ease, transform .14s ease; z-index:1000006;
        }}
        .cadivor-user-menu a {{
            display:flex; align-items:center; justify-content:space-between; gap:12px;
            padding:10px 12px; border-radius:11px; text-decoration:none!important;
            color:#0F172A!important; font-size:13px; font-weight:800;
        }}
        .cadivor-user-menu a:hover {{ background:#F8FAFC; color:#2563EB!important; }}
        .cadivor-user-menu .danger:hover {{ background:#FEF2F2; color:#DC2626!important; }}
        .cadivor-user-menu-divider {{ height:1px; background:#EEF2F7; margin:6px 4px; }}
        .cadivor-user-menu-meta {{ padding:10px 12px 8px; }}
        .cadivor-user-menu-meta strong {{ display:block; color:#0F172A!important; font-size:13px; }}
        .cadivor-user-menu-meta span {{ display:block; color:#64748B!important; font-size:12px; margin-top:2px; }}
        </style>
        <div id="cadivor-topbar-root" class="cadivor-topbar">
            <div class="cadivor-brand">
                <div class="cadivor-logo-mark">C</div>
                <div>
                    <div class="cadivor-logo-text">Cadivor</div>
                    <div class="cadivor-logo-subtitle">Engineering Intelligence</div>
                </div>
            </div>
            <div class="cadivor-topbar-center">
                <div class="cadivor-current-page">{app_mode}</div>
                <a class="cadivor-search-pill" href="?page=Dashboard&focus=search" target="_self" style="text-decoration:none!important;">Search BOMs, parts, suppliers…</a>
                <a class="cadivor-top-icon" href="?page=Notifications" target="_self" title="Notifications" style="text-decoration:none!important;">●</a>
                <a class="cadivor-top-icon" href="?page=Help" target="_self" title="Help" style="text-decoration:none!important;">?</a>
            </div>
            <div class="cadivor-user-wrap">
                <div class="cadivor-user">
                    <div class="cadivor-user-meta">
                        <div class="cadivor-user-label">Workspace</div>
                        <div class="cadivor-user-name">{profile["full_name"]}</div>
                        <div class="cadivor-user-company">{secondary}</div>
                    </div>
                    <div class="cadivor-avatar">{avatar}</div>
                </div>
                <div class="cadivor-user-menu">
                    <div class="cadivor-user-menu-meta"><strong>{profile["full_name"]}</strong><span>{profile["email"]}</span></div>
                    <div class="cadivor-user-menu-divider"></div>
                    <a href="?page=Settings" target="_self">My Profile <span>→</span></a>
                    <a href="?page=Workspace" target="_self">Workspace <span>→</span></a>
                    <a href="?page=Pricing" target="_self">Billing <span>→</span></a>
                    <a href="?page=Notifications" target="_self">Notifications <span>→</span></a>
                    <a href="?page=Help" target="_self">Help <span>→</span></a>
                    <div class="cadivor-user-menu-divider"></div>
                    <a class="danger" href="?action=logout" target="_self">Log out <span>↩</span></a>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title, subtitle="", action_label=None):
    st.markdown(
        f"""
        <div class="cadivor-page-header">
            <div>
                <h1>{title}</h1>
                <p>{subtitle}</p>
            </div>
            {f'<div class="cadivor-page-action">{action_label}</div>' if action_label else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(title, value, status="", kind="info"):
    kind_class = f"cadivor-badge-{kind}" if kind else "cadivor-badge-info"
    st.markdown(
        f"""
        <div class="cadivor-metric-card">
            <div class="cadivor-metric-title">{title}</div>
            <div class="cadivor-metric-value">{value}</div>
            {f'<div class="cadivor-badge {kind_class}">{status}</div>' if status else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def light_plotly_layout(fig, height=380):
    """Apply Cadivor's light chart style to a Plotly figure."""
    fig.update_layout(
        height=height,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color="#0F172A", family="Inter, Arial, sans-serif"),
        margin=dict(l=28, r=20, t=30, b=28),
        xaxis=dict(
            showgrid=True,
            gridcolor="#E5E7EB",
            zeroline=False,
            linecolor="#CBD5E1",
            tickfont=dict(color="#64748B"),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#E5E7EB",
            zeroline=False,
            linecolor="#CBD5E1",
            tickfont=dict(color="#64748B"),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    return fig


def empty_state(title, body, action_label=None, action_href=None, icon="◇"):
    """Reusable premium empty state."""
    action = f'<a class="cv-empty-action" href="{action_href}" target="_self">{action_label}</a>' if action_label and action_href else ""
    st.markdown(
        f"""
        <div class="cv-empty-state">
            <div class="cv-empty-icon">{icon}</div>
            <div class="cv-empty-title">{title}</div>
            <div class="cv-empty-body">{body}</div>
            {action}
        </div>
        <style>
        .cv-empty-state {{ background:#FFFFFF; border:1px solid #E5E7EB; border-radius:18px; padding:34px 28px; text-align:center; box-shadow:0 14px 34px rgba(15,23,42,.055); }}
        .cv-empty-icon {{ width:46px; height:46px; border-radius:14px; margin:0 auto 14px; display:flex; align-items:center; justify-content:center; background:#EFF6FF; color:#2563EB!important; font-weight:950; }}
        .cv-empty-title {{ color:#0F172A!important; font-size:18px; font-weight:950; margin-bottom:8px; }}
        .cv-empty-body {{ color:#64748B!important; font-size:14px; line-height:1.6; max-width:520px; margin:0 auto 18px; }}
        .cv-empty-action {{ display:inline-flex; align-items:center; justify-content:center; min-height:40px; padding:0 18px; border-radius:11px; background:#2563EB; color:#FFFFFF!important; font-weight:850; text-decoration:none!important; box-shadow:0 12px 24px rgba(37,99,235,.18); }}
        .cv-empty-action:hover {{ background:#1D4ED8; color:#FFFFFF!important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def action_card(title, body, href, icon="+", kind="primary"):
    """Clickable action card for dashboard/workspace pages."""
    st.markdown(
        f"""
        <a class="cv-action-card cv-action-card-link" href="{href}" target="_self">
          <div class="cv-action-icon">{icon}</div>
          <div class="cv-action-title">{title}</div>
          <div class="cv-action-copy">{body}</div>
        </a>
        <style>
        .cv-action-card-link {{ display:block; text-decoration:none!important; color:inherit!important; }}
        .cv-action-card-link:hover {{ transform:translateY(-3px); box-shadow:0 22px 46px rgba(15,23,42,.09)!important; border-color:#BFDBFE!important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )



def render_navigation_loading_overlay() -> None:
    """Compatibility no-op.

    Sprint 54.1 removes the full-screen HTML navigation overlay because it can
    remain visible across Streamlit reruns. Native page rendering now provides
    the transition without blocking the workspace.
    """
    st.session_state.pop("cadivor_navigation_loading", None)
    return


def launch_error(title: str, body: str, recovery: str = "Try again or return to the Dashboard.") -> None:
    """Render an actionable, customer-friendly error state."""
    st.markdown(
        f"""
        <div class="cv-launch-error">
          <div class="cv-launch-error-icon">!</div>
          <div><strong>{title}</strong><p>{body}</p><small>{recovery}</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------------------------------------------------------
# Cadivor v3.2 UX completion helpers
# -----------------------------------------------------------------------------
def inject_v32_ux_css():
    """Final Milestone 2 UX layer: design tokens, tables, animations, empty states."""
    st.markdown(
        """
        <style>
        :root {
            --cv-color-bg: #F6F8FB;
            --cv-color-surface: #FFFFFF;
            --cv-color-surface-soft: #F8FAFC;
            --cv-color-text: #0F172A;
            --cv-color-text-2: #334155;
            --cv-color-muted: #64748B;
            --cv-color-border: #E5E7EB;
            --cv-color-primary: #2563EB;
            --cv-color-primary-dark: #1D4ED8;
            --cv-color-success: #16A34A;
            --cv-color-warning: #F59E0B;
            --cv-color-danger: #DC2626;
            --cv-radius-sm: 10px;
            --cv-radius-md: 14px;
            --cv-radius-lg: 18px;
            --cv-radius-xl: 24px;
            --cv-shadow-sm: 0 8px 22px rgba(15,23,42,.045);
            --cv-shadow-md: 0 16px 38px rgba(15,23,42,.065);
            --cv-shadow-lg: 0 26px 70px rgba(15,23,42,.10);
            --cv-space-1: 4px;
            --cv-space-2: 8px;
            --cv-space-3: 12px;
            --cv-space-4: 16px;
            --cv-space-5: 24px;
            --cv-space-6: 32px;
            --cv-space-7: 40px;
        }
        .cv-fade-in { animation: cvFadeIn .22s ease both; }
        @keyframes cvFadeIn { from { opacity:0; transform:translateY(5px); } to { opacity:1; transform:translateY(0); } }
        .cv-panel, .cv-metric, .cv-action-card, .cadivor-metric-card, .card, .kpi-card {
            transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
        }
        .cv-panel:hover, .cv-metric:hover, .cv-action-card:hover {
            transform: translateY(-2px);
            box-shadow: var(--cv-shadow-md)!important;
            border-color: #CBD5E1!important;
        }
        .cv-command-card {
            background: linear-gradient(135deg, #FFFFFF 0%, #F8FBFF 100%);
            border: 1px solid var(--cv-color-border);
            border-radius: var(--cv-radius-xl);
            box-shadow: var(--cv-shadow-md);
            padding: 22px;
            margin: 14px 0 22px;
        }
        .cv-command-header { display:flex; justify-content:space-between; gap:18px; align-items:flex-start; margin-bottom:16px; }
        .cv-command-title { color:var(--cv-color-text)!important; font-size:20px; font-weight:950; letter-spacing:-.03em; margin-bottom:4px; }
        .cv-command-copy { color:var(--cv-color-muted)!important; font-size:13px; font-weight:700; line-height:1.55; }
        .cv-kbd-inline { border:1px solid #CBD5E1; background:#FFFFFF; color:#64748B!important; border-radius:7px; padding:2px 8px; font-size:11px; font-weight:950; }
        .cv-result-card {
            display:grid; grid-template-columns: 1fr auto; gap:16px; align-items:center;
            border:1px solid #E5E7EB; border-radius:15px; background:#FFFFFF; padding:14px 16px; margin:9px 0;
            box-shadow:0 8px 18px rgba(15,23,42,.035);
        }
        .cv-result-title { color:#0F172A!important; font-size:14px; font-weight:950; margin-bottom:3px; }
        .cv-result-meta { color:#64748B!important; font-size:12px; font-weight:750; }
        .cv-status-pill { display:inline-flex; align-items:center; min-height:26px; padding:0 9px; border-radius:999px; font-size:11px; font-weight:900; border:1px solid #BFDBFE; color:#2563EB!important; background:#EFF6FF; }
        .cv-status-pill.success { color:#047857!important; background:#ECFDF5; border-color:#A7F3D0; }
        .cv-status-pill.warning { color:#B45309!important; background:#FFFBEB; border-color:#FDE68A; }
        .cv-status-pill.danger { color:#B91C1C!important; background:#FEF2F2; border-color:#FECACA; }
        .cv-status-pill.muted { color:#64748B!important; background:#F8FAFC; border-color:#E2E8F0; }
        .cv-field-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 16px; }
        .cv-field-grid.three { grid-template-columns:repeat(3,minmax(0,1fr)); }
        .cv-section-rule { height:1px; background:#E5E7EB; margin:24px 0; }
        .cv-table-caption { display:flex; align-items:center; justify-content:space-between; gap:16px; margin:8px 0 12px; }
        .cv-table-caption-title { color:#0F172A!important; font-size:18px; font-weight:950; }
        .cv-table-caption-note { color:#64748B!important; font-size:12px; font-weight:800; }
        [data-testid="stDataFrame"] { border-radius:14px!important; overflow:hidden!important; border:1px solid #E5E7EB!important; box-shadow:var(--cv-shadow-sm)!important; }
        [data-testid="stDataFrame"] [role="columnheader"] { background:#F8FAFC!important; color:#475569!important; font-size:12px!important; font-weight:900!important; border-bottom:1px solid #E5E7EB!important; }
        [data-testid="stDataFrame"] [role="gridcell"] { background:#FFFFFF!important; color:#0F172A!important; border-bottom:1px solid #EEF2F7!important; }
        [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background:#F8FAFC!important; }
        div.stTextInput input, div.stTextArea textarea, div[data-baseweb="select"] > div {
            border-radius:12px!important; border:1px solid #CBD5E1!important; background:#FFFFFF!important; color:#0F172A!important;
        }
        div.stTextInput input:focus, div.stTextArea textarea:focus {
            border-color:#2563EB!important; box-shadow:0 0 0 3px rgba(37,99,235,.12)!important; outline:none!important;
        }
        div.stButton > button, div.stDownloadButton > button { transition:transform .15s ease, box-shadow .15s ease, background .15s ease; }
        div.stButton > button:hover, div.stDownloadButton > button:hover { transform:translateY(-1px); }
        @media(max-width:1100px){ .cv-field-grid, .cv-field-grid.three { grid-template-columns:1fr; } .cv-command-header{display:block;} }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_pill(label, status="info"):
    status = status if status in {"success", "warning", "danger", "muted"} else "info"
    return f'<span class="cv-status-pill {status}">{label}</span>'


# -----------------------------------------------------------------------------
# Cadivor Milestone 4.2 dashboard presentation helpers
# -----------------------------------------------------------------------------
def dashboard_insight_card(title, body, status="Action", kind="info", icon="•"):
    """Render a compact premium insight card for the dashboard command center."""
    kind = kind if kind in {"success", "warning", "danger", "muted", "info"} else "info"
    st.markdown(
        f"""
        <div class="cv-insight-card cv-insight-{kind}">
            <div class="cv-insight-icon">{icon}</div>
            <div class="cv-insight-content">
                <div class="cv-insight-title">{title}</div>
                <div class="cv-insight-body">{body}</div>
            </div>
            <span class="cv-status-pill {kind if kind != 'info' else ''}">{status}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def dashboard_command_center(greeting, user_name, subtitle, health_score, health_label, action_href="?page=BOM%20Analyzer"):
    """Render the premium dashboard hero used in Milestone 4.2."""
    st.markdown(
        f"""
        <div class="cv-command-hero cv-fade-in">
            <div class="cv-command-hero-copy">
                <div class="cv-eyebrow">Cadivor Command Center</div>
                <h1 class="cv-title">{greeting}, {user_name}.</h1>
                <p class="cv-subtitle">{subtitle}</p>
                <div class="cv-hero-actions">
                    <a class="cv-hero-primary" href="{action_href}" target="_self">Run new BOM analysis</a>
                    <a class="cv-hero-secondary" href="?page=Alternative%20Finder" target="_self">Find alternatives</a>
                </div>
            </div>
            <div class="cv-hero-score-card">
                <div class="cv-hero-score-label">Portfolio Health</div>
                <div class="cv-hero-score-value">{health_score}</div>
                <div class="cv-hero-score-status">{health_label}</div>
                <div class="cv-hero-score-track"><span style="width:{max(0, min(100, int(health_score or 0)))}%;"></span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
