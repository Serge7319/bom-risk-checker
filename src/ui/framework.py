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
    """Render the Cadivor application top bar."""
    profile = _profile_from_user(current_user)
    secondary = profile["company"] or profile["role_title"] or profile["plan"]
    avatar = f'<img src="{profile["avatar_url"]}" alt="Profile photo" />' if profile.get("avatar_url") else profile["initials"]

    st.markdown(
        f"""
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
                <div class="cadivor-search-pill">Search BOMs, parts, suppliers…</div>
                <div class="cadivor-top-icon" title="Notifications">●</div>
                <div class="cadivor-top-icon" title="Help">?</div>
            </div>
            <div class="cadivor-user">
                <div class="cadivor-user-meta">
                    <div class="cadivor-user-label">Workspace</div>
                    <div class="cadivor-user-name">{profile["full_name"]}</div>
                    <div class="cadivor-user-company">{secondary}</div>
                </div>
                <div class="cadivor-avatar">{avatar}</div>
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
