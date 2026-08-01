"""Cadivor Sprint 53 — enterprise excellence across marketing and workspace presentation.

This module owns only the signed-out public marketing experience. It does not
modify authenticated workspace routing, analysis state, or scrolling behavior.
"""
from __future__ import annotations

from html import escape
from textwrap import dedent
import re

import streamlit as st
import streamlit.components.v1 as components


PRODUCT_LINKS = [
    ("product", "Product"),
    ("solutions", "Solutions"),
    ("pricing", "Pricing"),
    ("resources", "Resources"),
    ("company", "Company"),
]


def _html(markup: str) -> None:
    """Render marketing HTML without Markdown treating indented lines as code.

    Streamlit's Markdown parser can expose fragments of large multiline HTML
    blocks when an embedded element contains preformatted or indented content.
    Normalizing inter-tag whitespace keeps the markup in one HTML block while
    preserving visible copy and avoids source text leaking into the page.
    """
    normalized = dedent(markup).strip()
    normalized = re.sub(r"\n[ \t]+", " ", normalized)
    normalized = re.sub(r">\s+<", "><", normalized)
    st.markdown(normalized, unsafe_allow_html=True)





def _query_value(name: str, default: str = "") -> str:
    """Read a scalar Streamlit query value without leaking list semantics."""
    try:
        value = st.query_params.get(name, default)
    except Exception:
        return default
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default
    return str(value or default).strip()



def _install_internal_link_bridge() -> None:
    """Connect every internal marketing control to one Streamlit callback.

    Internal actions are semantic HTML buttons, never anchors layered over
    hidden controls. A single delegated click listener forwards each action to
    one hidden Streamlit callback button. Reinstalling the listener on every
    render prevents stale handlers after Streamlit replaces page fragments.
    """
    public_routes = ("home", "product", "solutions", "pricing", "resources", "company", "contact", "security", "privacy", "terms")
    with st.container(key="cv_public_link_bridge"):
        for route in public_routes:
            st.button(
                f"Open {route}",
                key=f"cv_bridge_public_{route}",
                on_click=_set_public_route,
                args=(route,),
            )
        for surface in ("login", "signup"):
            st.button(
                f"Open {surface}",
                key=f"cv_bridge_auth_{surface}",
                on_click=_open_auth_surface,
                args=(surface,),
            )

    components.html(
        """<script>
        (() => {
          const win = window.parent;
          const doc = win.document;

          if (win.__cadivorUnifiedMarketingClickHandler) {
            doc.removeEventListener('click', win.__cadivorUnifiedMarketingClickHandler, true);
          }

          const activate = (kind, value) => {
            const safe = String(value || '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
            if (!safe) return;
            const selector = kind === 'auth'
              ? `.st-key-cv_bridge_auth_${safe} button`
              : `.st-key-cv_bridge_public_${safe} button`;
            const target = doc.querySelector(selector);
            if (target && !target.disabled) target.click();
          };

          const handler = (event) => {
            const control = event.target && event.target.closest
              ? event.target.closest('[data-cv-public], [data-cv-auth]')
              : null;
            if (!control || control.disabled || control.getAttribute('aria-disabled') === 'true') return;
            event.preventDefault();
            event.stopPropagation();
            if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
            const auth = control.getAttribute('data-cv-auth');
            const route = control.getAttribute('data-cv-public');
            activate(auth ? 'auth' : 'public', auth || route);
          };

          win.__cadivorUnifiedMarketingClickHandler = handler;
          doc.addEventListener('click', handler, true);
        })();
        </script>""",
        height=0,
        width=0,
    )

def _icon(name: str) -> str:
    icons = {
        "bom": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/></svg>',
        "brain": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 4.5A3 3 0 0 0 5 7a3 3 0 0 0 .5 5.5A3.5 3.5 0 0 0 9 18h1V6a2 2 0 0 0-.5-1.5ZM14.5 4.5A3 3 0 0 1 19 7a3 3 0 0 1-.5 5.5A3.5 3.5 0 0 1 15 18h-1V6a2 2 0 0 1 .5-1.5Z"/><path d="M7 9h3M14 9h3M7.5 14H10M14 14h2.5"/></svg>',
        "chat": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="m15.5 7 .6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6Z"/></svg>',
        "compare": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7h12M16 3l4 4-4 4M16 17H4M8 13l-4 4 4 4"/></svg>',
        "monitor": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/><path d="M18.5 3.5 20 2M5.5 3.5 4 2"/></svg>',
        "report": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2h9l3 3v17H6z"/><path d="M14 2v4h4M9 17v-4M12 17V9M15 17v-6"/></svg>',
        "decision": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 3h6v4H9zM8 12l2 2 5-5M8 18h8"/></svg>',
        "portfolio": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3v18h18"/><path d="m7 16 4-5 3 2 5-7"/><circle cx="7" cy="16" r="1"/><circle cx="11" cy="11" r="1"/><circle cx="14" cy="13" r="1"/><circle cx="19" cy="6" r="1"/></svg>',
        "shield": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 20 6v6c0 5-3.4 8-8 10-4.6-2-8-5-8-10V6z"/><path d="m9 12 2 2 4-4"/></svg>',
        "audit": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h5M8 16h7"/><circle cx="17" cy="12" r="2"/></svg>',
        "users": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        "layers": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 9 5-9 5-9-5zM3 12l9 5 9-5M3 17l9 5 9-5"/></svg>',
    }
    return icons.get(name, icons["bom"])


