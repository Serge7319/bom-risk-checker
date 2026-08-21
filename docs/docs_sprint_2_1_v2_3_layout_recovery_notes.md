# Cadivor Sprint 2.1 v2.3 — Layout Recovery Hotfix

## Files updated
- streamlit_app.py
- src/ui/framework.py

## Fixes
- Reworked the app shell so the dashboard and all authenticated pages reserve space for the fixed Cadivor sidebar.
- Removed the Streamlit top header/toolbar from the authenticated shell so it no longer pushes or interferes with the Cadivor topbar.
- Moved the content offset to the Streamlit block container instead of relying on Streamlit's changing internal `.main` layout classes.
- Kept the topbar user profile aligned with the Cadivor logo area.
- Reduced the quick-action vertical offset so New Analysis / Alternatives do not float too far down.

## Testing checklist
1. Replace the files and reboot the Streamlit app.
2. Login.
3. Check Dashboard: content should start to the right of the Cadivor sidebar, not under it.
4. Check BOM Analyzer, Monitoring, and About: sidebar should not overlap content.
5. Use browser back/forward and verify the layout remains stable.

## Note
If a brief login/landing flash still appears during browser back/forward, that is caused by the app reloading and waiting for the cookie/session restore. The next pass should replace sidebar HTML links with in-app navigation controls to reduce full-page reload behavior.
