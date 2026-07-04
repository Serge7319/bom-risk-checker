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


def render_topbar(current_user=None, app_mode="Dashboard"):
    """Render the Cadivor application top bar."""
    email = ""
    if current_user:
        email = current_user.get("email", "") if isinstance(current_user, dict) else getattr(current_user, "email", "")
    initials = "C"
    if email:
        initials = email[0].upper()

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
            <div class="cadivor-topbar-center">{app_mode}</div>
            <div class="cadivor-user">
                <div class="cadivor-user-meta">
                    <div class="cadivor-user-label">Workspace</div>
                    <div class="cadivor-user-email">{email}</div>
                </div>
                <div class="cadivor-avatar">{initials}</div>
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


def light_plotly_layout(fig, height=340):
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
