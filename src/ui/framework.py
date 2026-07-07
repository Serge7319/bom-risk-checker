import streamlit as st
import plotly.graph_objects as go

CADIVOR_PRIMARY = "#2563EB"
CADIVOR_TEXT = "#0F172A"
CADIVOR_MUTED = "#64748B"
CADIVOR_BORDER = "#E5E7EB"
CADIVOR_BG = "#F6F8FB"
CADIVOR_SURFACE = "#FFFFFF"


def inject_premium_css():
    """Inject the Cadivor Design System v1.0 CSS."""
    try:
        with open("src/css/premium.css", "r", encoding="utf-8") as css_file:
            css = css_file.read()
    except Exception:
        css = ""
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
        <div class="cadivor-topbar">
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
