"""Cadivor lightweight interaction runtime.

The former route-mask implementation was removed because it could outlive the
Streamlit rerun, obscure the destination, and intercept logout. Navigation is
now server-state driven and intentionally has no DOM-level transition layer.
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

          // Remove masks left by older deployed code immediately.
          doc.getElementById('cadivor-route-transition-overlay-v1')?.remove();
          doc.documentElement.dataset.cadivorPage = CURRENT_PAGE;
          win.__cadivorShowRouteMask = () => {{}};

          if (win.__cadivorInteractionObserver) {{
            win.__cadivorInteractionObserver.disconnect();
            win.__cadivorInteractionObserver = null;
          }}

          // Remove stale per-button bindings created by the old transition
          // runtime. Cloning is avoided so Streamlit event handlers remain intact.
          doc.querySelectorAll('[data-cv-transition-bound]').forEach((node) => {{
            delete node.dataset.cvTransitionBound;
          }});
        }})();
        </script>
        """,
        height=0,
        width=0,
    )
