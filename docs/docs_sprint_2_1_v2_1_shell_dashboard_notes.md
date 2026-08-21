# Cadivor Sprint 2.1 v2.1 — App Shell / Dashboard Hotfix

## Objective
Resolve the Streamlit sidebar interference and improve the authenticated dashboard shell.

## Files Updated
- streamlit_app.py
- src/ui/framework.py

## Changes
- Hid the native Streamlit sidebar/collapse control.
- Added a custom Cadivor left navigation shell with same-tab page navigation.
- Kept workspace/profile information visible in the app shell.
- Expanded the authenticated app content area so the dashboard uses the available screen width.
- Removed the broken empty white strips caused by open HTML panel wrappers around Streamlit components.
- Reworked dashboard quick-action buttons so they align better with the page header.
- Kept profile fields connected to the profile data already available in the app.

## Test Checklist
1. Login.
2. Confirm the native Streamlit sidebar is hidden.
3. Confirm the custom Cadivor sidebar appears with navigation links.
4. Click Dashboard, BOM Analyzer, Alternative Finder, Monitoring, Reports, Pricing, Settings.
5. Confirm each link stays in the same browser tab.
6. Click New Analysis from Dashboard.
7. Click Alternatives from Dashboard.
8. Confirm profile name/company still display in the topbar.
