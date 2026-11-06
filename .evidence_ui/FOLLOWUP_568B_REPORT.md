# PR #568 follow-up — production gates (568b)

## Status
Not calling the experience fully approved. These production issues were fixed and locally verified; production deploy SHA/deploy IDs are recorded after Railway publish.

## Fixes
1. **Compare Parts identity / evidence**
   - Offline catalog is identity-only (manufacturer, description, category/architecture).
   - `NE555P` → Timer IC (TI precision timer); `LM358DR` → Operational amplifier.
   - Unverified attributes map to **Unable to confirm** (no invented package/electrical values; no drop-in implication).
2. **Ask Cadivor vs saved report**
   - Context maps report fields including optional `supplier_count` / stock / risk.
   - Missing supplier counts are not treated as “0 recorded source”.
   - Tied scores no longer become 100/100; when the report has 0 high/medium priority risks, Ask states that plainly.
3. **Customer copy**
   - Home/reports persistence gaps no longer mention “migration Postgres”, “Streamlit app”, or “migration database”.
4. **Home Active Projects**
   - Table wrap uses intentional overflow-x scroll; Open stays visible.
   - Viewports verified: 1680×1050, 1366×768, 696×1188 — no page-level horizontal overflow; Open visible.

## Local verification
- `pytest tests/test_nextjs_parity_followup.py tests/test_family_engineering_profiles.py tests/test_nextjs_migration_tools.py tests/test_nextjs_migration_api.py` → **20 passed**
- Compare LM358DR vs NE555P → Material difference; families Operational amplifier / Timer IC; assessments include Unable to confirm (no “Needs data”)
- Ask Cadivor on all-low-risk report → “0 priority risks… not enough differentiating risk evidence”; no “only 0 recorded source”; no 100/100
- Screenshots: `.evidence_ui/screenshots/home_active_projects_{desktop_1680x1050,laptop_1366x768,mobile_696x1188}.png`

## Remaining blockers (honest)
1. Live authorized distributors: not connected.
2. Billing checkout: status only; no Checkout sessions/charges.
3. Alert email: mock sink only.
4. Self-serve signup: closed.
5. Production authenticated E2E for this agent still needs a real Supabase user session (sandbox JWT fail-closed in production_runtime).