def _marketing_css() -> None:
    st.markdown(
        """
        <style>
        :root{--mk-navy:#06142c;--mk-navy-2:#0b2248;--mk-blue:#2f6df6;--mk-blue-2:#1f56d8;--mk-sky:#78a9ff;--mk-ink:#0b1730;--mk-copy:#53657b;--mk-muted:#73839a;--mk-border:#dce5f0;--mk-soft:#f5f8fc;--mk-green:#18a865;--mk-amber:#e09a22;--mk-red:#e0474c;--mk-shadow:0 24px 70px rgba(10,28,59,.12)}
        html,body,.stApp,[data-testid="stAppViewContainer"]{background:#fff!important;color:var(--mk-ink)!important;font-family:Manrope,Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;scroll-behavior:smooth}
        [data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],section[data-testid="stSidebar"],[data-testid="collapsedControl"]{display:none!important}
        .block-container{width:100%!important;max-width:none!important;padding:0!important;margin:0!important}
        /* Emergency Restoration 61.0.5 — CSS-first public bootstrap. */
        html,body{background:#fff!important}
        .stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],section.main{background:#fff!important}
        [data-testid="stAppViewContainer"]::before{content:"";position:fixed;inset:0;z-index:-1;background:#fff}
        [data-testid="stSkeleton"],[data-testid="stSkeleton"]>div{background:#eef3f8!important;color:transparent!important}
        .cv-public-signout-toast{position:fixed;top:18px;left:50%;z-index:2147483645;transform:translateX(-50%);padding:10px 15px;border:1px solid #cfe0f5;border-radius:999px;background:#fff;color:#17345f;font-size:12px;font-weight:800;box-shadow:0 12px 34px rgba(15,23,42,.14);animation:cv-public-toast 3s ease both}
        @keyframes cv-public-toast{0%,80%{opacity:1;transform:translate(-50%,0)}100%{opacity:0;transform:translate(-50%,-8px)}}
        .mk-shell{width:100%;overflow:hidden}.mk-wrap{width:min(1240px,calc(100% - 48px));margin:0 auto}.mk-wide{width:min(1400px,calc(100% - 48px));margin:0 auto}
        .mk-shell h1 a,.mk-shell h2 a,.mk-shell h3 a,.mk-page-hero h1 a,.mk-footer h1 a,[data-testid="stMarkdownContainer"] h1 a,[data-testid="stMarkdownContainer"] h2 a,[data-testid="stMarkdownContainer"] h3 a{display:none!important}
        .mk-nav-wrap{position:relative;z-index:30;background:var(--mk-navy);border-bottom:1px solid rgba(255,255,255,.09)}.mk-nav{height:72px;display:flex;align-items:center;justify-content:space-between;gap:26px}.mk-brand{display:flex;align-items:center;gap:11px;color:#fff!important;text-decoration:none!important;font-size:23px;font-weight:800;letter-spacing:-.04em}.mk-logo{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:linear-gradient(145deg,#4b8cff,#1f5be5);box-shadow:0 10px 25px rgba(47,109,246,.35);font-weight:800;color:#fff!important}.mk-links{display:flex;align-items:center;gap:29px;font-size:13px;font-weight:700}.mk-links a{color:#d1daea!important;text-decoration:none!important}.mk-links a:not(:last-child)::after{content:"⌄";font-size:10px;margin-left:5px;color:#8393aa}.mk-links a:nth-child(3)::after{content:""}.mk-links a:hover,.mk-links a.active{color:#fff!important}.mk-nav-actions{display:flex;align-items:center;gap:10px}.mk-btn{display:inline-flex;align-items:center;justify-content:center;min-height:43px;padding:0 18px;border-radius:8px;text-decoration:none!important;font-size:13px;font-weight:800;white-space:nowrap;transition:.2s ease}.mk-btn:hover{transform:translateY(-1px)}.mk-btn-primary{background:linear-gradient(180deg,#3978fb,#2462eb);border:1px solid #4b82f7;color:#fff!important;box-shadow:0 10px 24px rgba(37,99,235,.28)}.mk-btn-light{background:#fff;border:1px solid #d9e2ee;color:var(--mk-ink)!important;box-shadow:0 8px 20px rgba(15,23,42,.08)}.mk-btn-ghost{background:transparent;border:1px solid rgba(255,255,255,.28);color:#fff!important}
        .mk-hero{background:radial-gradient(circle at 77% 18%,rgba(49,111,246,.25),transparent 31%),radial-gradient(circle at 8% 88%,rgba(31,86,216,.14),transparent 26%),linear-gradient(135deg,#06142c 0%,#081a37 55%,#102b5b 100%);color:#fff;padding:74px 0 78px;position:relative}.mk-hero:after{content:"";position:absolute;right:-180px;top:100px;width:430px;height:430px;border:1px solid rgba(105,158,255,.12);border-radius:50%}.mk-hero-grid{display:grid;grid-template-columns:minmax(500px,525px) minmax(0,1fr);gap:56px;align-items:center}.mk-eyebrow{display:inline-flex;align-items:center;gap:8px;padding:7px 13px;border-radius:999px;border:1px solid rgba(147,197,253,.28);background:rgba(37,99,235,.12);color:#c7dbff!important;font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin-bottom:24px}.mk-eyebrow-dot{width:7px;height:7px;border-radius:99px;background:#67a0ff;box-shadow:0 0 0 5px rgba(96,165,250,.12)}.mk-hero h1{margin:0 0 22px;color:#fff!important;font-size:clamp(43px,3vw,52px);line-height:1.06;letter-spacing:-.052em;font-weight:800}.mk-hero h1 .line{display:block;white-space:nowrap;color:#fff!important}.mk-hero h1 .mk-accent{color:#4f8cff!important}.mk-hero-copy{font-size:17px;line-height:1.7;color:#c6d1e2!important;max-width:590px;margin:0 0 29px}.mk-actions{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:23px}.mk-proof{display:flex;gap:19px;flex-wrap:wrap;color:#b8c5d8!important;font-size:12px;font-weight:650}.mk-proof b{color:#6ee7a7!important;margin-right:5px}
        .mk-product{background:#fff;border:1px solid rgba(255,255,255,.52);border-radius:14px;box-shadow:0 38px 100px rgba(0,0,0,.35);overflow:hidden;position:relative}.mk-product-top{height:43px;background:#f9fbfd;border-bottom:1px solid #e5eaf0;display:flex;align-items:center;justify-content:space-between;padding:0 14px}.mk-dots{display:flex;gap:6px}.mk-dots i{display:block;width:8px;height:8px;border-radius:99px;background:#cbd5e1}.mk-app{display:grid;grid-template-columns:132px 1fr;min-height:452px}.mk-side{background:#091831;padding:15px 9px}.mk-side-brand{color:#fff!important;font-size:11px;font-weight:800;margin:0 5px 16px}.mk-side-item{padding:8px 8px;border-radius:6px;color:#9aacC3!important;font-size:7px;font-weight:700;margin-bottom:3px}.mk-side-item.active{background:#245ce0;color:#fff!important}.mk-main{padding:15px;background:#f5f8fc}.mk-main-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:11px}.mk-main-head strong{color:#101b31!important;font-size:14px}.mk-mini-button{font-size:7px;background:#2868ef;color:#fff!important;padding:6px 9px;border-radius:5px;font-weight:800}.mk-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.mk-kpi{background:#fff;border:1px solid #e0e7f0;border-radius:7px;padding:9px}.mk-kpi-top{display:flex;align-items:center;justify-content:space-between}.mk-kpi-icon{width:21px;height:21px;border-radius:6px;background:#eef4ff;display:grid;place-items:center;color:#2f6df6}.mk-kpi-icon svg{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.mk-kpi span{display:block;color:#6b7c93!important;font-size:5.5px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.mk-kpi strong{display:block;color:#0f172a!important;font-size:16px;margin-top:4px}.mk-delta{font-size:5.5px!important;color:#15985a!important;margin-top:3px}.mk-decision-grid{display:grid;grid-template-columns:1.12fr .88fr;gap:8px;margin-top:8px}.mk-panel{background:#fff;border:1px solid #e0e7f0;border-radius:7px;padding:10px}.mk-panel-title{color:#0f172a!important;font-size:7.5px;font-weight:800;margin-bottom:7px}.mk-risk-list{display:grid;gap:5px}.mk-risk-item{display:grid;grid-template-columns:20px 1fr auto;gap:6px;align-items:center;font-size:6px;color:#475569!important}.mk-risk-badge{width:20px;height:20px;border-radius:5px;display:grid;place-items:center;font-weight:800;color:#fff!important}.mk-risk-badge.red{background:#d94b50}.mk-risk-badge.amber{background:#d98c20}.mk-risk-badge.blue{background:#3975eb}.mk-risk-name b{display:block;color:#18243b!important;font-size:6.5px}.mk-risk-name small{color:#77869b!important;font-size:5.5px}.mk-action-pill{padding:3px 5px;border-radius:4px;background:#edf3ff;color:#255dd5!important;font-size:5.5px;font-weight:800}.mk-ai-box{background:#0e2144;border-radius:7px;padding:10px;color:#dce8fb!important;min-height:128px}.mk-ai-box .mk-panel-title{color:#fff!important}.mk-ai-score{display:flex;gap:7px;margin-bottom:7px}.mk-ai-metric{flex:1;background:#162e59;padding:7px;border-radius:6px}.mk-ai-metric span{font-size:5.5px;color:#9fb3d0!important;text-transform:uppercase}.mk-ai-metric strong{display:block;font-size:13px;color:#fff!important;margin-top:3px}.mk-ai-copy{font-size:6px;line-height:1.55;color:#c9d6e9!important}.mk-table{margin-top:8px;background:#fff;border:1px solid #e0e7f0;border-radius:7px;overflow:hidden}.mk-row{display:grid;grid-template-columns:1.35fr .65fr .65fr .7fr;gap:5px;padding:6px 8px;border-bottom:1px solid #eef2f6;font-size:5.7px;color:#526178!important}.mk-row.head{background:#f8fafc;font-weight:800;color:#708097!important;text-transform:uppercase}.mk-row:last-child{border-bottom:0}.mk-risk{font-weight:800}.mk-risk.high{color:#d83f45!important}.mk-risk.medium{color:#d88a17!important}.mk-risk.low{color:#13975a!important}
        .mk-trust{background:#fff;border-bottom:1px solid #edf1f6;padding:22px 0}.mk-trust-inner{display:flex;align-items:center;justify-content:center;gap:40px;flex-wrap:wrap;color:#66788f!important}.mk-trust-label{color:#8a9ab0!important;font-size:10px;text-transform:uppercase;letter-spacing:.14em;font-weight:800}.mk-logo-text{font-size:16px;color:#566a83!important;font-weight:800}.mk-logo-text small{display:block;font-size:8px;letter-spacing:.11em;text-transform:uppercase;color:#9aa8ba!important;margin-top:2px;text-align:center}.mk-trust-divider{width:1px;height:24px;background:#e1e7ef}
        .mk-section{padding:82px 0}.mk-section.soft{background:var(--mk-soft)}.mk-section.dark{background:var(--mk-navy);color:#fff}.mk-heading{text-align:center;max-width:820px;margin:0 auto 42px}.mk-kicker{color:var(--mk-blue)!important;font-weight:800;font-size:10px;text-transform:uppercase;letter-spacing:.15em;margin-bottom:12px}.mk-heading h2{color:var(--mk-ink)!important;font-size:clamp(33px,3.5vw,47px);line-height:1.1;letter-spacing:-.045em;margin:0 0 16px;font-weight:800}.mk-heading p{color:var(--mk-copy)!important;font-size:16px;line-height:1.7;margin:0}.dark .mk-heading h2{color:#fff!important}.dark .mk-heading p{color:#b9c6d8!important}
        .mk-card-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.mk-card-grid.eight{grid-template-columns:repeat(4,1fr)}.mk-card{background:#fff;border:1px solid var(--mk-border);border-radius:14px;padding:24px;box-shadow:0 12px 34px rgba(15,23,42,.055);transition:.2s ease}.mk-card:hover{transform:translateY(-3px);box-shadow:0 20px 44px rgba(15,23,42,.09)}.mk-icon{width:44px;height:44px;border-radius:12px;background:linear-gradient(145deg,#eef4ff,#e7efff);color:#2f6df6!important;display:grid;place-items:center;margin-bottom:17px;box-shadow:inset 0 0 0 1px rgba(47,109,246,.08)}.mk-icon svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.mk-card h3{font-size:17px;color:var(--mk-ink)!important;margin:0 0 9px;font-weight:800;letter-spacing:-.025em}.mk-card p{font-size:13px;line-height:1.65;color:var(--mk-copy)!important;margin:0}.mk-card a,.mk-card button[data-cv-public],.mk-card button[data-cv-auth]{display:inline-block;margin-top:14px;color:#2a64df!important;text-decoration:none!important;font-size:12px;font-weight:800}
        .mk-feature-split{display:grid;grid-template-columns:1fr 1fr;gap:62px;align-items:center}.mk-feature-copy h2{font-size:41px;line-height:1.1;letter-spacing:-.045em;color:var(--mk-ink)!important;margin:0 0 17px;font-weight:800}.mk-feature-copy>p{color:var(--mk-copy)!important;font-size:16px;line-height:1.72}.mk-check-list{display:grid;gap:13px;margin-top:23px}.mk-check{display:flex;gap:11px;align-items:flex-start}.mk-check b{width:22px;height:22px;flex:none;border-radius:99px;background:#dcfce7;color:#15803d!important;display:grid;place-items:center;font-size:11px}.mk-check span{color:#334155!important;font-size:13px;line-height:1.55;font-weight:650}.mk-surface{background:#fff;border:1px solid var(--mk-border);border-radius:18px;padding:19px;box-shadow:var(--mk-shadow)}.mk-cockpit{background:#091a38;border-radius:12px;padding:17px;color:#fff}.mk-cockpit-title{font-size:12px;color:#fff!important;font-weight:800;margin-bottom:11px}.mk-cockpit-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.mk-cockpit-card{background:#122a53;border:1px solid rgba(255,255,255,.08);padding:10px;border-radius:7px}.mk-cockpit-card span{display:block;color:#9eb0c8!important;font-size:6px;text-transform:uppercase;font-weight:800}.mk-cockpit-card strong{display:block;color:#fff!important;font-size:16px;margin-top:4px}.mk-recommendation{margin-top:9px;background:#103366;border-left:3px solid #66a1ff;border-radius:7px;padding:11px;color:#dbeafe!important;font-size:9px;line-height:1.55}.mk-cockpit-actions{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px}.mk-cockpit-action{background:#10284f;border:1px solid rgba(255,255,255,.08);border-radius:7px;padding:9px}.mk-cockpit-action b{display:block;color:#fff!important;font-size:7px}.mk-cockpit-action span{display:block;color:#aebed4!important;font-size:6px;margin-top:4px}
        .mk-steps{display:grid;grid-template-columns:repeat(6,1fr);gap:14px}.mk-steps.four{grid-template-columns:repeat(4,minmax(0,1fr));max-width:980px;margin:0 auto}.mk-legal{max-width:920px;margin:0 auto}.mk-legal-meta{display:flex;gap:18px;flex-wrap:wrap;margin:0 0 28px;padding:16px 18px;background:#f8fafc;border:1px solid #dce6f2;border-radius:14px;color:#475569;font-size:13px}.mk-legal h2{font-size:28px;margin:34px 0 12px;color:var(--mk-ink)!important}.mk-legal h3{font-size:19px;margin:24px 0 8px;color:var(--mk-ink)!important}.mk-legal p,.mk-legal li{font-size:15px;line-height:1.75;color:var(--mk-copy)!important}.mk-legal ul{padding-left:22px}.mk-legal-note{margin-top:34px;padding:18px 20px;border-left:4px solid #2563eb;background:#eff6ff;border-radius:0 12px 12px 0}.mk-step{text-align:center;position:relative}.mk-step:after{content:"";position:absolute;top:20px;left:66%;width:70%;height:1px;background:#ccd8e8}.mk-step:last-child:after{display:none}.mk-step-num{width:40px;height:40px;border-radius:99px;background:#eaf2ff;color:#2563eb!important;display:grid;place-items:center;margin:0 auto 16px;font-weight:800;font-size:12px;position:relative;z-index:2}.mk-step h3{font-size:15px;color:var(--mk-ink)!important;margin:0 0 8px;font-weight:800}.mk-step p{font-size:11px;color:var(--mk-copy)!important;line-height:1.55;margin:0}
        .mk-reassure{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--mk-border);border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 12px 35px rgba(15,23,42,.05)}.mk-reassure-item{padding:20px 17px;display:flex;gap:11px;align-items:flex-start;border-right:1px solid #e7edf4}.mk-reassure-item:last-child{border-right:0}.mk-reassure-icon{width:34px;height:34px;border-radius:10px;background:#edf3ff;color:#2f6df6;display:grid;place-items:center;flex:none}.mk-reassure-icon svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.mk-reassure-item b{display:block;font-size:12px;color:#17243a!important}.mk-reassure-item span{display:block;font-size:10px;color:#6d7d92!important;line-height:1.45;margin-top:3px}
        .mk-evidence-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.mk-evidence{background:#fff;border:1px solid var(--mk-border);border-radius:14px;padding:24px}.mk-evidence .mk-icon{margin-bottom:14px}.mk-evidence h3{font-size:16px;margin:0 0 8px;color:var(--mk-ink)!important}.mk-evidence p{font-size:13px;line-height:1.65;color:var(--mk-copy)!important;margin:0}
        .mk-cta{background:linear-gradient(120deg,#09204a,#123d7b);border-radius:17px;padding:37px 42px;display:flex;align-items:center;justify-content:space-between;gap:25px;box-shadow:0 28px 65px rgba(7,22,47,.18)}.mk-cta h2{color:#fff!important;font-size:28px;letter-spacing:-.035em;margin:0 0 9px;font-weight:800}.mk-cta p{color:#c4d1e3!important;margin:0;font-size:14px}.mk-footer{background:#06142c;color:#fff;padding:57px 0 24px}.mk-footer-grid{display:grid;grid-template-columns:1.5fr repeat(4,1fr);gap:42px}.mk-footer-brand p{color:#91a4bf!important;font-size:12px;line-height:1.7;max-width:280px}.mk-footer-col{display:flex;flex-direction:column;gap:11px}.mk-footer-col strong{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#fff!important}.mk-footer-col a,.mk-footer-col button[data-cv-public],.mk-footer-col button[data-cv-auth]{color:#9fb0c5!important;text-decoration:none!important;font-size:12px}.mk-footer-bottom{display:flex;justify-content:space-between;gap:20px;border-top:1px solid rgba(255,255,255,.09);margin-top:38px;padding-top:19px;color:#8192aa!important;font-size:10px}
        .mk-page-hero{background:radial-gradient(circle at 75% 15%,rgba(37,99,235,.2),transparent 32%),linear-gradient(135deg,#06142c,#0d2854);padding:77px 0 70px;color:#fff}.mk-page-hero h1{font-size:clamp(44px,5vw,64px);line-height:1.04;letter-spacing:-.055em;max-width:800px;margin:0 0 20px;color:#fff!important;font-weight:800}.mk-page-hero p{max-width:760px;color:#c4d0e1!important;font-size:17px;line-height:1.7}.mk-page-hero .mk-actions{margin-top:27px}
        .mk-testimonials,.mk-industry-grid,.mk-resource-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.mk-quote,.mk-industry,.mk-resource{background:#fff;border:1px solid var(--mk-border);border-radius:14px;padding:24px;box-shadow:0 12px 34px rgba(15,23,42,.05)}.mk-quote p,.mk-industry p,.mk-resource p{color:var(--mk-copy)!important;font-size:13px;line-height:1.7}.mk-person{display:flex;gap:11px;align-items:center;margin-top:18px}.mk-avatar{width:36px;height:36px;border-radius:99px;background:#e1edff;color:#2563eb!important;display:grid;place-items:center;font-weight:800}.mk-person strong,.mk-person span{display:block;font-size:11px}.mk-person span{color:#8090a5!important;margin-top:3px}.mk-industry h3,.mk-resource h3{font-size:18px;color:var(--mk-ink)!important}.mk-industry ul,.mk-price-card ul{padding-left:18px;color:var(--mk-copy)!important;font-size:12px;line-height:1.8}.mk-industry a,.mk-resource a,.mk-industry button[data-cv-public],.mk-resource button[data-cv-public],.mk-industry button[data-cv-auth],.mk-resource button[data-cv-auth]{color:#2563eb!important;text-decoration:none!important;font-weight:800;font-size:12px}.mk-resource-type{font-size:10px;color:#2563eb!important;text-transform:uppercase;letter-spacing:.12em;font-weight:800}.mk-pricing{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.mk-price-card{border:1px solid var(--mk-border);border-radius:15px;padding:24px;background:#fff;position:relative}.mk-price-card.featured{border:2px solid #2f6df6;box-shadow:0 28px 70px rgba(47,109,246,.24);transform:translateY(-10px);background:linear-gradient(180deg,#fff,#f8fbff)}.mk-popular{position:absolute;right:14px;top:-12px;background:#2f6df6;color:#fff!important;border-radius:99px;padding:5px 10px;font-size:9px;font-weight:800}.mk-price-name{font-size:14px;font-weight:800}.mk-price{font-size:34px;font-weight:800;margin:9px 0;color:var(--mk-ink)!important}.mk-price small{font-size:12px;color:#67788e!important}.mk-price-card p{font-size:12px;color:var(--mk-copy)!important;min-height:54px}.mk-compare{width:100%;border-collapse:collapse;font-size:12px}.mk-compare th,.mk-compare td{padding:13px;border-bottom:1px solid #e5ebf2;text-align:center}.mk-compare th:first-child,.mk-compare td:first-child{text-align:left}.mk-yes{color:#15985a!important;font-weight:800}.mk-partial{color:#b87818!important}.mk-faq{display:grid;gap:12px}.mk-faq-item{background:#fff;border:1px solid var(--mk-border);border-radius:12px;padding:19px}.mk-faq-item strong{color:var(--mk-ink)!important}.mk-faq-item p{color:var(--mk-copy)!important;font-size:13px;margin:8px 0 0;line-height:1.65}

        .mk-hero-capabilities,.mk-page-outcomes{display:flex;flex-wrap:wrap;gap:8px;margin:-10px 0 24px}.mk-hero-capabilities span,.mk-page-outcomes span{display:inline-flex;align-items:center;padding:7px 10px;border-radius:999px;border:1px solid rgba(145,184,255,.22);background:rgba(40,91,184,.16);color:#d8e7ff!important;font-size:12px;font-weight:700}.mk-page-outcomes{margin:18px 0 0}.mk-story-section{background:linear-gradient(180deg,#fff,#f6f9fd)}.mk-story-grid{display:grid;grid-template-columns:1fr 74px 1fr;gap:22px;align-items:stretch}.mk-story-card{border:1px solid var(--mk-border);border-radius:18px;padding:30px;background:#fff;box-shadow:0 18px 54px rgba(15,23,42,.07)}.mk-story-card.after{border-color:#8fb2ff;background:linear-gradient(145deg,#f8fbff,#eef5ff)}.mk-story-label{display:inline-flex;padding:6px 10px;border-radius:999px;background:#eef3fb;color:#52657d!important;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}.mk-story-card.after .mk-story-label{background:#dfeaff;color:#2259d7!important}.mk-story-card h3{font-size:24px;line-height:1.25;margin:18px 0;color:var(--mk-ink)!important}.mk-story-card ul{margin:0;padding-left:21px;color:var(--mk-copy)!important;font-size:16px;line-height:1.85}.mk-story-arrow{display:grid;place-items:center;color:#2f6df6!important;font-size:36px;font-weight:800}.mk-story-metric{margin-top:22px;padding-top:18px;border-top:1px solid #e2e8f0;display:flex;gap:10px;align-items:baseline}.mk-story-metric strong{font-size:30px;color:#123b85!important}.mk-story-metric span{color:#64748b!important;font-size:14px}.mk-footer-grid{grid-template-columns:1.35fr repeat(5,1fr)}.mk-footer-col span{display:block;color:#8fa0b8!important;font-size:13px;margin-top:11px}.mk-price-card.featured .mk-price{font-size:40px}.mk-price-card.featured .mk-price-name{font-size:17px}
        @media(max-width:1100px){.mk-story-grid{grid-template-columns:1fr}.mk-story-arrow{transform:rotate(90deg);height:30px}.mk-footer-grid{grid-template-columns:repeat(3,1fr)}.mk-hero-grid{grid-template-columns:1fr}.mk-hero h1 .line{white-space:normal}.mk-card-grid.eight{grid-template-columns:repeat(2,1fr)}.mk-steps{grid-template-columns:repeat(3,1fr)}.mk-steps.four{grid-template-columns:repeat(2,minmax(0,1fr));max-width:720px}.mk-step:nth-child(3):after,.mk-step:last-child:after{display:none}.mk-reassure{grid-template-columns:repeat(2,1fr)}.mk-reassure-item{border-bottom:1px solid #e7edf4}.mk-pricing{grid-template-columns:repeat(2,1fr)}}
        @media(max-width:820px){.mk-footer-grid{grid-template-columns:1fr 1fr}.mk-links{display:none}.mk-nav{height:68px}.mk-nav-actions .mk-btn-ghost{display:none}.mk-hero{padding:61px 0}.mk-hero-grid{grid-template-columns:1fr}.mk-app{grid-template-columns:95px 1fr}.mk-card-grid,.mk-testimonials,.mk-industry-grid,.mk-resource-grid,.mk-evidence-grid{grid-template-columns:1fr}.mk-card-grid.eight{grid-template-columns:1fr}.mk-feature-split{grid-template-columns:1fr}.mk-steps{grid-template-columns:repeat(2,1fr)}.mk-steps.four{grid-template-columns:repeat(2,minmax(0,1fr))}.mk-step:nth-child(even):after{display:none}.mk-reassure{grid-template-columns:1fr}.mk-reassure-item{border-right:0}.mk-footer-grid{grid-template-columns:1fr 1fr}.mk-cta{align-items:flex-start;flex-direction:column}.mk-cockpit-grid{grid-template-columns:repeat(2,1fr)}}
        /* Sprint 53 — enterprise readability, conversion, and page-specific storytelling */
        .mk-page-hero-grid{grid-template-columns:minmax(460px,.92fr) minmax(500px,1.08fr)!important;gap:76px!important}.mk-page-hero h1{font-size:clamp(44px,4.25vw,62px)!important}.mk-page-hero p{font-size:18px!important}.mk-card p,.mk-industry p,.mk-resource p,.mk-price-card p,.mk-price-card li,.mk-faq-item p{font-size:16px!important;line-height:1.7!important}.mk-card h3{font-size:20px!important}.mk-compare{font-size:16px!important}.mk-compare th,.mk-compare td{padding:18px 16px!important}.mk-footer p,.mk-footer a{font-size:14px!important}.mk-hero-visual{min-height:410px;display:flex;flex-direction:column;justify-content:center}.mk-visual-card strong{font-size:21px!important}.mk-visual-card span,.mk-visual-row,.mk-visual-highlight span{font-size:11px!important}.mk-visual-row{padding:11px!important}.mk-visual-highlight{padding:14px 15px!important}.mk-role-grid,.mk-industry-all-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.mk-role-card,.mk-industry-pill{border:1px solid var(--mk-border);border-radius:14px;background:#fff;padding:18px;box-shadow:0 10px 28px rgba(15,23,42,.045)}.mk-role-card strong,.mk-industry-pill strong{display:block;font-size:16px;color:var(--mk-ink)!important;margin-bottom:6px}.mk-role-card span,.mk-industry-pill span{font-size:14px;line-height:1.55;color:var(--mk-copy)!important}.mk-flow-story{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;align-items:stretch}.mk-flow-node{position:relative;border:1px solid var(--mk-border);border-radius:14px;background:#fff;padding:20px;box-shadow:0 12px 30px rgba(15,23,42,.05)}.mk-flow-node:after{content:'→';position:absolute;right:-12px;top:50%;transform:translateY(-50%);width:24px;height:24px;border-radius:50%;background:#2563eb;color:#fff;display:grid;place-items:center;font-size:12px;font-weight:900;z-index:2}.mk-flow-node:last-child:after{display:none}.mk-flow-node b{display:block;color:#2563eb!important;font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}.mk-flow-node strong{display:block;color:var(--mk-ink)!important;font-size:16px;margin-bottom:7px}.mk-flow-node span{color:var(--mk-copy)!important;font-size:14px;line-height:1.55}.mk-report-preview{display:grid;grid-template-columns:88px 1fr;gap:14px;align-items:center}.mk-report-thumb{height:112px;border-radius:10px;background:linear-gradient(160deg,#fff,#eef4ff);border:1px solid #dbe5f2;padding:10px;box-shadow:0 12px 22px rgba(15,23,42,.08)}.mk-report-thumb i{display:block;height:5px;background:#dbe7fb;border-radius:4px;margin:7px 0}.mk-report-thumb i:first-child{width:65%;background:#2f6df6}.mk-report-thumb i:nth-child(3){width:78%}.mk-report-thumb i:nth-child(4){width:55%}@media(max-width:1100px){.mk-role-grid,.mk-industry-all-grid{grid-template-columns:repeat(2,1fr)}.mk-flow-story{grid-template-columns:1fr 1fr}.mk-flow-node:after{display:none}.mk-page-hero-grid{grid-template-columns:1fr!important}}@media(max-width:620px){.mk-role-grid,.mk-industry-all-grid,.mk-flow-story{grid-template-columns:1fr}.mk-page-hero p{font-size:16px!important}}
        @media(max-width:560px){.mk-wrap,.mk-wide{width:min(100% - 28px,1180px)}.mk-brand{font-size:20px}.mk-logo{width:34px;height:34px}.mk-nav-actions .mk-btn-primary{padding:0 12px;font-size:11px}.mk-hero h1{font-size:43px}.mk-hero-copy{font-size:15px}.mk-product{display:none}.mk-section{padding:62px 0}.mk-heading h2,.mk-feature-copy h2{font-size:34px}.mk-steps{grid-template-columns:1fr}.mk-steps.four{grid-template-columns:1fr;max-width:420px}.mk-step:after{display:none}.mk-pricing{grid-template-columns:1fr}.mk-footer-grid{grid-template-columns:1fr}.mk-footer-bottom{flex-direction:column}.mk-kpis{grid-template-columns:repeat(2,1fr)}}

        /* Sprint 51.2 final polish */
        .mk-hero-grid{grid-template-columns:minmax(500px,525px) minmax(0,1fr);gap:56px}.mk-hero-copy{max-width:520px}.mk-product{width:100%;max-width:860px;justify-self:end}
        /* Emergency Restoration 61.0.3 — explicit contrast tokens for navy surfaces. */
        .mk-section.dark .mk-kicker,
        .mk-section.dark .mk-eyebrow,
        .mk-cta .mk-kicker,
        .mk-footer .mk-kicker{color:#bcd4ff!important}
        .mk-section.dark .mk-heading h2,
        .mk-section.dark .mk-feature-copy h2,
        .mk-section.dark .mk-feature-copy h3,
        .mk-section.dark>.mk-wrap>h2,
        .mk-section.dark>.mk-wrap>h3{color:#ffffff!important}
        .mk-section.dark .mk-heading p,
        .mk-section.dark .mk-feature-copy>p,
        .mk-section.dark>.mk-wrap>p,
        .mk-section.dark .mk-check span{color:#c8d6e9!important}
        .mk-section.dark a:not(.mk-btn),
        .mk-section.dark button:not(.mk-btn),
        .mk-cta a:not(.mk-btn),
        .mk-cta button:not(.mk-btn),
        .mk-footer a{color:#b9d1ff!important}
        .mk-section.dark a:not(.mk-btn):hover,
        .mk-section.dark button:not(.mk-btn):hover,
        .mk-cta a:not(.mk-btn):hover,
        .mk-cta button:not(.mk-btn):hover,
        .mk-footer a:hover{color:#ffffff!important}
        .mk-cta .mk-btn-primary,.mk-cta .mk-btn-primary *{color:#ffffff!important}
        .mk-cta .mk-btn-light,.mk-cta .mk-btn-light *{color:#0b1730!important}
        .mk-security-banner a:not(.mk-btn),.mk-security-banner button:not(.mk-btn),
        .mk-visual-highlight a:not(.mk-btn),.mk-visual-highlight button:not(.mk-btn),
        .mk-ai-box a:not(.mk-btn),.mk-ai-box button:not(.mk-btn),
        .mk-cockpit a:not(.mk-btn),.mk-cockpit button:not(.mk-btn){color:#c7dcff!important}
        .mk-security-banner a:not(.mk-btn):hover,.mk-security-banner button:not(.mk-btn):hover,
        .mk-visual-highlight a:not(.mk-btn):hover,.mk-visual-highlight button:not(.mk-btn):hover,
        .mk-ai-box a:not(.mk-btn):hover,.mk-ai-box button:not(.mk-btn):hover,
        .mk-cockpit a:not(.mk-btn):hover,.mk-cockpit button:not(.mk-btn):hover{color:#ffffff!important}

        .mk-page-hero{padding:72px 0;background:radial-gradient(circle at 80% 18%,rgba(49,111,246,.24),transparent 31%),linear-gradient(135deg,#06142c,#0d2a59);color:#fff}.mk-page-hero-grid{display:grid;grid-template-columns:minmax(0,.95fr) minmax(420px,.85fr);gap:70px;align-items:center}.mk-page-hero h1{font-size:clamp(46px,4vw,64px);line-height:1.05;letter-spacing:-.05em;color:#fff!important;max-width:760px}.mk-page-hero p{font-size:17px;line-height:1.7;color:#c7d2e4!important;max-width:720px}.mk-hero-visual{background:rgba(255,255,255,.96);border:1px solid rgba(255,255,255,.5);border-radius:18px;padding:18px;box-shadow:0 30px 85px rgba(0,0,0,.28)}.mk-visual-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;color:#0b1730;font-size:12px;font-weight:800}.mk-visual-chip{padding:5px 8px;border-radius:999px;background:#eaf1ff;color:#2563eb!important;font-size:9px}.mk-visual-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.mk-visual-card{border:1px solid #dfe7f1;border-radius:11px;padding:13px;background:#fff}.mk-visual-card strong{display:block;color:#0b1730!important;font-size:18px}.mk-visual-card span{font-size:9px;color:#718198!important;text-transform:uppercase;letter-spacing:.06em}.mk-visual-list{margin-top:10px;display:grid;gap:8px}.mk-visual-row{display:grid;grid-template-columns:28px 1fr auto;gap:9px;align-items:center;padding:9px;border-radius:9px;background:#f5f8fc;color:#53657b!important;font-size:10px}.mk-visual-row b{color:#0b1730!important}.mk-visual-badge{width:28px;height:28px;border-radius:8px;background:#e8f0ff;display:grid;place-items:center;color:#2563eb!important;font-weight:800}.mk-visual-status{font-size:9px;font-weight:800;color:#15985a!important}.mk-visual-status.warn{color:#c77b11!important}.mk-visual-status.risk{color:#d74349!important}.mk-visual-highlight{margin-top:10px;padding:11px 12px;border-radius:10px;background:linear-gradient(135deg,#0d2b59,#19468d);color:#fff!important;display:flex;justify-content:space-between;gap:14px;align-items:center}.mk-visual-highlight b{display:block;color:#fff!important;font-size:11px}.mk-visual-highlight span{color:#d5e3f8!important;font-size:9px;line-height:1.45}.mk-visual-cta{flex:none;padding:6px 9px;border-radius:7px;background:#2f6df6;color:#fff!important;font-size:8px;font-weight:800}.mk-subnav{border-bottom:1px solid #e2e8f0;background:#fff}.mk-subnav-inner{display:flex;gap:9px;flex-wrap:wrap;padding:15px 0}.mk-subnav-inner a{display:inline-flex;padding:8px 12px;border-radius:999px;background:#f3f6fb;border:1px solid #e0e7f0;color:#334155!important;text-decoration:none!important;font-size:12px;font-weight:750}.mk-subnav-inner a:hover{background:#e8f0ff;color:#1d4ed8!important}.mk-pricing{grid-template-columns:repeat(5,1fr)}.mk-price-card{display:flex;flex-direction:column}.mk-price-card ul{flex:1}.mk-price-card.enterprise{background:linear-gradient(145deg,#0b1d3e,#15366e);border-color:#284f93}.mk-price-card.enterprise *{color:#fff!important}.mk-price-card.enterprise p,.mk-price-card.enterprise li{color:#cfdbed!important}.mk-price-card.enterprise .mk-btn-light{background:#fff!important;color:#0b1730!important;border-color:#fff!important;width:100%;box-sizing:border-box}.mk-price-card.enterprise .mk-btn-light:hover{background:#edf4ff!important}.mk-plan-label{display:inline-flex;align-self:flex-start;padding:5px 9px;border-radius:999px;background:#eef4ff;color:#2563eb!important;font-size:9px;font-weight:800;margin-bottom:10px}.mk-price-card.enterprise .mk-plan-label{background:rgba(255,255,255,.12)}.mk-security-banner{background:linear-gradient(135deg,#0c2855,#123a78);border-radius:18px;padding:28px;color:#fff;margin-bottom:28px;display:grid;grid-template-columns:1.2fr .8fr;gap:25px;align-items:center}.mk-security-banner h2{color:#fff!important;margin:0 0 10px}.mk-security-banner p{color:#d3deef!important}.mk-security-points{display:grid;gap:9px}.mk-security-point{display:flex;gap:9px;align-items:flex-start;color:#e8effa!important;font-size:13px}.mk-security-point b{color:#75e2a7!important}.mk-trust-note{font-size:12px;color:#64748b!important;margin-top:14px}.mk-table-wrap{overflow-x:auto}.mk-compare{min-width:900px}
        /* Sprint 51.2.4 — Atlassian-inspired readable type scale */
        .mk-shell{font-size:16px}
        .mk-links{font-size:14px;gap:30px}.mk-btn{font-size:14px;min-height:45px;padding:0 20px}
        .mk-hero-copy,.mk-page-hero p{font-size:18px;line-height:1.68}.mk-proof{font-size:14px}
        .mk-trust-label{font-size:11px}.mk-logo-text{font-size:17px}.mk-logo-text small{font-size:9px}
        .mk-kicker{font-size:12px}.mk-heading p,.mk-feature-copy>p{font-size:17px;line-height:1.72}
        .mk-card h3{font-size:19px}.mk-card p{font-size:15px;line-height:1.68}.mk-card a,.mk-card button[data-cv-public],.mk-card button[data-cv-auth]{font-size:14px}
        .mk-check span{font-size:15px}.mk-step h3{font-size:17px}.mk-step p{font-size:14px;line-height:1.62}
        .mk-quote p,.mk-industry p,.mk-resource p{font-size:15px;line-height:1.7}
        .mk-industry h3,.mk-resource h3{font-size:20px}.mk-industry ul,.mk-price-card ul{font-size:14px;line-height:1.72}.mk-industry a,.mk-resource a,.mk-industry button[data-cv-public],.mk-resource button[data-cv-public],.mk-industry button[data-cv-auth],.mk-resource button[data-cv-auth]{font-size:14px}.mk-resource-type{font-size:11px}
        .mk-price-name{font-size:16px}.mk-price{font-size:38px}.mk-price small{font-size:14px}.mk-price-card p{font-size:14px;line-height:1.62;min-height:68px}.mk-plan-label,.mk-popular{font-size:10px}
        .mk-compare{font-size:15px;line-height:1.45;min-width:980px}.mk-compare th,.mk-compare td{padding:17px 15px}.mk-compare th{font-size:15px}.mk-compare td:first-child,.mk-compare th:first-child{font-weight:700}
        .mk-faq-item{padding:22px}.mk-faq-item strong{font-size:16px}.mk-faq-item p{font-size:15px;line-height:1.68}
        .mk-security-point{font-size:15px}.mk-trust-note{font-size:14px}
        .mk-footer p,.mk-footer a{font-size:13px}.mk-footer h4{font-size:12px}.mk-footer-bottom{font-size:12px}
        .mk-subnav-inner a{font-size:14px;padding:9px 14px}
        @media(max-width:820px){.mk-hero-copy,.mk-page-hero p{font-size:17px}.mk-compare{font-size:14px}.mk-compare th,.mk-compare td{padding:15px 13px}}
        @media(max-width:560px){.mk-shell{font-size:15px}.mk-card p,.mk-quote p,.mk-industry p,.mk-resource p,.mk-faq-item p{font-size:15px}.mk-btn{font-size:13px}}

        @media(max-width:1180px){.mk-hero-grid,.mk-page-hero-grid{grid-template-columns:1fr}.mk-product,.mk-hero-visual{justify-self:stretch;max-width:none}.mk-pricing{grid-template-columns:repeat(2,1fr)}}
        @media(max-width:700px){.mk-pricing{grid-template-columns:1fr}.mk-page-hero{padding:58px 0}.mk-page-hero h1{font-size:42px}.mk-security-banner{grid-template-columns:1fr}}
        /* Public Navigation Runtime Conversion */
        .st-key-cv_public_nav{background:var(--mk-navy)!important;border-bottom:1px solid rgba(255,255,255,.09)!important;padding:13px max(24px,calc((100vw - 1400px)/2))!important;position:relative;z-index:40;margin:0!important}
        .st-key-cv_public_nav [data-testid="stHorizontalBlock"]{align-items:center!important;gap:8px!important}
        .st-key-cv_public_nav .stButton>button{min-height:44px!important;height:44px!important;border:0!important;border-radius:8px!important;background:transparent!important;color:#d7dfed!important;box-shadow:none!important;padding:0 11px!important;font-size:14px!important;font-weight:760!important;white-space:nowrap!important}
        .st-key-cv_public_nav .stButton>button:hover{background:rgba(255,255,255,.07)!important;color:#fff!important;transform:none!important}
        .st-key-cv_public_brand{position:relative!important;min-height:46px!important;display:flex!important;align-items:center!important;overflow:visible!important}
        .cv-public-brand-visual{display:flex;align-items:center;gap:11px;color:#fff;font-size:22px;font-weight:900;letter-spacing:-.035em;pointer-events:none;white-space:nowrap;position:relative;z-index:1}
        .cv-public-brand-mark{width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center;flex:0 0 34px;border-radius:9px;background:linear-gradient(145deg,#4b8cff,#1f5be5);color:#fff;font-size:18px;font-weight:900;line-height:1;box-shadow:0 9px 22px rgba(37,99,235,.36),inset 0 1px 0 rgba(255,255,255,.26)}
        .st-key-cv_public_brand .st-key-cv_public_home{position:absolute!important;inset:0!important;z-index:3!important;margin:0!important;padding:0!important;min-height:46px!important;width:100%!important}
        .st-key-cv_public_brand .st-key-cv_public_home .stButton{position:absolute!important;inset:0!important;margin:0!important;padding:0!important;width:100%!important;height:100%!important}
        .st-key-cv_public_brand .st-key-cv_public_home button{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;min-height:46px!important;padding:0!important;margin:0!important;border:0!important;background:transparent!important;box-shadow:none!important;color:transparent!important;font-size:0!important;line-height:0!important;opacity:1!important;cursor:pointer!important}
        .st-key-cv_public_brand .st-key-cv_public_home button p,.st-key-cv_public_brand .st-key-cv_public_home button span{display:none!important}
        .st-key-cv_public_brand .st-key-cv_public_home button:hover,.st-key-cv_public_brand .st-key-cv_public_home button:focus{background:rgba(255,255,255,.035)!important;box-shadow:none!important;outline:none!important}
        .st-key-cv_public_brand .st-key-cv_public_home button:focus-visible{outline:2px solid rgba(96,165,250,.9)!important;outline-offset:3px!important;border-radius:10px!important}
        .st-key-cv_public_login .stButton>button,.st-key-cv_public_contact .stButton>button{border:1px solid rgba(255,255,255,.28)!important;color:#fff!important}
        .st-key-cv_public_signup .stButton>button{background:linear-gradient(180deg,#3978fb,#2462eb)!important;border:1px solid #4b82f7!important;color:#fff!important;box-shadow:0 10px 24px rgba(37,99,235,.28)!important}
        .cv-public-active-route{display:none!important}

        /* Sprint 62 — Landing Page polish. Keep the native Streamlit navigation
           and the marketing hero on one uninterrupted dark canvas. */
        [data-testid="stMainBlockContainer"]>.stVerticalBlock,
        [data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"],
        .main .block-container>.stVerticalBlock,
        .main .block-container>[data-testid="stVerticalBlock"]{gap:0!important}
        [data-testid="stElementContainer"]:has(>.st-key-cv_public_nav),
        [data-testid="element-container"]:has(>.st-key-cv_public_nav){margin:0!important;padding:0!important}
        .st-key-cv_public_nav+div,
        .st-key-cv_public_nav~[data-testid="stElementContainer"]:first-of-type{margin-top:0!important;padding-top:0!important}
        .st-key-cv_public_nav{isolation:isolate;box-shadow:0 18px 0 var(--mk-navy)!important}
        .mk-shell{margin:0!important;padding:0!important}
        .mk-shell>.mk-hero,.mk-shell>.mk-page-hero{margin-top:0!important;border-top:0!important}
        .mk-hero,.mk-page-hero{background-color:var(--mk-navy)!important}
        .mk-section{padding:76px 0}
        .mk-heading{margin-bottom:38px}
        .mk-heading h2{font-size:clamp(34px,3.25vw,46px)}
        .mk-heading p{max-width:760px;margin-left:auto;margin-right:auto}
        .mk-footer{margin-top:0!important}
        @media(max-width:820px){.st-key-cv_public_nav{box-shadow:0 12px 0 var(--mk-navy)!important}.mk-section{padding:62px 0}}
        @media(max-width:1050px){.st-key-cv_public_nav [data-testid="column"]:nth-child(n+7){display:none!important}.st-key-cv_public_nav{overflow-x:auto!important}.st-key-cv_public_nav [data-testid="stHorizontalBlock"]{min-width:760px!important}}

        /* Sprint 62.2 — all body/footer internal links stay in the active runtime. */
        .st-key-cv_public_link_bridge{position:fixed!important;left:-10000px!important;top:-10000px!important;width:1px!important;height:1px!important;overflow:hidden!important;opacity:0!important;pointer-events:none!important}
        .mk-shell [data-cv-public],.mk-shell [data-cv-auth],.mk-footer [data-cv-public],.mk-footer [data-cv-auth]{cursor:pointer!important}
        button[data-cv-public],button[data-cv-auth]{font:inherit;color:inherit;background:none;border:0;padding:0;margin:0;text-align:inherit;appearance:none;-webkit-appearance:none;cursor:pointer}
        button[data-cv-public]:focus-visible,button[data-cv-auth]:focus-visible{outline:2px solid #78a9ff;outline-offset:3px;border-radius:6px}
        button[data-cv-public]:disabled,button[data-cv-auth]:disabled,button[aria-disabled="true"]{cursor:not-allowed;opacity:.62}
        .mk-btn[data-cv-public],.mk-btn[data-cv-auth]{display:inline-flex;align-items:center;justify-content:center}
        .mk-footer button[data-cv-public],.mk-footer button[data-cv-auth],.mk-card button[data-cv-public],.mk-card button[data-cv-auth],.mk-resource button[data-cv-public],.mk-resource button[data-cv-auth]{display:block;width:max-content}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _set_public_route(route: str) -> None:
    """Commit a top-level marketing route without replacing the browser document."""
    normalized = str(route or "home").strip().lower() or "home"
    st.session_state["cadivor_public_route"] = normalized
    st.session_state["cadivor_root_state"] = "public"
    st.session_state["cadivor_public_section"] = ""
    st.session_state["cadivor_footer_active_item"] = ""
    st.session_state["cadivor_public_scroll_nonce"] = int(st.session_state.get("cadivor_public_scroll_nonce", 0)) + 1
    st.session_state.pop("cadivor_last_public_render", None)
    try:
        st.query_params.clear()
    except Exception:
        pass


def _set_public_destination(route: str, section: str = "", item_id: str = "") -> None:
    """Navigate to a public page or a named section with one stable callback."""
    normalized = str(route or "home").strip().lower() or "home"
    target = str(section or "").strip().lower().lstrip("#")
    st.session_state["cadivor_public_route"] = normalized
    st.session_state["cadivor_root_state"] = "public"
    st.session_state["cadivor_public_section"] = target
    st.session_state["cadivor_footer_active_item"] = str(item_id or "").strip().lower()
    st.session_state["cadivor_public_scroll_nonce"] = int(st.session_state.get("cadivor_public_scroll_nonce", 0)) + 1
    st.session_state.pop("cadivor_last_public_render", None)
    try:
        st.query_params.clear()
    except Exception:
        pass


def _open_auth_surface(surface: str) -> None:
    """Open Login or Signup through the root state machine."""
    normalized = "signup" if str(surface).lower() == "signup" else "login"
    st.session_state["cadivor_root_state"] = normalized
    st.session_state.pop("cadivor_last_public_render", None)
    try:
        st.query_params.clear()
    except Exception:
        pass


def _nav(active: str = "home") -> None:
    """Native Streamlit marketing navigation.

    Browser query anchors previously destroyed the Streamlit document and
    exposed the host skeleton, raw HTML, and white/black initialization frames.
    These keyed buttons commit session state before the widget rerun, keeping
    navigation inside the active application session.
    """
    with st.container(key="cv_public_nav"):
        cols = st.columns([1.65, .78, .82, .72, .86, .76, .34, .74, 1.02, .94], gap="small")
        with cols[0]:
            with st.container(key="cv_public_brand"):
                st.markdown(
                    '<div class="cv-public-brand-visual" aria-hidden="true"><span class="cv-public-brand-mark">C</span><span>Cadivor</span></div>',
                    unsafe_allow_html=True,
                )
                st.button(
                    "Home",
                    key="cv_public_home",
                    on_click=_set_public_route,
                    args=("home",),
                    use_container_width=True,
                    type="primary" if active == "home" else "secondary",
                )
        for col, (route, label) in zip(cols[1:6], PRODUCT_LINKS):
            with col:
                st.button(
                    label,
                    key=f"cv_public_{route}",
                    on_click=_set_public_route,
                    args=(route,),
                    use_container_width=True,
                    type="primary" if active == route else "secondary",
                )
        with cols[7]:
            st.button("Sign In", key="cv_public_login", on_click=_open_auth_surface, args=("login",), use_container_width=True)
        with cols[8]:
            st.button("Start Free Trial", key="cv_public_signup", on_click=_open_auth_surface, args=("signup",), use_container_width=True)
        with cols[9]:
            st.button("Book a Demo", key="cv_public_contact", on_click=_set_public_route, args=("contact",), use_container_width=True)
    st.markdown(f'<div class="cv-public-active-route" data-route="{escape(active)}"></div>', unsafe_allow_html=True)


def _footer(active: str | None = None) -> None:
    """Render a stable footer with explicit page/section destinations."""
    current_route = str(active or st.session_state.get("cadivor_public_route") or "home").strip().lower()
    active_footer_item = str(st.session_state.get("cadivor_footer_active_item") or "").strip().lower()
    if not active_footer_item:
        active_footer_item = {
            "product": "overview", "solutions": "robotics", "pricing": "pricing",
            "resources": "getting_started", "company": "about", "security": "security",
            "contact": "contact", "privacy": "privacy", "terms": "terms",
        }.get(current_route, "")

    footer_groups = (
        ("Product", (
            ("overview", "Overview", "product", "bom-analyzer"),
            ("engineering_intelligence", "Engineering Intelligence", "product", "engineering-intelligence"),
            ("ask_cadivor", "Ask Cadivor", "product", "copilot"),
            ("pricing", "Pricing", "pricing", ""),
        )),
        ("Solutions", (
            ("robotics", "Robotics", "solutions", "robotics"),
            ("medical_devices", "Medical Devices", "solutions", "medical"),
            ("industrial_automation", "Industrial Automation", "solutions", "industrial"),
            ("hardware_startups", "Hardware Startups", "solutions", "hardware-startups"),
        )),
        ("Resources", (
            ("getting_started", "Getting Started", "resources", "getting-started"),
            ("demo_boms", "Demo BOMs", "resources", "demo-boms"),
            ("engineering_guides", "Engineering Guides", "resources", "engineering-guides"),
            ("faq", "FAQ", "resources", "faq"),
        )),
        ("Company", (
            ("about", "About", "company", "about"),
            ("security", "Security", "security", ""),
            ("contact", "Contact", "contact", ""),
            ("privacy", "Privacy", "privacy", ""),
            ("terms", "Terms", "terms", ""),
        )),
    )

    st.markdown(
        """
        <style>
        .st-key-cv_native_footer{position:relative;margin-top:0;padding:52px max(24px,calc((100vw - 1180px)/2)) 24px;background:#06142c;color:#fff}
        .st-key-cv_native_footer::before{content:"";position:absolute;inset:0 calc(50% - 50vw);z-index:-1;background:#06142c}
        .st-key-cv_native_footer [data-testid="stHorizontalBlock"]{gap:34px;align-items:flex-start!important}
        .st-key-cv_native_footer [data-testid="stMarkdownContainer"] p{margin:0;color:#91a4bf!important;font-size:13px!important;line-height:1.7!important}
        .st-key-cv_native_footer .cv-footer-heading{height:24px;margin:0 0 8px;color:#fff!important;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;display:flex;align-items:center}
        .st-key-cv_native_footer .cv-footer-coverage{display:grid;gap:0;color:#8fa0b8!important;font-size:13px}
        .st-key-cv_native_footer .cv-footer-coverage span{height:36px;display:flex;align-items:center;margin:0!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"]{margin:0!important;padding:0!important;min-height:36px!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button{min-height:36px!important;height:auto!important;width:100%!important;margin:0!important;padding:7px 0!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;color:#aebdd0!important;font-size:13px!important;font-weight:550!important;line-height:1.35!important;text-align:left!important;justify-content:flex-start!important;white-space:normal!important;cursor:pointer!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button:hover{color:#fff!important;background:transparent!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button:active{transform:none!important;color:#fff!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button:focus-visible{color:#fff!important;outline:1px solid #75a7ff!important;outline-offset:2px!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button[kind="primary"]{color:#fff!important;background:transparent!important;border:0!important;font-weight:700!important;box-shadow:none!important;position:relative!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button[kind="primary"]::after{content:""!important;position:absolute!important;left:0!important;bottom:4px!important;width:22px!important;height:2px!important;border-radius:2px!important;background:#75a7ff!important}
        .st-key-cv_native_footer .st-key-cv_footer_brand button{display:inline-flex!important;align-items:center!important;gap:10px!important;min-height:42px!important;width:auto!important;padding:4px 8px 4px 0!important;color:#fff!important;font-size:20px!important;font-weight:800!important;letter-spacing:-.025em!important}
        .st-key-cv_native_footer .st-key-cv_footer_brand button::before{content:"C";display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:linear-gradient(145deg,#3478ff,#1e56cf);color:#fff;font-size:16px;font-weight:900;box-shadow:0 8px 24px rgba(47,109,246,.28)}
        .st-key-cv_native_footer .cv-footer-bottom{display:flex;justify-content:space-between;gap:20px;margin-top:34px;padding-top:18px;border-top:1px solid rgba(255,255,255,.09);color:#8192aa;font-size:11px}
        @media(max-width:900px){.st-key-cv_native_footer [data-testid="stHorizontalBlock"]{flex-wrap:wrap}.st-key-cv_native_footer [data-testid="column"]{min-width:42%;flex:1 1 42%}.st-key-cv_native_footer .cv-footer-bottom{flex-direction:column}}
        </style>
        """, unsafe_allow_html=True)

    with st.container(key="cv_native_footer"):
        cols=st.columns([1.55,1,1,1,1,1],gap="large")
        with cols[0]:
            st.button("Cadivor",key="cv_footer_brand",on_click=_set_public_route,args=("home",),type="secondary")
            st.markdown("Engineering intelligence that helps hardware teams understand BOM risk, evaluate alternatives, and make better decisions before production.")
        for column_index,(heading,links) in enumerate(footer_groups,start=1):
            with cols[column_index]:
                st.markdown(f'<div class="cv-footer-heading">{escape(heading)}</div>',unsafe_allow_html=True)
                for item_id,label,route,section in links:
                    st.button(label,key=f"cv_footer_{item_id}",on_click=_set_public_destination,args=(route,section,item_id),use_container_width=True,type="primary" if active_footer_item==item_id else "secondary")
        with cols[5]:
            st.markdown('<div class="cv-footer-heading">Data coverage</div><div class="cv-footer-coverage"><span>DigiKey</span><span>Mouser</span><span>Newark</span><span>Octopart — Coming soon</span></div>',unsafe_allow_html=True)
        st.markdown('<div class="cv-footer-bottom"><span>© 2026 Cadivor. All rights reserved.</span><span>Engineering decision support—not a replacement for professional validation.</span></div>',unsafe_allow_html=True)


def _cta(title: str = "Make your next BOM review faster and more decisive.", copy: str = "Start with a 14-day full-access trial. No credit card required.") -> None:
    _html(f"""
    <section class="mk-section"><div class="mk-wrap"><div class="mk-cta">
      <div><h2>{escape(title)}</h2><p>{escape(copy)}</p></div>
      <div class="mk-actions" style="margin:0"><button type="button" class="mk-btn mk-btn-primary" data-cv-auth="signup">Start Free Trial</button><button type="button" class="mk-btn mk-btn-light" data-cv-public="contact">Book a Demo</button></div>
    </div></div></section>
    """)


def _dashboard_mockup() -> str:
    return f"""
    <div class="mk-product">
      <div class="mk-product-top"><div class="mk-dots"><i></i><i></i><i></i></div><span style="font-size:7px;color:#64748b;font-weight:800">Acme Engineering · Motor Controller Rev C</span></div>
      <div class="mk-app"><div class="mk-side"><div class="mk-side-brand">CADIVOR</div><div class="mk-side-item active">Dashboard</div><div class="mk-side-item">BOM Analyzer</div><div class="mk-side-item">Alternative Finder</div><div class="mk-side-item">Monitoring</div><div class="mk-side-item">Engineering Decisions</div><div class="mk-side-item">Procurement Advisor</div><div class="mk-side-item">Portfolio Intelligence</div><div class="mk-side-item">Design Impact Analyzer</div><div class="mk-side-item">Cost Optimization</div><div class="mk-side-item">Reports</div></div>
      <div class="mk-main"><div class="mk-main-head"><strong>Executive Decision Cockpit</strong><span class="mk-mini-button">View Full Report</span></div>
      <div class="mk-kpis">
        <div class="mk-kpi"><div class="mk-kpi-top"><span>Overall BOM Health</span><i class="mk-kpi-icon">{_icon('portfolio')}</i></div><strong>84<span style="display:inline;font-size:8px">/100</span></strong><small class="mk-delta">Good · +6 vs last review</small></div>
        <div class="mk-kpi"><div class="mk-kpi-top"><span>Priority Risks</span><i class="mk-kpi-icon">{_icon('shield')}</i></div><strong>7</strong><small class="mk-delta" style="color:#d88a17!important">3 require action</small></div>
        <div class="mk-kpi"><div class="mk-kpi-top"><span>Monitored Parts</span><i class="mk-kpi-icon">{_icon('monitor')}</i></div><strong>1,248</strong><small class="mk-delta">98.7% reviewed</small></div>
        <div class="mk-kpi"><div class="mk-kpi-top"><span>Potential Cost Impact</span><i class="mk-kpi-icon">{_icon('report')}</i></div><strong>$12,430</strong><small class="mk-delta">5.7% of BOM cost</small></div>
      </div>
      <div class="mk-decision-grid">
        <div class="mk-panel"><div class="mk-panel-title">Top Component Risks</div><div class="mk-risk-list">
          <div class="mk-risk-item"><span class="mk-risk-badge red">3</span><span class="mk-risk-name"><b>MPU6050</b><small>EOL announced · single source</small></span><span class="mk-action-pill">Review</span></div>
          <div class="mk-risk-item"><span class="mk-risk-badge amber">2</span><span class="mk-risk-name"><b>LM35DN</b><small>Stock declining · 18 weeks</small></span><span class="mk-action-pill">Qualify</span></div>
          <div class="mk-risk-item"><span class="mk-risk-badge amber">1</span><span class="mk-risk-name"><b>TPS54331</b><small>Lifecycle change detected</small></span><span class="mk-action-pill">Monitor</span></div>
          <div class="mk-risk-item"><span class="mk-risk-badge blue">1</span><span class="mk-risk-name"><b>ATMEGA328P-AU</b><small>Alternate available</small></span><span class="mk-action-pill">Compare</span></div>
        </div></div>
        <div class="mk-ai-box"><div class="mk-panel-title">AI Engineering Recommendation</div><div class="mk-ai-score"><div class="mk-ai-metric"><span>Release posture</span><strong>HOLD</strong></div><div class="mk-ai-metric"><span>Confidence</span><strong>87%</strong></div></div><div class="mk-ai-copy">Replace the MPU6050 before production release and qualify the proposed alternate for LM35DN. Current evidence indicates avoidable lifecycle, supplier-concentration, and sourcing exposure. Procurement should qualify the proposed second source before release.</div><span class="mk-mini-button" style="display:inline-block;margin-top:8px">Review Recommendations</span></div>
      </div>
      <div class="mk-table"><div class="mk-row head"><div>Recent engineering activity</div><div>Type</div><div>Status</div><div>Owner</div></div><div class="mk-row"><div>MPU6050 alternate proposed</div><div>Decision</div><div class="mk-risk medium">Review</div><div>J. Patel</div></div><div class="mk-row"><div>Lifecycle report generated</div><div>Report</div><div class="mk-risk low">Ready</div><div>System</div></div><div class="mk-row"><div>Supplier evidence updated</div><div>Monitoring</div><div class="mk-risk low">Complete</div><div>Cadivor</div></div></div>
      </div></div>
    </div>
    """


def _home() -> None:
    _nav("home")
    _html(f"""
    <main class="mk-shell mk-launch-story">
      <section class="mk-hero mk-launch-hero"><div class="mk-wide mk-launch-hero-grid">
        <div class="mk-launch-copy">
          <div class="mk-eyebrow"><i class="mk-eyebrow-dot"></i>Engineering Decision Intelligence for hardware teams</div>
          <h1>Turn BOM risk into <span class="mk-accent">defensible engineering decisions.</span></h1>
          <p class="mk-hero-copy">Cadivor gives hardware teams one decision system for BOM health, lifecycle exposure, supplier resilience, alternate qualification, AI-assisted review, and release accountability.</p>
          <div class="mk-actions mk-launch-actions"><button type="button" class="mk-btn mk-btn-primary" data-cv-auth="signup">Start 14-Day Free Trial</button><a class="mk-btn mk-btn-ghost mk-scroll-cta" href="#workflow">See How It Works</a></div>
          <div class="mk-proof"><span><b>✓</b>No credit card required</span><span><b>✓</b>CSV and Excel BOMs</span><span><b>✓</b>Decision support in minutes</span></div>
        </div>
        <div class="mk-demo-stage" aria-label="Cadivor product demo container">
          <div class="mk-demo-frame">
            <div class="mk-demo-toolbar"><span class="mk-demo-dots"><i></i><i></i><i></i></span><span>Motor Controller Rev C · Engineering Review</span><em><span class="mk-live-dot"></span>Live product workspace</em></div>
            <div class="mk-demo-layout">
              <aside><strong>CADIVOR</strong><span class="active">Decision Cockpit</span><span>BOM Analyzer</span><span>Engineering Copilot</span><span>Alternatives</span><span>Monitoring</span><span>Decisions</span></aside>
              <div class="mk-demo-content">
                <div class="mk-demo-head"><div><small>PRODUCT RELEASE REVIEW</small><h3>Motor Controller Rev C</h3></div><span class="mk-release-hold">Release Hold</span></div>
                <div class="mk-demo-kpis">
                  <div><small>BOM Health</small><strong>72</strong><span class="amber">Needs review</span></div>
                  <div><small>High-Risk Components</small><strong>4</strong><span class="red">2 release blockers</span></div>
                  <div><small>Lifecycle Alerts</small><strong>7</strong><span>3 new this week</span></div>
                  <div><small>Approved Decisions</small><strong>12</strong><span class="green">Audit ready</span></div>
                  <div><small>Alternate Components</small><strong>18</strong><span>5 recommended</span></div>
                  <div><small>Monitoring</small><strong>146</strong><span class="green">Parts active</span></div>
                </div>
                <div class="mk-demo-bottom">
                  <div class="mk-risk-panel"><div class="mk-demo-title">Priority engineering risks</div><div class="mk-risk-line"><b>MPU6050</b><span>EOL · single source</span><em>Blocker</em></div><div class="mk-risk-line"><b>LM35DN</b><span>18-week lead time</span><em>Qualify</em></div><div class="mk-risk-line"><b>TPS54331</b><span>Lifecycle change</span><em>Monitor</em></div></div>
                  <div class="mk-demo-recommendation"><div class="mk-demo-title">Cadivor recommendation</div><strong>Do not release this BOM yet.</strong><p>Replace MPU6050 and qualify the proposed second source for LM35DN. These two actions remove the highest avoidable production exposure.</p><span>Confidence 87% · 14 evidence points</span></div>
                </div>
              </div>
            </div>
            <div class="mk-media-slot"><video autoplay muted loop playsinline aria-label="Cadivor product demonstration"></video><span>MP4/WebM-ready product media layer</span></div>
          </div>
        </div>
      </div></section>

      <section class="mk-trust"><div class="mk-wrap mk-trust-inner"><span class="mk-trust-label">Live supplier coverage</span><span class="mk-logo-text">DigiKey</span><span class="mk-logo-text">Mouser</span><span class="mk-logo-text">Newark</span><span class="mk-trust-divider"></span><span class="mk-logo-text">Octopart <small>Coming Soon</small></span></div></section>

      <section class="mk-section mk-workflow-section" id="workflow"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">The engineering workflow</div><h2>One connected path from BOM upload to release decision.</h2><p>Every step adds context and evidence, so engineering, procurement, and supply chain can act from the same review.</p></div><div class="mk-workflow-grid">
        <article><span>01</span><div class="mk-icon">{_icon('bom')}</div><h3>Upload BOM</h3><p>Import CSV or Excel files and normalize manufacturer part numbers, quantities, and product context.</p><small>INPUT · STRUCTURED BOM</small></article>
        <article><span>02</span><div class="mk-icon">{_icon('portfolio')}</div><h3>Analyze Risk</h3><p>Surface lifecycle, stock, lead-time, supplier concentration, cost, and sourcing exposure.</p><small>OUTPUT · PRIORITIZED EXPOSURE</small></article>
        <article><span>03</span><div class="mk-icon">{_icon('chat')}</div><h3>AI Copilot</h3><p>Ask what matters first, challenge recommendations, and trace every conclusion to supporting evidence.</p><small>OUTPUT · EXPLAINED RECOMMENDATION</small></article>
        <article><span>04</span><div class="mk-icon">{_icon('decision')}</div><h3>Engineering Decision</h3><p>Approve, reject, assign, monitor, and preserve the rationale behind the release decision.</p><small>OUTPUT · AUDITABLE ACTION</small></article>
      </div></div></section>

      <section class="mk-section soft" id="engineering-intelligence"><div class="mk-wrap mk-intelligence-layout"><div class="mk-feature-copy"><div class="mk-kicker">Engineering Intelligence</div><h2>Replace generic dashboards with the metrics engineers actually act on.</h2><p>Cadivor translates component-level data into a release-oriented view of product health, blockers, alternatives, and accountable actions.</p><ul class="mk-check-list"><li>Prioritized release blockers—not just raw alerts</li><li>Evidence across lifecycle, availability, suppliers, and cost</li><li>Clear owners and next actions for every critical issue</li></ul><button type="button" class="mk-text-action" data-cv-public="product">Explore Engineering Intelligence →</button></div><div class="mk-metric-showcase">
        <div><small>BOM Health</small><strong>72 / 100</strong><span>↑ 6 after two mitigations</span></div><div><small>High-Risk Components</small><strong>4</strong><span>2 require action before release</span></div><div><small>Lifecycle Alerts</small><strong>7</strong><span>3 newly detected changes</span></div><div><small>Approved Decisions</small><strong>12</strong><span>Complete rationale and history</span></div><div><small>Alternate Components</small><strong>18</strong><span>5 ranked recommendations</span></div><div><small>Monitoring</small><strong>146</strong><span>Continuous part surveillance</span></div>
      </div></div></section>

      <section class="mk-section" id="copilot"><div class="mk-wrap mk-copilot-layout"><div class="mk-copilot-window"><div class="mk-copilot-top"><span>{_icon('chat')} Engineering Copilot</span><em>Grounded in Motor Controller Rev C</em></div><div class="mk-message user"><small>You</small><p>What should I review first in this BOM?</p></div><div class="mk-message assistant"><small>Cadivor · Engineering analysis</small><div class="mk-answer-header"><strong>Review the MPU6050 first.</strong><span>93% confidence</span></div><p>It is the only current release blocker: EOL has been announced, the approved source count is one, and no qualified alternate is attached to the decision record.</p><div class="mk-evidence-block"><b>WHY THIS RANKS FIRST</b><code>Lifecycle severity: EOL
Approved sources: 1
Qualified alternates: 0
Production impact: Release blocker</code></div><div class="mk-evidence-chips"><span>Lifecycle evidence</span><span>Supplier evidence</span><span>Decision history</span></div></div><div class="mk-message user"><small>You</small><p>What evidence would change that recommendation?</p></div><div class="mk-message assistant"><small>Cadivor</small><p>A validated lifetime-buy plan or an approved form-fit-function alternate with test evidence would reduce the release risk. Supplier stock alone would not remove the lifecycle exposure.</p><button type="button" data-cv-public="product">See the Copilot workflow →</button></div></div><div class="mk-feature-copy"><div class="mk-kicker">AI Copilot</div><h2>Ask the BOM—not another generic chatbot.</h2><p>Cadivor’s Copilot answers within the active engineering context, explains why a recommendation was made, and identifies what evidence could change it.</p><ul class="mk-check-list"><li>Context-aware follow-up questions</li><li>Evidence-linked recommendations</li><li>Release, sourcing, and qualification guidance</li></ul></div></div></section>

      <section class="mk-section soft" id="supplier-intelligence"><div class="mk-wrap mk-feature-split"><div class="mk-feature-copy"><div class="mk-kicker">Supplier Intelligence</div><h2>See sourcing resilience—not just a stock number.</h2><p>Compare authorized sources, inventory, lead time, supplier concentration, and alternates in the same engineering review.</p><button type="button" class="mk-text-action" data-cv-public="product">Explore Supplier Intelligence →</button></div><div class="mk-supplier-board"><div class="mk-supplier-row head"><span>Component</span><span>Sources</span><span>Lead time</span><span>Action</span></div><div class="mk-supplier-row"><b>MPU6050</b><span>1 approved</span><span>26 weeks</span><em>Replace</em></div><div class="mk-supplier-row"><b>LM35DN</b><span>2 available</span><span>18 weeks</span><em>Qualify</em></div><div class="mk-supplier-row"><b>TPS54331</b><span>4 available</span><span>8 weeks</span><em>Monitor</em></div><div class="mk-supplier-summary"><div><strong>Recommended next move</strong><p>Qualify the second source for LM35DN before placing the next production order.</p></div><span>Confidence 89%<br>2 authorized sources</span></div></div></div></section>

      <section class="mk-section" id="decision-intelligence"><div class="mk-wrap mk-decision-story"><div class="mk-decision-card"><div class="mk-decision-topline"><span class="mk-decision-status">APPROVED WITH CONDITIONS</span><span class="mk-decision-time">Recorded Jul 31, 2026 · 4:42 PM</span></div><h3>Replace MPU6050 before production release</h3><p>Approved alternate: ICM-42688-P. Validation requires firmware update, vibration testing, and procurement confirmation from two authorized suppliers.</p><div class="mk-decision-meta"><span><b>Owner</b> A. Chen</span><span><b>Due</b> Aug 14</span><span><b>Confidence</b><i class="mk-confidence"><em style="width:87%"></em></i>87%</span><span><b>Evidence</b> 14 items</span></div><div class="mk-rationale"><b>Decision rationale</b><p>The alternate removes the lifecycle blocker and improves sourcing resilience, provided firmware and vibration validation are completed before release.</p></div><div class="mk-decision-history"><i></i><span><b>Recommendation created</b><small>Cadivor · lifecycle and supplier evidence</small></span><i></i><span><b>Engineering approved</b><small>A. Chen · conditions attached</small></span><i></i><span><b>Monitoring enabled</b><small>Cadivor · both components tracked</small></span></div></div><div class="mk-feature-copy"><div class="mk-kicker">Decision Intelligence</div><h2>Turn recommendations into accountable engineering action.</h2><p>Preserve the decision, supporting evidence, owner, conditions, and history—so the next review starts with context instead of reconstruction.</p><button type="button" class="mk-text-action" data-cv-public="product">Explore Decision Records →</button></div></div></section>
    </main>
    """)
    _cta("Make the next BOM review a release decision—not another spreadsheet.", "Start with a 14-day full-access trial, or book a focused walkthrough using a representative BOM.")
    _footer("home")

def _hero_visual(kind: str) -> str:
    """Return a page-specific product story rather than a reused generic dashboard."""
    visuals = {
        "product": """
        <div class="mk-hero-visual"><div class="mk-visual-head"><span>Engineering Intelligence review</span><span class="mk-visual-chip">Decision ready</span></div><div class="mk-visual-grid"><div class="mk-visual-card"><span>Release posture</span><strong>HOLD</strong></div><div class="mk-visual-card"><span>Confidence</span><strong>91%</strong></div><div class="mk-visual-card"><span>Lifecycle risks</span><strong>7</strong></div><div class="mk-visual-card"><span>Supplier exposure</span><strong>6 parts</strong></div></div><div class="mk-visual-list"><div class="mk-visual-row"><span class="mk-visual-badge">AI</span><span><b>Priority recommendation</b><br>Replace MPU6050 before production release</span><span class="mk-visual-status risk">Act</span></div><div class="mk-visual-row"><span class="mk-visual-badge">ALT</span><span><b>Qualified replacement</b><br>ICM-42688-P · 94% confidence</span><span class="mk-visual-status">Review</span></div><div class="mk-visual-row"><span class="mk-visual-badge">SC</span><span><b>Supply-chain action</b><br>Qualify second source for LM35DN</span><span class="mk-visual-status warn">Qualify</span></div></div><div class="mk-visual-highlight"><div><b>Evidence-backed next action</b><span>Engineering, procurement, supply chain, and leadership review the same recommendation and supporting evidence.</span></div><span class="mk-visual-cta">Open review →</span></div></div>""",
        "solutions": """
        <div class="mk-hero-visual"><div class="mk-visual-head"><span>Industry portfolio intelligence</span><span class="mk-visual-chip">14 sectors</span></div><div class="mk-visual-grid"><div class="mk-visual-card"><span>Defense program</span><strong>82 health</strong></div><div class="mk-visual-card"><span>Medical platform</span><strong>89 health</strong></div><div class="mk-visual-card"><span>Robotics family</span><strong>11 actions</strong></div><div class="mk-visual-card"><span>Industrial controls</span><strong>4 alerts</strong></div></div><div class="mk-visual-list"><div class="mk-visual-row"><span class="mk-visual-badge">D</span><span><b>Defense electronics</b><br>Long-life obsolescence plan and traceable decisions</span><span class="mk-visual-status">Tracked</span></div><div class="mk-visual-row"><span class="mk-visual-badge">A</span><span><b>Automotive controller</b><br>Supplier continuity and qualification workflow</span><span class="mk-visual-status warn">Review</span></div><div class="mk-visual-row"><span class="mk-visual-badge">E</span><span><b>Energy system</b><br>Lifecycle and sourcing resilience review</span><span class="mk-visual-status">Ready</span></div></div><div class="mk-visual-highlight"><div><b>One platform across industries</b><span>Adapt the same evidence-driven workflow to regulated, high-reliability, commercial, academic, and startup hardware programs.</span></div><span class="mk-visual-cta">Explore sectors →</span></div></div>""",
        "pricing": """
        <div class="mk-hero-visual"><div class="mk-visual-head"><span>Professional team workspace</span><span class="mk-visual-chip">Full trial</span></div><div class="mk-visual-grid"><div class="mk-visual-card"><span>Approvals</span><strong>5 pending</strong></div><div class="mk-visual-card"><span>Decision records</span><strong>42</strong></div><div class="mk-visual-card"><span>API usage</span><strong>Active</strong></div><div class="mk-visual-card"><span>Monitored parts</span><strong>2,148</strong></div></div><div class="mk-visual-list"><div class="mk-visual-row"><span class="mk-visual-badge">✓</span><span><b>Engineering approval</b><br>Alternate qualification accepted</span><span class="mk-visual-status">Approved</span></div><div class="mk-visual-row"><span class="mk-visual-badge">API</span><span><b>ERP handoff</b><br>Decision record prepared for integration</span><span class="mk-visual-status">Ready</span></div><div class="mk-visual-row"><span class="mk-visual-badge">10</span><span><b>Team workspace</b><br>Engineering, sourcing, quality, and leadership</span><span class="mk-visual-status">Included</span></div></div><div class="mk-visual-highlight"><div><b>Evaluate the complete workflow</b><span>Use all core capabilities during the 14-day trial before selecting the right operating tier.</span></div><span class="mk-visual-cta">Start trial →</span></div></div>""",
        "resources": """
        <div class="mk-hero-visual"><div class="mk-visual-head"><span>Engineering knowledge center</span><span class="mk-visual-chip">Practical library</span></div><div class="mk-report-preview"><div class="mk-report-thumb"><i></i><i></i><i></i><i></i><i></i><i></i></div><div><div class="mk-visual-list"><div class="mk-visual-row"><span class="mk-visual-badge">PDF</span><span><b>Executive BOM report</b><br>Health, risks, actions, and release posture</span><span class="mk-visual-status">Sample</span></div><div class="mk-visual-row"><span class="mk-visual-badge">CSV</span><span><b>BOM template</b><br>Manufacturer part number and quantity format</span><span class="mk-visual-status">Template</span></div><div class="mk-visual-row"><span class="mk-visual-badge">KB</span><span><b>Lifecycle and sourcing guides</b><br>Practical review standards for teams</span><span class="mk-visual-status">Guide</span></div></div></div></div><div class="mk-visual-highlight"><div><b>Learn with working examples</b><span>Use guides, sample reports, demo BOMs, and templates to establish a repeatable review process.</span></div><span class="mk-visual-cta">Open library →</span></div></div>""",
        "company": """
        <div class="mk-hero-visual"><div class="mk-visual-head"><span>Cadivor mission roadmap</span><span class="mk-visual-chip">Engineering-first</span></div><div class="mk-visual-list"><div class="mk-visual-row"><span class="mk-visual-badge">1</span><span><b>Connect the evidence</b><br>Component, lifecycle, supplier, cost, and decision context</span><span class="mk-visual-status">Today</span></div><div class="mk-visual-row"><span class="mk-visual-badge">2</span><span><b>Standardize the workflow</b><br>Repeatable reviews across products and teams</span><span class="mk-visual-status">Launch</span></div><div class="mk-visual-row"><span class="mk-visual-badge">3</span><span><b>Predict engineering exposure</b><br>Portfolio intelligence and proactive recommendations</span><span class="mk-visual-status warn">Roadmap</span></div></div><div class="mk-visual-grid" style="margin-top:12px"><div class="mk-visual-card"><span>Teams aligned</span><strong>7 roles</strong></div><div class="mk-visual-card"><span>Core principle</span><strong>Evidence first</strong></div></div><div class="mk-visual-highlight"><div><b>Built for people who ship hardware</b><span>Cadivor exists to make engineering and supply-chain decisions faster, clearer, and more accountable.</span></div><span class="mk-visual-cta">Our mission →</span></div></div>""",
        "security": """
        <div class="mk-hero-visual"><div class="mk-visual-head"><span>Workspace security center</span><span class="mk-visual-chip">Controlled access</span></div><div class="mk-visual-grid"><div class="mk-visual-card"><span>Active sessions</span><strong>3</strong></div><div class="mk-visual-card"><span>Workspace members</span><strong>10</strong></div><div class="mk-visual-card"><span>Audit events</span><strong>248</strong></div><div class="mk-visual-card"><span>Access reviews</span><strong>Current</strong></div></div><div class="mk-visual-list"><div class="mk-visual-row"><span class="mk-visual-badge">S</span><span><b>Session management</b><br>Authenticated sessions and controlled account access</span><span class="mk-visual-status">Active</span></div><div class="mk-visual-row"><span class="mk-visual-badge">A</span><span><b>Audit trail</b><br>Engineering decisions and activity remain traceable</span><span class="mk-visual-status">Recorded</span></div><div class="mk-visual-row"><span class="mk-visual-badge">W</span><span><b>Workspace controls</b><br>Organization context and access policies</span><span class="mk-visual-status">Protected</span></div></div><div class="mk-visual-highlight"><div><b>Your engineering data stays yours</b><span>Cadivor uses BOM content to provide your private workspace and does not sell it as a data product.</span></div><span class="mk-visual-cta">Review controls →</span></div></div>""",
    }
    return visuals.get(kind, visuals["product"])




def _page_hero(active: str, kicker: str, title: str, copy: str) -> None:
    _nav(active)
    # Keep public-page hero rendering deterministic. Every current caller uses
    # the route-specific visual, so an optional override only created an
    # unnecessary runtime failure path on Streamlit Cloud.
    visual_markup = _hero_visual(
        active if active in {"product", "solutions", "pricing", "resources", "company", "security"} else "product"
    )
    _html(f"""
    <section class="mk-page-hero"><div class="mk-wide mk-page-hero-grid"><div><div class="mk-eyebrow"><i class="mk-eyebrow-dot"></i>{escape(kicker)}</div><h1>{escape(title)}</h1><p>{escape(copy)}</p><div class="mk-actions"><button type="button" class="mk-btn mk-btn-primary" data-cv-auth="signup">Start Free Trial</button><button type="button" class="mk-btn mk-btn-light" data-cv-public="contact">Book a Demo</button></div><div class="mk-proof"><span><b>✓</b>14-day full access</span><span><b>✓</b>No credit card</span><span><b>✓</b>CSV and Excel BOMs</span></div><div class="mk-page-outcomes"><span>Lifecycle risk</span><span>Supplier exposure</span><span>Alternatives</span><span>Decision records</span></div></div>{visual_markup}</div></section>
    """)


def _product() -> None:
    _page_hero("product", "Cadivor platform", "Engineering and supply-chain intelligence from BOM to production.", "Analyze lifecycle, inventory, supplier concentration, and supply-chain exposure; qualify alternatives; record decisions; and monitor risk in one connected workspace for engineering and procurement.")
    _html(f"""
    <div class="mk-subnav"><div class="mk-wrap mk-subnav-inner"><a href="#bom-analyzer" target="_self">BOM Analyzer</a><a href="#engineering-intelligence" target="_self">Engineering Intelligence</a><a href="#copilot" target="_self">Ask Cadivor</a><a href="#alternatives" target="_self">Alternative Finder</a><a href="#monitoring" target="_self">Monitoring</a><a href="#reports" target="_self">Reports</a></div></div>
    <section class="mk-section" id="bom-analyzer"><div class="mk-wrap mk-feature-split"><div class="mk-feature-copy"><div class="mk-kicker">BOM Analyzer</div><h2>Turn a parts list into an engineering review.</h2><p>Normalize CSV and Excel BOMs, evaluate lifecycle and sourcing exposure, and prioritize the components that deserve attention first.</p><div class="mk-check-list"><div class="mk-check"><b>✓</b><span>Lifecycle, inventory, supplier, and concentration analysis</span></div><div class="mk-check"><b>✓</b><span>Health scoring and release-oriented risk prioritization</span></div><div class="mk-check"><b>✓</b><span>Connected alternatives, monitoring, decisions, and reports</span></div></div></div><div class="mk-surface">{_dashboard_mockup()}</div></div></section>
    <section class="mk-section soft" id="engineering-intelligence"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Engineering Intelligence</div><h2>Move from alerts to engineering conclusions.</h2><p>Understand release posture, priority risks, confidence, evidence, and the best next action.</p></div><div class="mk-card-grid"><div class="mk-card"><div class="mk-icon">{_icon('decision')}</div><h3>Executive Decision Cockpit</h3><p>Summarizes release posture, confidence, evidence, and recommended actions.</p></div><div class="mk-card"><div class="mk-icon">{_icon('shield')}</div><h3>Risk prioritization</h3><p>Identifies which issue deserves attention first and why.</p></div><div class="mk-card"><div class="mk-icon">{_icon('audit')}</div><h3>Decision evidence</h3><p>Explains what supports a recommendation and what could change it.</p></div></div></div></section>
    <section class="mk-section" id="copilot"><div class="mk-wrap mk-feature-split"><div class="mk-surface"><div class="mk-cockpit"><div class="mk-cockpit-title">Ask Cadivor</div><div class="mk-recommendation" style="margin-top:0"><b>Question:</b> Is this BOM ready for production release?</div><div class="mk-recommendation"><b>Cadivor:</b> Not yet. Two components create unresolved lifecycle and single-source exposure. Qualify the proposed alternate for U14 and verify the manufacturer status for Q7 before release.</div><div class="mk-recommendation"><b>Follow-up:</b> What evidence would change this recommendation?</div></div></div><div class="mk-feature-copy"><div class="mk-kicker">Ask Cadivor</div><h2>Challenge the analysis in plain language.</h2><p>Ask context-aware questions about risk, suppliers, alternatives, production readiness, or the evidence needed to reach a different conclusion.</p></div></div></section>
    <section class="mk-section soft" id="alternatives"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Alternative Finder</div><h2>Shortlist replacements with engineering context.</h2><p>Compare lifecycle, supplier coverage, inventory, and compatibility considerations before qualification.</p></div></div></section>
    <section class="mk-section" id="monitoring"><div class="mk-wrap mk-feature-split"><div class="mk-feature-copy"><div class="mk-kicker">Monitoring</div><h2>Keep critical components under review.</h2><p>Track meaningful lifecycle, stock, and sourcing changes after the initial analysis.</p></div>{_hero_visual('solutions')}</div></section>
    <section class="mk-section soft" id="reports"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Reports and decisions</div><h2>Communicate engineering risk clearly.</h2><p>Export executive, lifecycle, and engineering decision records for cross-functional review.</p></div></div></section>
    """)
    _cta("Bring every BOM review into one connected workspace.", "Start with full platform access for 14 days.")
    _html("""
    <section class="mk-section"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Designed for complex hardware</div><h2>One product across industries, programs, and teams.</h2><p>Cadivor supports commercial, regulated, high-reliability, academic, and government hardware organizations without narrowing the workflow to a single sector.</p></div><div class="mk-industry-all-grid">
      <div class="mk-industry-pill"><strong>Aerospace</strong><span>Long-life platforms, qualification evidence, and obsolescence planning.</span></div><div class="mk-industry-pill"><strong>Defense</strong><span>Traceable engineering reviews for constrained and high-reliability electronics.</span></div><div class="mk-industry-pill"><strong>Medical devices</strong><span>Controlled component decisions and documented evidence.</span></div><div class="mk-industry-pill"><strong>Robotics</strong><span>Controller, sensing, power, and communications continuity.</span></div><div class="mk-industry-pill"><strong>Industrial automation</strong><span>Long product lifecycles and production continuity.</span></div><div class="mk-industry-pill"><strong>Automotive</strong><span>Supplier resilience, lifecycle review, and alternate qualification.</span></div><div class="mk-industry-pill"><strong>Energy</strong><span>Critical infrastructure electronics and sourcing durability.</span></div><div class="mk-industry-pill"><strong>Telecommunications</strong><span>Network hardware lifecycle and supplier exposure.</span></div><div class="mk-industry-pill"><strong>Consumer electronics</strong><span>Fast-moving inventory, cost, and redesign decisions.</span></div><div class="mk-industry-pill"><strong>Semiconductor equipment</strong><span>Specialized parts, long support windows, and replacement planning.</span></div><div class="mk-industry-pill"><strong>EMS & contract manufacturing</strong><span>Customer BOM review and sourcing readiness.</span></div><div class="mk-industry-pill"><strong>Universities & research</strong><span>Capstone, laboratory, and prototype decision workflows.</span></div><div class="mk-industry-pill"><strong>Hardware startups</strong><span>Build supply resilience before production scale.</span></div><div class="mk-industry-pill"><strong>Government programs</strong><span>Structured, accountable review for long-lived hardware.</span></div>
    </div></div></section>
    <section class="mk-section soft"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Built for the whole decision chain</div><h2>Shared intelligence for every team responsible for physical products.</h2></div><div class="mk-role-grid"><div class="mk-role-card"><strong>Engineering</strong><span>Prioritize technical risks, alternatives, and release decisions.</span></div><div class="mk-role-card"><strong>Procurement</strong><span>Qualify suppliers, compare sourcing options, and coordinate action.</span></div><div class="mk-role-card"><strong>Supply chain</strong><span>Track concentration, lead time, inventory, and continuity exposure.</span></div><div class="mk-role-card"><strong>Manufacturing</strong><span>Understand production readiness and component disruption.</span></div><div class="mk-role-card"><strong>Quality & compliance</strong><span>Preserve evidence, rationale, and review history.</span></div><div class="mk-role-card"><strong>Program management</strong><span>See schedule-impacting decisions and open actions.</span></div><div class="mk-role-card"><strong>Executive leadership</strong><span>Review health, cost exposure, and release posture quickly.</span></div><div class="mk-role-card"><strong>Sustaining engineering</strong><span>Manage obsolescence and redesign across long-lived products.</span></div></div></div></section>
    """)
    _footer()


def _solutions() -> None:
    _page_hero("solutions", "Industry solutions", "Engineering and supply-chain intelligence for teams that build physical products.", "Cadivor helps engineering, procurement, and supply-chain teams identify component exposure earlier, coordinate cross-functional reviews, and make more defensible release decisions.")
    _html("""
    <section class="mk-section soft"><div class="mk-wrap"><div class="mk-industry-grid">
      <article class="mk-industry" id="robotics"><div class="mk-kicker">Robotics</div><h3>Protect long-lived robotic platforms from component disruption.</h3><p>Review controller, sensing, communications, and power-system BOMs before fragile components become field problems.</p></article>
      <article class="mk-industry" id="medical"><div class="mk-kicker">Medical devices</div><h3>Support controlled design decisions with clearer evidence.</h3><p>Connect lifecycle, supplier, and alternate-part evidence to disciplined engineering review.</p></article>
      <article class="mk-industry" id="industrial"><div class="mk-kicker">Industrial automation</div><h3>Maintain production continuity across long product lifecycles.</h3><p>Find exposure in PLC, I/O, drive, and controller BOMs before it reaches manufacturing.</p></article>
      <article class="mk-industry" id="hardware-startups"><div class="mk-kicker">Hardware startups</div><h3>Build supply resilience before scaling production.</h3><p>Identify fragile sourcing, lifecycle, and alternate-part decisions while redesign is still affordable.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Aerospace and defense</div><h3>Improve visibility into constrained and long-life electronics.</h3><p>Support obsolescence review, supplier exposure analysis, and alternate qualification planning.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Hardware startups</div><h3>Build supply resilience before scale.</h3><p>Find avoidable lifecycle and sourcing risks while changes are still inexpensive.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Universities and research</div><h3>Teach engineering decisions with real component evidence.</h3><p>Help capstone and research teams understand lifecycle and sourcing tradeoffs.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Automotive</div><h3>Coordinate sourcing resilience across production programs.</h3><p>Track supplier continuity, lifecycle changes, and alternate qualification before they affect vehicle schedules.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Energy</div><h3>Protect critical infrastructure electronics.</h3><p>Manage long-life controllers, power electronics, and field-service component exposure.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Telecommunications</div><h3>Keep network hardware supportable.</h3><p>Review specialized components, lead times, and lifecycle changes across deployed systems.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Consumer electronics</div><h3>Move quickly without losing sourcing discipline.</h3><p>Balance cost, inventory, alternative options, and rapid product-cycle decisions.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Semiconductor equipment</div><h3>Manage specialized long-life BOMs.</h3><p>Plan replacements for constrained components in complex capital equipment.</p></article>
      <article class="mk-industry"><div class="mk-kicker">EMS & contract manufacturing</div><h3>Review customer BOM readiness at scale.</h3><p>Surface sourcing, lifecycle, and qualification issues before production commitments.</p></article>
      <article class="mk-industry"><div class="mk-kicker">Government programs</div><h3>Support accountable long-term hardware decisions.</h3><p>Maintain evidence and action history across long-lived public-sector programs.</p></article>
    </div></div></section>
    """)
    _cta("See how Cadivor fits your engineering workflow.", "Book a focused product walkthrough using a representative BOM.")
    _footer()


def _pricing() -> None:
    _page_hero("pricing", "Transparent pricing", "Start with full access. Scale when the workflow proves its value.", "Every new workspace receives a 14-day full-access trial with no feature restrictions. After the trial, upgrade or automatically continue on Starter.")
    _html("""
    <section class="mk-section"><div class="mk-wrap"><div class="mk-pricing">
      <div class="mk-price-card"><span class="mk-plan-label">Academic adoption</span><div class="mk-price-name">Student</div><div class="mk-price">$0</div><p>For university students, engineering clubs, and capstone teams.</p><ul><li>3 BOM analyses/month</li><li>25 components/BOM</li><li>Basic risk analysis and health score</li><li>Limited alternative search</li><li>Student Edition PDF watermark</li><li>Community support</li></ul><a class="mk-btn mk-btn-light" href="#" aria-disabled="true">Coming Soon</a></div>
      <div class="mk-price-card"><span class="mk-plan-label">Individual use</span><div class="mk-price-name">Starter</div><div class="mk-price">$29<small>/month</small></div><p>For hobbyists, freelancers, makers, and prototype companies.</p><ul><li>10 BOM analyses/month</li><li>100 components/BOM</li><li>Basic reports and alternatives</li><li>PDF export</li><li>Email support</li><li>No monitoring or AI assistant</li></ul><button type="button" class="mk-btn mk-btn-light" data-cv-auth="signup">Start Free Trial</button></div>
      <div class="mk-price-card featured"><div class="mk-popular">Most popular</div><span class="mk-plan-label">Best value for professional teams</span><div class="mk-price-name">Professional</div><div class="mk-price">$99<small>/month</small></div><p>For professional engineers, hardware startups, procurement leads, and small engineering companies.</p><ul><li>Unlimited BOM analyses and components</li><li>Advanced AI recommendations</li><li>Engineering Decision Records</li><li>Supplier intelligence and advanced reports</li><li>2,500 monitored components</li><li>Priority email support</li></ul><button type="button" class="mk-btn mk-btn-primary" data-cv-auth="signup">Start Free Trial</button></div>
      <div class="mk-price-card"><span class="mk-plan-label">Best for teams</span><div class="mk-price-name">Business</div><div class="mk-price">$299<small>/month</small></div><p>For growing companies and engineering organizations.</p><ul><li>Everything in Professional</li><li>10 users included</li><li>Role-based approvals and shared BOM library</li><li>Unlimited monitoring</li><li>API, webhooks, audit logs, comments</li><li>Advanced analytics and priority support</li></ul><button type="button" class="mk-btn mk-btn-light" data-cv-auth="signup">Start Free Trial</button></div>
      <div class="mk-price-card enterprise"><span class="mk-plan-label">Organization-wide</span><div class="mk-price-name">Enterprise</div><div class="mk-price">Custom</div><p>Flexible deployment, integrations, security, support, and commercial terms tailored to your organization.</p><ul><li>Unlimited users, API, and monitoring</li><li>SSO, priority SLA, dedicated success manager</li><li>ERP and PLM integrations</li><li>Custom integrations and AI models</li><li>Training and migration assistance</li><li>On-premises option planned</li></ul><button type="button" class="mk-btn mk-btn-light" data-cv-public="contact">Contact Sales</button></div>
    </div></div></section>
    <section class="mk-section soft"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Feature comparison</div><h2>Choose the level that matches your review process.</h2></div><div class="mk-table-wrap"><table class="mk-compare"><thead><tr><th>Feature</th><th>Student</th><th>Starter</th><th>Professional</th><th>Business</th><th>Enterprise</th></tr></thead><tbody>
    <tr><td>BOM analysis</td><td>3/month</td><td>10/month</td><td class="mk-yes">Unlimited</td><td class="mk-yes">Unlimited</td><td class="mk-yes">Unlimited</td></tr>
    <tr><td>Components/BOM</td><td>25</td><td>100</td><td class="mk-yes">Unlimited</td><td class="mk-yes">Unlimited</td><td class="mk-yes">Unlimited</td></tr>
    <tr><td>Alternative search</td><td>Limited</td><td>Basic</td><td>Advanced</td><td>Advanced</td><td>Advanced</td></tr>
    <tr><td>AI recommendations</td><td>—</td><td>—</td><td class="mk-yes">Included</td><td class="mk-yes">Included</td><td class="mk-yes">Included</td></tr>
    <tr><td>BOM monitoring</td><td>—</td><td>—</td><td>2,500 parts</td><td class="mk-yes">Unlimited</td><td class="mk-yes">Unlimited</td></tr>
    <tr><td>Decision records</td><td>—</td><td>—</td><td class="mk-yes">Included</td><td class="mk-yes">Included</td><td class="mk-yes">Included</td></tr>
    <tr><td>Team collaboration</td><td>—</td><td>—</td><td>—</td><td class="mk-yes">Included</td><td class="mk-yes">Included</td></tr>
    <tr><td>API access</td><td>—</td><td>—</td><td>—</td><td class="mk-yes">Included</td><td class="mk-yes">Unlimited</td></tr>
    <tr><td>SSO</td><td>—</td><td>—</td><td>—</td><td>—</td><td class="mk-yes">Included</td></tr>
    <tr><td>Custom integrations</td><td>—</td><td>—</td><td>—</td><td>Limited</td><td class="mk-yes">Included</td></tr>
    <tr><td>Support</td><td>Community</td><td>Email</td><td>Priority</td><td>Priority</td><td>Dedicated</td></tr>
    </tbody></table></div></div></section>
    <section class="mk-section"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Free trial</div><h2>Evaluate the complete Cadivor workflow.</h2><p>For 14 days, every workspace receives full access with no artificial feature restrictions. No credit card is required.</p></div></div></section>
    """)
    _footer()


def _resources() -> None:
    _page_hero("resources", "Engineering resources", "Build a stronger BOM review practice.", "Use Cadivor guides, demo BOMs, templates, and technical explanations to standardize how your team reviews component risk and engineering decisions.")
    _html("""
    <section class="mk-section soft"><div class="mk-wrap"><div class="mk-resource-grid">
      <article class="mk-resource" id="getting-started"><div class="mk-resource-type">Getting started</div><h3>Your first Cadivor analysis</h3><p>Prepare a BOM, upload it, understand the health score, review priority risks, and export a decision-ready report.</p><a href="#" aria-disabled="true">Coming Soon</a></article>
      <article class="mk-resource" id="demo-boms"><div class="mk-resource-type">Template</div><h3>BOM formatting guide</h3><p>Use clean manufacturer part numbers and quantities in supported CSV or Excel files.</p><a href="#" aria-disabled="true">Coming Soon</a></article>
      <article class="mk-resource" id="engineering-guides"><div class="mk-resource-type">Engineering guide</div><h3>Lifecycle exposure</h3><p>Understand Active, NRND, EOL, obsolete, and unknown lifecycle signals.</p><button type="button" data-cv-public="contact">Request the guide →</button></article>
      <article class="mk-resource"><div class="mk-resource-type">Engineering guide</div><h3>Single-source risk</h3><p>Learn when supplier concentration becomes an engineering concern.</p><button type="button" data-cv-public="contact">Request the guide →</button></article>
      <article class="mk-resource"><div class="mk-resource-type">Demo BOM</div><h3>Industrial controller example</h3><p>Explore lifecycle issues, sourcing concentration, alternatives, and release recommendations.</p><a href="#" aria-disabled="true">Coming Soon</a></article>
      <article class="mk-resource"><div class="mk-resource-type">Release notes</div><h3>Cadivor launch edition</h3><p>Review Engineering Intelligence, Ask Cadivor, Decision Cockpit, reports, and monitoring.</p><button type="button" data-cv-public="product">Review the platform →</button></article>
    </div></div></section>
    <section class="mk-section" id="faq"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">FAQ</div><h2>Common questions before your first analysis.</h2></div><div class="mk-card-grid"><div class="mk-card"><h3>What files can I upload?</h3><p>Cadivor supports structured CSV and Excel BOMs with manufacturer part numbers and quantities.</p></div><div class="mk-card"><h3>Does Cadivor replace engineering validation?</h3><p>No. Cadivor organizes decision evidence and recommendations; your team retains final qualification and release authority.</p></div><div class="mk-card"><h3>Can I evaluate the full workflow?</h3><p>Yes. The 14-day trial is designed to let teams test analysis, alternatives, monitoring, decisions, and reports.</p></div></div></div></section>
    """)
    _cta("Start with a real BOM and see what Cadivor surfaces.", "Create a workspace and run your first analysis in minutes.")
    _footer()


def _company() -> None:
    _page_hero("company", "About Cadivor", "Hardware teams deserve better decision infrastructure.", "Cadivor replaces fragmented BOM review with a connected engineering intelligence workflow built around evidence, priorities, and action.")
    _html("""
    <section class="mk-section" id="about"><div class="mk-wrap mk-feature-split"><div class="mk-feature-copy"><div class="mk-kicker">Mission</div><h2>Help engineering teams make better decisions before problems reach production.</h2><p>Cadivor turns fragmented supplier pages, spreadsheets, lifecycle signals, alternatives, and review notes into one repeatable workflow.</p></div><div class="mk-surface"><div class="mk-card" style="box-shadow:none"><div class="mk-icon">C</div><h3>Our core promise</h3><p>Upload a BOM. Understand the risks. See what matters. Decide what to do next.</p></div></div></div></section>
    """)
    _cta("Help shape the future of engineering intelligence.", "Join the launch program and evaluate Cadivor on a real BOM.")
    _footer()


def _contact() -> None:
    _page_hero("company", "Contact Cadivor", "Start a practical conversation about your BOM review workflow.", "Use the contact options below for product demos, beta participation, commercial questions, support, or partnership discussions.")
    _html("""
    <section class="mk-section soft"><div class="mk-wrap"><div class="mk-card-grid"><div class="mk-card"><div class="mk-icon">▶</div><h3>Book a product demo</h3><p>Walk through BOM analysis, Engineering Intelligence, Ask Cadivor, alternatives, monitoring, and reports using a representative workflow.</p><a href="mailto:info@cadivor.com?subject=Cadivor%20Demo%20Request">info@cadivor.com →</a></div><div class="mk-card"><div class="mk-icon">β</div><h3>Join the beta program</h3><p>Evaluate Cadivor with a real engineering team and provide feedback that directly influences launch priorities.</p><a href="mailto:info@cadivor.com?subject=Cadivor%20Beta%20Program">Request beta access →</a></div><div class="mk-card"><div class="mk-icon">?</div><h3>Product and support</h3><p>Ask a question about accounts, BOM formatting, plan entitlements, reports, or the engineering workflow.</p><a href="mailto:info@cadivor.com?subject=Cadivor%20Product%20Question">Contact support →</a></div></div></div></section>
    <section class="mk-section"><div class="mk-wrap"><div class="mk-heading"><div class="mk-kicker">Prepare for a productive demo</div><h2>Bring one representative workflow.</h2><p>A useful conversation starts with the BOM you review, the lifecycle and supply-chain risks you track, the engineering and procurement teams involved, and the decision output you need.</p></div><div class="mk-steps four"><div class="mk-step"><div class="mk-step-num">1</div><h3>Choose a BOM</h3><p>Select a representative prototype, production, redesign, or sustaining-engineering BOM.</p></div><div class="mk-step"><div class="mk-step-num">2</div><h3>Identify the decision</h3><p>Define what the team needs to approve, qualify, replace, or monitor.</p></div><div class="mk-step"><div class="mk-step-num">3</div><h3>Map the workflow</h3><p>Note who reviews component, supplier, procurement, and production evidence.</p></div><div class="mk-step"><div class="mk-step-num">4</div><h3>Evaluate the result</h3><p>Compare Cadivor's output with your existing review process.</p></div></div></div></section>
    """)
    _footer()


def _legal_page(kind: str) -> None:
    titles = {
        "security": ("Security", "Upload your BOM with confidence.", "Cadivor is designed to keep engineering workspaces controlled, private, and accountable while supporting secure cloud operation."),
        "privacy": ("Privacy Policy", "How Cadivor handles account and product data.", "This pre-launch policy describes the information Cadivor processes to provide, secure, support, and improve the service."),
        "terms": ("Terms of Service", "The conditions for using Cadivor.", "Cadivor is an engineering decision-support platform. Final production, procurement, qualification, and regulatory decisions remain with the customer."),
    }
    title, heading, copy = titles[kind]
    _page_hero("security" if kind == "security" else "company", title, heading, copy)
    if kind == "security":
        body = f"""
        <section class="mk-section"><div class="mk-wrap"><div class="mk-security-banner"><div><h2>Your engineering data stays yours.</h2><p>Cadivor uses uploaded BOM content to provide your analysis and workspace. It is not sold as a data product. Access is tied to authenticated accounts and workspace controls.</p></div><div class="mk-security-points"><div class="mk-security-point"><b>✓</b><span>Encrypted transport for browser-to-service communication</span></div><div class="mk-security-point"><b>✓</b><span>Authenticated access and session controls</span></div><div class="mk-security-point"><b>✓</b><span>Workspace-separated application data</span></div><div class="mk-security-point"><b>✓</b><span>Auditable engineering decisions and activity history</span></div></div></div><div class="mk-card-grid"><div class="mk-card"><div class="mk-icon">{_icon('shield')}</div><h3>Controlled access</h3><p>Managed authentication and session controls help protect access to customer workspaces.</p></div><div class="mk-card"><div class="mk-icon">{_icon('layers')}</div><h3>Workspace separation</h3><p>Application data is associated with authenticated user and organization contexts and supported by database access policies.</p></div><div class="mk-card"><div class="mk-icon">{_icon('brain')}</div><h3>Responsible AI</h3><p>AI assists review and explanation. Your team remains responsible for engineering validation and final decisions.</p></div></div><div class="mk-faq" style="margin-top:28px"><div class="mk-faq-item"><strong>Can Cadivor use my BOM to train public models?</strong><p>Cadivor does not present customer BOMs as public training data. Final contractual language and subprocessor terms will be documented before commercial launch.</p></div><div class="mk-faq-item"><strong>Should I upload regulated or export-controlled data?</strong><p>Only upload information you are authorized to process. Export-controlled, regulated, or highly sensitive programs require an appropriate contractual and security review before use.</p></div><div class="mk-faq-item"><strong>How do I ask a security question?</strong><p>Send security and responsible-disclosure inquiries to info@cadivor.com with “Security” in the subject line.</p></div></div></div></section>"""
    elif kind == "privacy":
        body = """<section class="mk-section"><div class="mk-wrap"><div class="mk-feature-copy"><h2>Pre-launch privacy notice</h2><p>Cadivor may process account information, authentication data, uploaded BOM content, analysis results, reports, usage records, support communications, billing status, and technical logs necessary to operate the service.</p><p><em>This draft requires qualified legal review before commercial launch.</em></p></div></div></section>"""
    else:
        body = """<section class="mk-section"><div class="mk-wrap"><div class="mk-legal">
        <div class="mk-legal-meta"><strong>Cadivor Terms of Service</strong><span>Pre-launch version</span><span>Last updated: July 25, 2026</span></div>
        <p>These Terms of Service govern access to and use of Cadivor. By creating an account, checking the acceptance box during registration, or using Cadivor, you agree to these Terms and the Privacy Policy.</p>
        <h2>1. Decision-support service</h2>
        <p>Cadivor provides software-based component lifecycle, sourcing, supplier, inventory, risk, alternative-part, reporting, monitoring, and AI-assisted engineering intelligence for informational and decision-support purposes.</p>
        <p>Cadivor does not replace professional engineering judgment, datasheet review, supplier confirmation, qualification testing, procurement review, regulatory review, manufacturing review, or production-release approval. You remain responsible for validating outputs before relying on them in a design, sourcing, procurement, compliance, manufacturing, or production workflow.</p>
        <h2>2. Accounts and authorized use</h2>
        <p>You are responsible for maintaining accurate account information, protecting account credentials, and ensuring that people using your workspace are authorized to do so. You may not misuse the service, interfere with its operation, attempt unauthorized access, or use Cadivor for unlawful activity.</p>
        <h2>3. Customer data and BOM ownership</h2>
        <p>You retain ownership of BOMs and other content you upload. You grant Cadivor permission to process that content only as reasonably necessary to provide analysis, reporting, monitoring, account administration, support, security, service reliability, and product operation.</p>
        <p>You must not upload unlawful data or confidential third-party, export-controlled, restricted, regulated, or highly sensitive information unless you have the legal right and appropriate authorization to process it through the service.</p>
        <h2>4. Supplier data and recommendations</h2>
        <p>Cadivor may use distributor APIs, supplier records, public sources, third-party data, software rules, and AI-assisted analysis. Availability, lifecycle status, pricing, stock, lead times, risk scores, compatibility assessments, and alternative recommendations may be incomplete, delayed, inaccurate, or unsuitable for a particular design.</p>
        <p>You are responsible for confirming component specifications, fit, form, function, regulatory status, sourcing terms, and supplier information before purchasing, qualifying, or releasing a component.</p>
        <h2>5. Plans, trials, billing, and changes</h2>
        <p>Plan features and usage limits are described on the Pricing page and may vary by subscription. Trial access may automatically continue on the Starter plan unless the customer upgrades or cancels as described during registration. Paid subscriptions, renewal, taxes, refunds, and cancellation terms will be presented during checkout and in the final commercial agreement.</p>
        <h2>6. Availability and service changes</h2>
        <p>Cadivor may modify features, integrations, limits, or availability to improve the service, address security or legal requirements, or respond to third-party service changes. We will use reasonable efforts to communicate material changes that affect paid customers.</p>
        <h2>7. Suspension and termination</h2>
        <p>Cadivor may suspend or terminate access for abuse, misuse, nonpayment, security risk, violation of these Terms, or activity that may harm the service or other users. Customers may stop using the service and cancel eligible subscriptions through the available account or billing process.</p>
        <h2>8. Disclaimers</h2>
        <p>To the extent permitted by law, Cadivor is provided “as is” and “as available.” Cadivor does not warrant uninterrupted availability, complete accuracy, merchantability, non-infringement, or fitness for a particular purpose.</p>
        <h2>9. Limitation of liability</h2>
        <p>To the maximum extent permitted by law, Cadivor and its owners, officers, employees, contractors, suppliers, service providers, and affiliates will not be liable for indirect, incidental, consequential, special, punitive, procurement, production, recall, lost-profit, lost-data, business-interruption, design-failure, regulatory, or manufacturing damages arising from use of the service.</p>
        <h2>10. Contact</h2>
        <p>Questions about these Terms may be sent to <strong>info@cadivor.com</strong> with “Terms” in the subject line.</p>
        <div class="mk-legal-note"><strong>Legal review required before commercial launch.</strong><p>This version is aligned with the terms shown during account creation, but the final document should be reviewed by qualified counsel and completed with Cadivor’s legal entity name, business address, governing law, payment and refund terms, dispute process, and any enterprise-specific provisions.</p></div>
        </div></div></section>"""
    _html(body)
    _footer()




def _sprint63_marketing_polish() -> None:
    """Apply the final public-site design system without changing routing or auth."""
    st.markdown(
        """
        <style id="cadivor-sprint-63-marketing-polish">
        :root{
          --mk-space-1:8px;--mk-space-2:12px;--mk-space-3:16px;--mk-space-4:24px;
          --mk-space-5:32px;--mk-space-6:48px;--mk-space-7:72px;--mk-space-8:96px;
          --mk-radius-sm:10px;--mk-radius-md:16px;--mk-radius-lg:22px;
          --mk-ease:cubic-bezier(.2,.8,.2,1);
          --mk-card-shadow:0 14px 42px rgba(12,31,64,.07);
          --mk-card-shadow-hover:0 22px 55px rgba(12,31,64,.11);
        }
        .mk-shell{font-size:16px;line-height:1.65;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased}
        .mk-wrap{width:min(1200px,calc(100% - 48px))}.mk-wide{width:min(1360px,calc(100% - 48px))}
        .mk-section{padding:var(--mk-space-8) 0!important}.mk-section.compact{padding:var(--mk-space-7) 0!important}
        .mk-heading{max-width:760px;margin:0 auto var(--mk-space-6)!important}.mk-heading h2,.mk-feature-copy h2{font-size:clamp(34px,3.35vw,46px)!important;line-height:1.1!important;letter-spacing:-.04em!important;margin:0 0 16px!important}.mk-heading p,.mk-feature-copy>p{font-size:17px!important;line-height:1.75!important}
        .mk-page-hero{padding:92px 0 88px!important}.mk-page-hero h1{font-size:clamp(44px,4.7vw,66px)!important;line-height:1.03!important;letter-spacing:-.052em!important}.mk-page-hero p{max-width:680px;font-size:18px!important;line-height:1.72!important}
        .mk-hero{padding:100px 0 92px!important}.mk-hero h1{line-height:1.02!important;letter-spacing:-.055em!important}.mk-hero-copy{font-size:18px!important;line-height:1.72!important}
        .mk-card,.mk-industry,.mk-resource,.mk-price-card,.mk-story-card,.mk-role-card,.mk-industry-pill,.mk-flow-node,.mk-faq-item{border-radius:var(--mk-radius-md)!important;box-shadow:var(--mk-card-shadow)!important;transition:transform 180ms var(--mk-ease),box-shadow 180ms var(--mk-ease),border-color 180ms var(--mk-ease)!important}
        .mk-card,.mk-industry,.mk-resource,.mk-price-card{padding:30px!important}.mk-card h3,.mk-industry h3,.mk-resource h3{margin:17px 0 9px!important;line-height:1.3!important}.mk-card p,.mk-industry p,.mk-resource p,.mk-price-card p,.mk-price-card li{line-height:1.7!important}
        @media(hover:hover){.mk-card:hover,.mk-industry:hover,.mk-resource:hover,.mk-role-card:hover,.mk-industry-pill:hover{transform:translateY(-2px);box-shadow:var(--mk-card-shadow-hover)!important;border-color:#c7d8ee!important}.mk-btn:hover{transform:translateY(-1px);filter:brightness(1.02)}}
        .mk-btn{min-height:44px!important;padding:0 19px!important;border-radius:9px!important;transition:transform 160ms var(--mk-ease),box-shadow 160ms var(--mk-ease),background 160ms var(--mk-ease)!important}.mk-btn:focus-visible{outline:3px solid rgba(117,167,255,.42)!important;outline-offset:3px!important}
        .mk-nav{height:74px!important}.mk-links{gap:25px!important}.mk-nav-actions{gap:11px!important}
        .st-key-cv_public_nav button{min-height:40px!important;border-radius:8px!important;transition:background 150ms var(--mk-ease),color 150ms var(--mk-ease),border-color 150ms var(--mk-ease)!important}.st-key-cv_public_nav button:focus-visible{outline:2px solid #75a7ff!important;outline-offset:2px!important}
        .mk-cta{border-radius:var(--mk-radius-lg)!important;padding:42px 46px!important}.mk-cta h2{font-size:clamp(28px,3vw,38px)!important}.mk-cta p{font-size:15px!important;line-height:1.65!important}
        .mk-footer{padding-top:64px!important}.st-key-cv_native_footer{padding-top:60px!important;padding-bottom:26px!important}
        .st-key-cv_native_footer [data-testid="stHorizontalBlock"]{gap:40px!important;align-items:flex-start!important}
        .st-key-cv_native_footer [data-testid="column"]{min-width:0!important}
        .st-key-cv_native_footer .cv-footer-heading{height:auto!important;min-height:28px!important;margin:0 0 10px!important;align-items:flex-start!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"]{min-height:34px!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button{min-height:34px!important;padding:6px 0!important;font-size:13px!important;line-height:1.42!important;letter-spacing:0!important;align-items:flex-start!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button p{margin:0!important;text-align:left!important;line-height:1.42!important}
        .st-key-cv_native_footer div[class*="st-key-cv_footer_"] button[kind="primary"]::after{left:0!important;bottom:2px!important;width:18px!important;height:2px!important}
        .st-key-cv_native_footer .cv-footer-coverage span{height:34px!important;align-items:flex-start!important;padding-top:6px!important;line-height:1.42!important}
        .st-key-cv_native_footer .cv-footer-bottom{margin-top:40px!important;padding-top:20px!important;line-height:1.55!important}
        .mk-footer-col a,.mk-footer-col button{transition:color 150ms var(--mk-ease)!important}
        @media(max-width:1100px){.mk-section{padding:78px 0!important}.mk-page-hero{padding:78px 0 72px!important}}
        @media(max-width:820px){.mk-wrap,.mk-wide{width:min(100% - 34px,1200px)}.mk-section{padding:66px 0!important}.mk-page-hero,.mk-hero{padding:70px 0 64px!important}.mk-heading{margin-bottom:38px!important}.mk-cta{padding:32px!important}.st-key-cv_native_footer{padding-left:20px!important;padding-right:20px!important}.st-key-cv_native_footer [data-testid="stHorizontalBlock"]{gap:28px!important}}
        @media(max-width:560px){.mk-section{padding:56px 0!important}.mk-page-hero h1{font-size:40px!important}.mk-heading h2,.mk-feature-copy h2{font-size:32px!important}.mk-hero-copy,.mk-page-hero p{font-size:16px!important}.mk-card,.mk-industry,.mk-resource,.mk-price-card{padding:24px!important}.mk-cta{padding:28px 24px!important}.st-key-cv_native_footer [data-testid="column"]{min-width:100%!important;flex-basis:100%!important}}
        /* Sprint 63.1 — Launch-ready product story */
        .mk-launch-hero{padding:88px 0 80px!important}.mk-launch-hero-grid{display:grid;grid-template-columns:minmax(390px,.78fr) minmax(650px,1.22fr);gap:58px;align-items:center}.mk-launch-copy h1{font-size:clamp(48px,5.1vw,72px)!important;line-height:1.02!important;margin:18px 0 24px!important}.mk-launch-actions .mk-scroll-cta{border-color:rgba(255,255,255,.32);color:#fff!important}.mk-demo-stage{min-width:0}.mk-demo-frame{position:relative;border:1px solid rgba(154,186,238,.28);border-radius:20px;background:#f7f9fc;box-shadow:0 38px 90px rgba(0,10,32,.42);overflow:hidden}.mk-demo-toolbar{height:44px;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;padding:0 14px;background:#fff;border-bottom:1px solid #dce5f0;color:#65758b;font-size:10px;font-weight:750}.mk-demo-toolbar em{font-style:normal;color:#2f6df6}.mk-demo-dots{display:flex;gap:5px}.mk-demo-dots i{width:8px;height:8px;border-radius:50%;background:#cbd5e1}.mk-demo-layout{display:grid;grid-template-columns:138px 1fr;min-height:430px}.mk-demo-layout aside{display:flex;flex-direction:column;gap:5px;padding:18px 12px;background:#081a36;color:#91a4bf;font-size:9px}.mk-demo-layout aside strong{color:#fff;font-size:11px;letter-spacing:.11em;margin-bottom:15px}.mk-demo-layout aside span{padding:8px;border-radius:6px}.mk-demo-layout aside span.active{background:#173e78;color:#fff}.mk-demo-content{padding:20px;min-width:0}.mk-demo-head{display:flex;justify-content:space-between;align-items:center;gap:15px}.mk-demo-head small{font-size:8px;color:#64748b;font-weight:800;letter-spacing:.1em}.mk-demo-head h3{margin:3px 0 0;font-size:18px;color:#0b1730!important}.mk-release-hold{padding:6px 9px;border-radius:999px;background:#fff0f0;color:#c9363e;font-size:8px;font-weight:900}.mk-demo-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:16px 0}.mk-demo-kpis>div{padding:12px;border:1px solid #e0e7f0;border-radius:10px;background:#fff}.mk-demo-kpis small,.mk-demo-kpis span{display:block;color:#718096;font-size:8px}.mk-demo-kpis strong{display:block;margin:3px 0;font-size:19px;color:#13223b}.mk-demo-kpis .red{color:#d34248}.mk-demo-kpis .amber{color:#b87913}.mk-demo-kpis .green{color:#168654}.mk-demo-bottom{display:grid;grid-template-columns:1fr 1fr;gap:10px}.mk-risk-panel,.mk-demo-recommendation{padding:14px;border:1px solid #e0e7f0;border-radius:11px;background:#fff}.mk-demo-title{font-size:9px;font-weight:900;color:#31445e;margin-bottom:10px}.mk-risk-line{display:grid;grid-template-columns:.8fr 1.4fr auto;gap:6px;align-items:center;padding:8px 0;border-top:1px solid #edf1f6;font-size:8px;color:#68788d}.mk-risk-line b{color:#15243d}.mk-risk-line em{font-style:normal;font-weight:800;color:#b33a40}.mk-demo-recommendation{background:#0d2853;color:#dce9ff}.mk-demo-recommendation strong{display:block;color:#fff;font-size:12px}.mk-demo-recommendation p{font-size:9px;line-height:1.55;color:#b9cbea!important}.mk-demo-recommendation span{font-size:8px;color:#81abff}.mk-media-slot{display:none;position:absolute;inset:44px 0 0;background:#071a35;color:#cfe0ff;place-items:center;font-size:14px}.mk-demo-frame.has-media .mk-media-slot{display:grid}.mk-workflow-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.mk-workflow-grid article{position:relative;padding:28px 24px;border:1px solid #dce5f0;border-radius:17px;background:#fff;box-shadow:0 15px 38px rgba(15,23,42,.065)}.mk-workflow-grid article:not(:last-child)::after{content:'→';position:absolute;right:-19px;top:50%;z-index:3;width:36px;height:36px;display:grid;place-items:center;transform:translateY(-50%);border-radius:50%;background:#2563eb;color:#fff;font-weight:900}.mk-workflow-grid article>span{font-size:11px;font-weight:900;color:#2f6df6;letter-spacing:.1em}.mk-workflow-grid h3{font-size:20px;margin:16px 0 8px}.mk-workflow-grid p{font-size:14px;line-height:1.65;color:#5c6d82!important}.mk-intelligence-layout,.mk-copilot-layout,.mk-decision-story{display:grid;grid-template-columns:.82fr 1.18fr;gap:64px;align-items:center}.mk-metric-showcase{display:grid;grid-template-columns:repeat(2,1fr);gap:13px}.mk-metric-showcase>div{padding:23px;border:1px solid #dce5f0;border-radius:15px;background:#fff}.mk-metric-showcase small,.mk-metric-showcase span{display:block;color:#6b7c91}.mk-metric-showcase small{font-size:12px;font-weight:800}.mk-metric-showcase strong{display:block;margin:7px 0 5px;font-size:28px;color:#102344}.mk-metric-showcase span{font-size:12px}.mk-check-list{list-style:none;padding:0;margin:24px 0}.mk-check-list li{position:relative;padding:7px 0 7px 28px;color:#52657b}.mk-check-list li::before{content:'✓';position:absolute;left:0;color:#1b9a62;font-weight:900}.mk-text-action,.mk-card button,.mk-message button{padding:0;border:0;background:transparent;color:#235fd8;font-weight:800;cursor:pointer}.mk-copilot-layout{grid-template-columns:1.18fr .82fr}.mk-copilot-window{border:1px solid #d6e1ef;border-radius:18px;background:#f7f9fc;box-shadow:0 24px 65px rgba(15,23,42,.1);overflow:hidden}.mk-copilot-top{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;background:#0b2147;color:#fff;font-size:12px;font-weight:800}.mk-copilot-top svg{width:17px;vertical-align:middle;fill:none;stroke:currentColor;stroke-width:1.7}.mk-copilot-top em{font-size:10px;font-style:normal;color:#9db8df}.mk-message{margin:16px;padding:15px 17px;border-radius:13px;max-width:84%}.mk-message small{display:block;margin-bottom:4px;font-size:10px;font-weight:900}.mk-message p{margin:0;color:inherit!important;font-size:14px;line-height:1.62}.mk-message.user{margin-left:auto;background:#2563eb;color:#fff}.mk-message.assistant{background:#fff;border:1px solid #dce5f0;color:#263a55}.mk-evidence-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}.mk-evidence-chips span{padding:5px 7px;border-radius:999px;background:#edf3ff;color:#315fba;font-size:9px;font-weight:800}.mk-supplier-board{border:1px solid #dce5f0;border-radius:17px;background:#fff;overflow:hidden;box-shadow:0 18px 48px rgba(15,23,42,.07)}.mk-supplier-row{display:grid;grid-template-columns:1.2fr 1fr 1fr .7fr;gap:12px;padding:16px 18px;border-top:1px solid #e8edf4;align-items:center;font-size:13px;color:#617188}.mk-supplier-row.head{border-top:0;background:#f5f8fc;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.06em}.mk-supplier-row b{color:#162842}.mk-supplier-row em{font-style:normal;color:#245fd5;font-weight:800}.mk-supplier-summary{margin:14px;padding:17px;border-radius:12px;background:#0c2854;color:#fff}.mk-supplier-summary p{margin:5px 0 0;color:#bcd0eb!important;font-size:13px}.mk-decision-card{padding:30px;border:1px solid #cfe0f2;border-radius:18px;background:linear-gradient(145deg,#fff,#f4f8ff);box-shadow:0 24px 65px rgba(15,23,42,.09)}.mk-decision-status{font-size:10px;font-weight:900;letter-spacing:.08em;color:#178153}.mk-decision-card h3{font-size:25px;margin:14px 0 10px}.mk-decision-card>p{color:#566a82!important}.mk-decision-meta{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:22px 0}.mk-decision-meta span{padding:10px;border-radius:9px;background:#fff;border:1px solid #e0e7f0;font-size:11px;color:#607188}.mk-decision-meta b{display:block;color:#172842}.mk-decision-history{display:grid;grid-template-columns:10px 1fr;gap:9px 10px;align-items:start}.mk-decision-history i{width:9px;height:9px;margin-top:5px;border-radius:50%;background:#2f6df6}.mk-decision-history span{font-size:12px;color:#263a55}.mk-decision-history small{display:block;color:#718096}.st-key-cv_native_footer [data-testid="stHorizontalBlock"]{justify-content:flex-start!important}.st-key-cv_native_footer div[class*="st-key-cv_footer_"] button[kind="primary"]::after{display:none!important}.st-key-cv_native_footer div[class*="st-key-cv_footer_"] button[kind="primary"]{font-weight:650!important;color:#d9e7fb!important}.st-key-cv_native_footer div[class*="st-key-cv_footer_"] button:hover{text-decoration:underline!important;text-underline-offset:3px}.mk-scroll-cta{cursor:pointer}.mk-scroll-cta:hover{background:rgba(255,255,255,.08)!important}
        @media(max-width:1180px){.mk-launch-hero-grid{grid-template-columns:1fr}.mk-demo-stage{max-width:900px}.mk-workflow-grid{grid-template-columns:repeat(2,1fr)}.mk-workflow-grid article::after{display:none}.mk-intelligence-layout,.mk-copilot-layout,.mk-decision-story{grid-template-columns:1fr;gap:40px}}
        @media(max-width:700px){.mk-demo-layout{grid-template-columns:1fr}.mk-demo-layout aside{display:none}.mk-demo-toolbar em{display:none}.mk-demo-kpis{grid-template-columns:repeat(2,1fr)}.mk-demo-bottom{grid-template-columns:1fr}.mk-workflow-grid,.mk-metric-showcase{grid-template-columns:1fr}.mk-decision-meta{grid-template-columns:repeat(2,1fr)}.mk-supplier-row{grid-template-columns:1fr 1fr}.mk-supplier-row span:nth-child(3),.mk-supplier-row.head span:nth-child(3){display:none}}
        /* Sprint 63.2 — Flagship B2B engineering product experience */
        .mk-launch-hero{background:radial-gradient(circle at 76% 20%,rgba(58,123,255,.27),transparent 30%),linear-gradient(135deg,#06142c 0%,#081b3a 56%,#0b2552 100%)!important}
        .mk-launch-copy{max-width:610px}.mk-launch-copy h1{max-width:610px}.mk-launch-copy .mk-hero-copy{max-width:590px;color:#c9d6e9!important}
        .mk-demo-stage{transform:perspective(1400px) rotateY(-1.4deg);transform-origin:center right}.mk-demo-frame{border-color:rgba(146,183,245,.38);box-shadow:0 45px 110px rgba(0,8,28,.5),0 0 0 1px rgba(255,255,255,.04)}
        .mk-demo-toolbar{height:48px}.mk-demo-toolbar em{display:flex;align-items:center;gap:7px;color:#2e6ae5;font-weight:850}.mk-live-dot{width:7px;height:7px;border-radius:50%;background:#22b573;box-shadow:0 0 0 4px rgba(34,181,115,.12)}
        .mk-demo-layout{min-height:470px}.mk-demo-layout aside{padding-top:22px}.mk-demo-content{padding:24px}.mk-demo-kpis>div{min-height:88px;display:flex;flex-direction:column;justify-content:center}.mk-demo-kpis strong{font-size:22px}.mk-demo-bottom{gap:13px}.mk-risk-panel,.mk-demo-recommendation{min-height:158px}
        .mk-media-slot video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.mk-media-slot span{position:relative;z-index:2;padding:8px 12px;border-radius:999px;background:rgba(5,18,40,.72);border:1px solid rgba(255,255,255,.2)}
        .mk-workflow-section{background:linear-gradient(180deg,#fff 0%,#f7faff 100%)}.mk-workflow-grid{gap:22px;position:relative}.mk-workflow-grid::before{content:'';position:absolute;left:8%;right:8%;top:50%;height:2px;background:linear-gradient(90deg,#d8e5fa,#2f6df6,#d8e5fa);z-index:0}.mk-workflow-grid article{z-index:1;min-height:270px;display:flex;flex-direction:column}.mk-workflow-grid article>small{margin-top:auto;padding-top:20px;font-size:9px;font-weight:900;letter-spacing:.09em;color:#6c84a3}.mk-workflow-grid article:not(:last-child)::after{box-shadow:0 0 0 7px #f8fbff}
        .mk-metric-showcase>div{min-height:142px;display:flex;flex-direction:column;justify-content:center;border-color:#d4e0ef}.mk-metric-showcase>div:nth-child(1){background:linear-gradient(145deg,#0d2853,#173f7d);border-color:#234b8b}.mk-metric-showcase>div:nth-child(1) small,.mk-metric-showcase>div:nth-child(1) span{color:#bcd1ef!important}.mk-metric-showcase>div:nth-child(1) strong{color:#fff!important;font-size:32px}
        .mk-copilot-window{background:#eef3f9;border-color:#cbd9ea}.mk-message{box-shadow:0 8px 22px rgba(15,23,42,.055)}.mk-message.assistant{max-width:90%}.mk-answer-header{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:8px}.mk-answer-header>span{flex:none;padding:5px 8px;border-radius:999px;background:#e4f6ed;color:#158052;font-size:9px;font-weight:900}.mk-evidence-block{margin-top:13px;padding:12px;border-radius:10px;background:#0d213f;color:#d6e5fa}.mk-evidence-block b{display:block;margin-bottom:7px;font-size:9px;letter-spacing:.09em;color:#80aef8}.mk-evidence-block code{display:block;white-space:pre-line;font:600 10px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;color:#e8f1ff}
        .mk-supplier-board{transform:translateY(0);box-shadow:0 24px 65px rgba(15,23,42,.09)}.mk-supplier-row{min-height:58px}.mk-supplier-summary{display:flex;justify-content:space-between;gap:20px;align-items:center}.mk-supplier-summary>span{flex:none;padding:8px 10px;border-radius:9px;background:rgba(255,255,255,.1);font-size:10px;color:#dce9ff}
        .mk-decision-card{border-top:4px solid #22a06b}.mk-decision-topline{display:flex;justify-content:space-between;gap:16px;align-items:center}.mk-decision-time{font-size:10px;color:#73839a}.mk-confidence{display:block;height:5px;margin:6px 0 5px;border-radius:999px;background:#e4ebf4;overflow:hidden}.mk-confidence em{display:block;height:100%;border-radius:inherit;background:#22a06b}.mk-rationale{padding:15px 16px;margin:-6px 0 22px;border-left:3px solid #2f6df6;background:#f3f7fd}.mk-rationale b{font-size:11px;color:#203b63}.mk-rationale p{margin:5px 0 0;font-size:12px;line-height:1.55;color:#607188!important}
        @media(max-width:1180px){.mk-demo-stage{transform:none}.mk-workflow-grid::before{display:none}}
        @media(max-width:700px){.mk-decision-topline,.mk-supplier-summary{align-items:flex-start;flex-direction:column}.mk-demo-stage{margin-top:10px}}

        /* Sprint 63.3 — lightweight motion and product-presence system */
        .mk-launch-hero{position:relative;isolation:isolate;overflow:hidden}.mk-launch-hero::before,.mk-launch-hero::after{content:"";position:absolute;border-radius:50%;pointer-events:none;filter:blur(2px);opacity:.55;z-index:-1}.mk-launch-hero::before{width:420px;height:420px;right:-130px;top:-170px;background:radial-gradient(circle,rgba(72,134,255,.28),transparent 68%);animation:cv-orbit 12s ease-in-out infinite alternate}.mk-launch-hero::after{width:320px;height:320px;left:36%;bottom:-230px;background:radial-gradient(circle,rgba(36,197,160,.13),transparent 68%);animation:cv-orbit 15s ease-in-out infinite alternate-reverse}
        .mk-launch-copy>*{opacity:0;transform:translateY(15px);animation:cv-hero-in .7s var(--mk-ease) forwards}.mk-launch-copy>*:nth-child(1){animation-delay:.05s}.mk-launch-copy>*:nth-child(2){animation-delay:.13s}.mk-launch-copy>*:nth-child(3){animation-delay:.21s}.mk-launch-copy>*:nth-child(4){animation-delay:.29s}.mk-launch-copy>*:nth-child(5){animation-delay:.37s}
        .mk-demo-stage{opacity:0;animation:cv-product-in .9s .18s var(--mk-ease) forwards}.mk-demo-frame::after{content:"";position:absolute;inset:48px 0 auto;height:90px;background:linear-gradient(180deg,transparent,rgba(72,132,255,.08),transparent);transform:translateY(-120px);pointer-events:none;animation:cv-scan 7s 1.4s ease-in-out infinite}.mk-demo-frame::before{content:"LIVE ANALYSIS";position:absolute;right:18px;bottom:15px;z-index:4;padding:5px 8px;border-radius:999px;background:rgba(8,29,61,.9);border:1px solid rgba(124,169,245,.28);color:#bcd5ff;font-size:7px;font-weight:900;letter-spacing:.12em;box-shadow:0 8px 22px rgba(7,19,42,.25)}
        .mk-live-dot{animation:cv-live 2s ease-out infinite}.mk-risk-line{position:relative;overflow:hidden}.mk-risk-line::before{content:"";position:absolute;left:0;top:20%;bottom:20%;width:2px;border-radius:2px;background:#3b78f3;opacity:0;animation:cv-risk-focus 6s ease-in-out infinite}.mk-risk-line:nth-child(3)::before{animation-delay:2s}.mk-risk-line:nth-child(4)::before{animation-delay:4s}
        .mk-demo-kpis>div{transition:transform .28s var(--mk-ease),box-shadow .28s var(--mk-ease),border-color .28s var(--mk-ease)}.mk-demo-kpis>div:nth-child(1){animation:cv-kpi-focus 8s 1.2s ease-in-out infinite}.mk-demo-kpis>div:nth-child(2){animation:cv-kpi-focus 8s 3.2s ease-in-out infinite}.mk-demo-kpis>div:nth-child(5){animation:cv-kpi-focus 8s 5.2s ease-in-out infinite}
        .mk-trust-inner{position:relative}.mk-trust-inner::after{content:"";position:absolute;left:0;bottom:-1px;width:22%;height:1px;background:linear-gradient(90deg,transparent,#4c83ed,transparent);animation:cv-trust-line 7s linear infinite}
        .mk-workflow-grid article{overflow:hidden}.mk-workflow-grid article::before{content:"";position:absolute;inset:auto 0 0;height:3px;background:linear-gradient(90deg,#2f6df6,#70a3ff);transform:scaleX(0);transform-origin:left;transition:transform .35s var(--mk-ease)}@media(hover:hover){.mk-workflow-grid article:hover{transform:translateY(-6px);border-color:#b9cfee;box-shadow:0 24px 56px rgba(18,48,93,.13)}.mk-workflow-grid article:hover::before{transform:scaleX(1)}}
        .mk-metric-showcase>div{position:relative;overflow:hidden}.mk-metric-showcase>div::after{content:"";position:absolute;left:22px;right:22px;bottom:15px;height:3px;border-radius:999px;background:#edf2f8}.mk-metric-showcase>div::before{content:"";position:absolute;left:22px;bottom:15px;height:3px;border-radius:999px;background:linear-gradient(90deg,#2f6df6,#76a7ff);width:var(--metric-fill,72%);transform:scaleX(0);transform-origin:left;transition:transform .9s .12s var(--mk-ease);z-index:1}.mk-metric-showcase>div:nth-child(2){--metric-fill:44%}.mk-metric-showcase>div:nth-child(3){--metric-fill:61%}.mk-metric-showcase>div:nth-child(4){--metric-fill:82%}.mk-metric-showcase>div:nth-child(5){--metric-fill:68%}.mk-metric-showcase>div:nth-child(6){--metric-fill:91%}.mk-section.cv-in-view .mk-metric-showcase>div::before{transform:scaleX(1)}
        .mk-copilot-window{position:relative}.mk-copilot-window::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;box-shadow:inset 0 0 0 1px rgba(60,119,225,.08);animation:cv-copilot-glow 5s ease-in-out infinite}.mk-message.assistant:last-child::after{content:"";display:inline-block;width:5px;height:12px;margin-left:5px;vertical-align:-2px;background:#2f6df6;animation:cv-cursor 1s steps(1) infinite}
        .mk-supplier-row:not(.head){transition:background .2s ease,transform .2s ease}.mk-supplier-row:not(.head):hover{background:#f5f8ff;transform:translateX(3px)}.mk-decision-card{transition:transform .3s var(--mk-ease),box-shadow .3s var(--mk-ease)}.mk-decision-card:hover{transform:translateY(-4px);box-shadow:0 30px 75px rgba(15,23,42,.13)}
        .mk-launch-story>section:not(.mk-launch-hero){opacity:0;transform:translateY(28px);transition:opacity .72s var(--mk-ease),transform .72s var(--mk-ease)}.mk-launch-story>section.cv-in-view{opacity:1;transform:none}.mk-launch-story>section.mk-trust{transform:translateY(12px)}.mk-launch-story>section.mk-trust.cv-in-view{transform:none}
        @keyframes cv-hero-in{to{opacity:1;transform:none}}@keyframes cv-product-in{from{opacity:0;transform:perspective(1400px) rotateY(-4deg) translateY(24px) scale(.975)}to{opacity:1;transform:perspective(1400px) rotateY(-1.4deg) translateY(0) scale(1)}}@keyframes cv-orbit{to{transform:translate3d(-34px,24px,0) scale(1.08)}}@keyframes cv-scan{0%,15%{transform:translateY(-130px);opacity:0}30%{opacity:1}70%{opacity:.65}85%,100%{transform:translateY(570px);opacity:0}}@keyframes cv-live{0%{box-shadow:0 0 0 0 rgba(34,181,115,.35)}70%{box-shadow:0 0 0 7px rgba(34,181,115,0)}100%{box-shadow:0 0 0 0 rgba(34,181,115,0)}}@keyframes cv-risk-focus{0%,25%,100%{opacity:0}8%,18%{opacity:1}}@keyframes cv-kpi-focus{0%,18%,100%{transform:none;box-shadow:none;border-color:#e0e7f0}7%,12%{transform:translateY(-2px);box-shadow:0 12px 24px rgba(35,83,158,.12);border-color:#a9c5ed}}@keyframes cv-trust-line{from{transform:translateX(-100%)}to{transform:translateX(560%)}}@keyframes cv-copilot-glow{0%,100%{opacity:.25}50%{opacity:1}}@keyframes cv-cursor{50%{opacity:0}}
        @media(max-width:1180px){@keyframes cv-product-in{from{opacity:0;transform:translateY(24px) scale(.98)}to{opacity:1;transform:none}}}
        @media(prefers-reduced-motion:reduce){.mk-shell *{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}.mk-launch-story>section{opacity:1!important;transform:none!important}.mk-metric-showcase>div::before{transform:scaleX(1)!important}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _install_marketing_motion() -> None:
    """Add lightweight viewport reveals without adding a frontend library."""
    components.html(
        """<script>
        (() => {
          const win = window.parent;
          const doc = win.document;
          const sections = [...doc.querySelectorAll('.mk-launch-story > section')];
          if (!sections.length) return;
          if (win.__cadivorMarketingObserver) win.__cadivorMarketingObserver.disconnect();
          const reduced = win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
          if (reduced || !('IntersectionObserver' in win)) {
            sections.forEach((section) => section.classList.add('cv-in-view'));
            return;
          }
          const observer = new win.IntersectionObserver((entries) => {
            entries.forEach((entry) => {
              if (entry.isIntersecting) {
                entry.target.classList.add('cv-in-view');
                observer.unobserve(entry.target);
              }
            });
          }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
          sections.forEach((section, index) => {
            if (index < 2) section.classList.add('cv-in-view');
            else observer.observe(section);
          });
          win.__cadivorMarketingObserver = observer;
        })();
        </script>""",
        height=0,
        width=0,
    )


def render_marketing_site(*, forced_page: str | None = None) -> None:
    """Render the signed-out marketing website.

    ``forced_page`` is used only for deterministic authentication landings. It
    prevents stale browser query parameters from painting the wrong public page
    before client-side history normalization completes.
    """
    _marketing_css()
    _sprint63_marketing_polish()
    _install_internal_link_bridge()
    st.markdown("""<style id="cadivor-static-public-runtime">
    html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],section.main{background:#ffffff!important;color:#0b1730!important}
    [data-testid="stAppViewContainer"]{transition:none!important}
    [data-testid="stSkeleton"],[data-testid="stSkeleton"]>div,
    [data-testid="stSkeleton"] span,[data-testid="stSkeleton"] svg{
      background:#f4f7fb!important;background-image:none!important;box-shadow:none!important;color:transparent!important;
    }
    [data-testid="stSkeleton"]{opacity:.18!important;min-height:0!important;max-height:6px!important;overflow:hidden!important}
    [data-testid="stStatusWidget"],[data-testid="stConnectionStatus"]{background:#fff!important;color:#64748b!important}
    .mk-shell,.mk-shell *{box-sizing:border-box}
    .mk-hero,.mk-page-hero{animation:none!important;transition:none!important}
    .st-key-cv_public_nav button[kind="primary"]{color:#ffffff!important;background:rgba(47,109,246,.18)!important;border:1px solid rgba(117,167,255,.22)!important;box-shadow:inset 0 -2px 0 #75a7ff!important}
    .st-key-cv_public_nav button:active{transform:translateY(1px)!important}
    .st-key-cv_public_nav button:focus:not(:focus-visible),
    .st-key-cv_native_footer button:focus:not(:focus-visible){outline:none!important;box-shadow:none!important}
    .st-key-cv_native_footer button[kind="primary"]:focus:not(:focus-visible){box-shadow:inset 2px 0 0 #75a7ff!important}
    </style>""", unsafe_allow_html=True)
    requested_page = _query_value("public")
    session_page = str(st.session_state.get("cadivor_public_route") or "").strip().lower()
    if forced_page:
        page = str(forced_page).strip().lower() or "home"
        st.session_state["cadivor_public_route"] = page
    elif session_page:
        page = session_page
    elif requested_page:
        # Optional external deep link only. Ordinary navigation is state-driven.
        page = requested_page.lower()
        st.session_state["cadivor_public_route"] = page
        try:
            st.query_params.clear()
        except Exception:
            pass
    else:
        page = "home"
        st.session_state["cadivor_public_route"] = page
    routes = {
        "home": _home,
        "product": _product,
        "features": _product,
        "solutions": _solutions,
        "pricing": _pricing,
        "resources": _resources,
        "company": _company,
        "contact": _contact,
        "security": lambda: _legal_page("security"),
        "privacy": lambda: _legal_page("privacy"),
        "terms": lambda: _legal_page("terms"),
    }
    normalized_page = str(page or "home").lower()
    previous_page = str(st.session_state.get("cadivor_last_public_render") or "")
    requested_section = str(st.session_state.get("cadivor_public_section") or "").strip().lower().lstrip("#")
    should_scroll = normalized_page != previous_page or bool(requested_section)
    if st.session_state.pop("cadivor_signing_out", False):
        st.markdown('<div class="cv-public-signout-toast">Signed out securely</div>', unsafe_allow_html=True)
    routes.get(normalized_page, _home)()
    _install_marketing_motion()
    if should_scroll:
        section_json = repr(requested_section)
        components.html(
            f"""<script>
            (() => {{
              const targetId = {section_json};
              const apply = () => {{
                try {{
                  const win = window.parent;
                  const doc = win.document;
                  if (targetId) {{
                    const target = doc.getElementById(targetId);
                    if (target) {{ target.scrollIntoView({{behavior:'auto', block:'start'}}); return true; }}
                  }}
                  win.scrollTo(0, 0);
                  doc.documentElement.scrollTop = 0;
                  doc.body.scrollTop = 0;
                  const nodes = doc.querySelectorAll('section.main,[data-testid="stMain"],[data-testid="stAppViewContainer"],[data-testid="stMainBlockContainer"]');
                  nodes.forEach((node) => {{ node.scrollTop = 0; }});
                  return !targetId;
                }} catch (e) {{ return false; }}
              }};
              let attempts = 0;
              const settle = () => {{ attempts += 1; if (!apply() && attempts < 12) setTimeout(settle, 50); }};
              requestAnimationFrame(settle);
              setTimeout(settle, 80);
              setTimeout(settle, 220);
            }})();
            </script>""", height=0, width=0)
        st.session_state["cadivor_last_public_render"] = normalized_page
        st.session_state["cadivor_public_section"] = ""
