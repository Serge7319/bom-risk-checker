Cadivor Sprint 2.1 v2.2 — Shell Recovery Hotfix

Files to replace:
- streamlit_app.py
- src/ui/framework.py

What changed:
- Removed the native Streamlit sidebar logout block from the authenticated shell.
- Added global shell CSS outside the Dashboard-only block so the custom Cadivor sidebar renders correctly on every page.
- Changed the app layout from padding-left to a true left margin so the sidebar no longer overlaps Dashboard content.
- Kept the authenticated sidebar available on every page without raw/unstyled navigation text.
- Top bar now uses the saved profile/company fields where available.
- Preserved existing business logic, supplier integrations, auth behavior, saved BOM loading, and report logic.

Testing checklist:
1. Login.
2. Confirm the native Streamlit sidebar is hidden.
3. Confirm the custom Cadivor sidebar does not cover the Dashboard.
4. Click Dashboard, BOM Analyzer, Alternative Finder, Monitoring, Reports, Pricing, Settings, and About.
5. Confirm every page keeps the styled sidebar/topbar.
6. Use browser back/forward between app pages and confirm the layout stays stable.
