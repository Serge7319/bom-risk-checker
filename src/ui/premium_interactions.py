"""Cadivor premium interaction runtime.

Keeps the authenticated shell visually mounted while Streamlit resolves a new
route and applies small parent-document interaction repairs that cannot be
implemented reliably with page-local CSS alone.
"""
from __future__ import annotations

import json

import streamlit.components.v1 as components


def render_premium_interactions(*, current_page: str) -> None:
    page_json = json.dumps(str(current_page or "Dashboard"))
    components.html(
        f"""
        <script>
        (() => {{
          const doc = window.parent.document;
          const win = window.parent;
          const CURRENT_PAGE = {page_json};
          const OVERLAY_ID = 'cadivor-route-transition-overlay-v1';
          const STYLE_ID = 'cadivor-premium-interaction-runtime-v1';

          // A new destination has rendered. Remove any mask left by the prior DOM.
          doc.getElementById(OVERLAY_ID)?.remove();
          doc.documentElement.dataset.cadivorPage = CURRENT_PAGE;

          if (!doc.getElementById(STYLE_ID)) {{
            const style = doc.createElement('style');
            style.id = STYLE_ID;
            style.textContent = `
              #${{OVERLAY_ID}}{{position:fixed;left:var(--cv-foundation-rail,232px);right:0;top:var(--cv-foundation-top,64px);bottom:0;z-index:999990;background:#f5f7fb;display:flex;align-items:flex-start;justify-content:center;padding:28px;box-sizing:border-box;opacity:0;animation:cv-route-mask-in .08s ease-out forwards;pointer-events:all}}
              #${{OVERLAY_ID}} .cv-route-mask{{width:100%;max-width:none;display:grid;gap:16px}}
              #${{OVERLAY_ID}} .cv-route-kicker{{color:#2563eb;font:900 10px/1.2 Inter,system-ui,sans-serif;letter-spacing:.13em;text-transform:uppercase}}
              #${{OVERLAY_ID}} .cv-route-title{{color:#0f172a;font:900 22px/1.15 Inter,system-ui,sans-serif;letter-spacing:-.025em}}
              #${{OVERLAY_ID}} .cv-route-hero{{height:112px;border:1px solid #e2e8f0;border-radius:18px;background:linear-gradient(90deg,#fff 20%,#f3f6fa 38%,#fff 56%);background-size:260% 100%;animation:cv-route-shimmer 1.1s linear infinite}}
              #${{OVERLAY_ID}} .cv-route-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
              #${{OVERLAY_ID}} .cv-route-card{{height:126px;border:1px solid #e2e8f0;border-radius:16px;background:linear-gradient(90deg,#fff 20%,#f3f6fa 38%,#fff 56%);background-size:260% 100%;animation:cv-route-shimmer 1.1s linear infinite}}
              @keyframes cv-route-mask-in{{to{{opacity:1}}}}
              @keyframes cv-route-shimmer{{to{{background-position:-130% 0}}}}
              @media(max-width:760px){{#${{OVERLAY_ID}}{{left:var(--cv-foundation-rail,188px);padding:16px}}#${{OVERLAY_ID}} .cv-route-grid{{grid-template-columns:1fr}}}}
            `;
            doc.head.appendChild(style);
          }}

          const showMask = (label) => {{
            doc.getElementById(OVERLAY_ID)?.remove();
            const overlay = doc.createElement('div');
            overlay.id = OVERLAY_ID;
            overlay.setAttribute('role','status');
            overlay.setAttribute('aria-live','polite');
            const safe = String(label || 'Cadivor workspace').replace(/[<>]/g,'');
            overlay.innerHTML = `<div class="cv-route-mask"><div><div class="cv-route-kicker">Engineering workspace</div><div class="cv-route-title">Opening ${{safe}}…</div></div><div class="cv-route-hero"></div><div class="cv-route-grid"><div class="cv-route-card"></div><div class="cv-route-card"></div><div class="cv-route-card"></div></div></div>`;
            doc.body.appendChild(overlay);
          }};
          win.__cadivorShowRouteMask = showMask;

          const bind = (button) => {{
            if (!button || button.dataset.cvTransitionBound === '1') return;
            button.dataset.cvTransitionBound = '1';
            button.addEventListener('click', () => {{
              const label = button.innerText?.trim() || 'Cadivor workspace';
              // Active route clicks do not need a transition mask.
              if (button.getAttribute('kind') === 'primary' && label === CURRENT_PAGE) return;
              showMask(label.replace(/^＋\s*/,''));
            }}, true);
          }};

          const bindAll = () => {{
            doc.querySelectorAll('.st-key-cv_foundation_navigation .stButton > button').forEach(bind);
            doc.querySelectorAll('[data-testid="stPopoverBody"] .stButton > button').forEach(bind);
          }};
          bindAll();

          if (win.__cadivorInteractionObserver) win.__cadivorInteractionObserver.disconnect();
          win.__cadivorInteractionObserver = new MutationObserver(bindAll);
          win.__cadivorInteractionObserver.observe(doc.body, {{childList:true,subtree:true}});
        }})();
        </script>
        """,
        height=0,
        width=0,
    )
