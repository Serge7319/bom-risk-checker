# Cadivor Design System v1.0

## Objective
Rebrand the application from BOM Risk Checker to Cadivor and establish a reusable design-system foundation.

## Files changed
- streamlit_app.py
- src/auth.py
- src/css/premium.css
- src/ui/__init__.py
- src/ui/framework.py
- .streamlit/config.toml
- docs/CADIVOR_LEGAL_DRAFTS.md
- CADIVOR_DESIGN_SYSTEM_V1_NOTES.md

## Brand positioning
Cadivor is an engineering intelligence platform for modern electronics teams.

Primary phrase:
Run it through Cadivor.

Hero:
Reduce BOM Risk. Run it through Cadivor.

Trusted language:
AI-assisted insights, not fully autonomous AI decisions.

## Testing checklist
1. Landing page opens and shows Cadivor branding.
2. Sign In opens the compact auth page.
3. Get Started opens create-account mode.
4. Login still works.
5. Dashboard loads.
6. BOM Analyzer opens.
7. Alternative Finder opens.
8. No `ModuleNotFoundError: src.ui.framework`.
