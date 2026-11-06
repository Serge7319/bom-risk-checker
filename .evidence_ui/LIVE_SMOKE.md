# Real-route UI smoke (synthetic local API)

## Servers
- API: `http://127.0.0.1:8080` (sandbox JWT + synthetic-preview)
- Next dev: `http://127.0.0.1:3000` with `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080`

## Auth / flow
- Signed in as `sandbox-a@cadivor.test` (tests/fixtures sandbox account)
- Analyzed `tests/fixtures/synthetic_bom_25parts.csv`
- Post-analyze URL: `/reports/<analysis_id>` (see live_smoke_report.json)

## Screenshots
`.evidence_ui/screenshots_live/` @ 1680×1050 and 696×1188:
- home_*.png — live KPIs (1 project / 1 BOM / health 94)
- bom_*.png — sticky progress + upload form
- procurement_*.png — synthetic supplier table + Next steps
- prod_reject_localhost_1680x1050.png — production guard

## Production localhost guard
- Built/started Next production on `:3001` with `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080` and **no** `NEXT_PUBLIC_ALLOW_LOCAL_API`
- Login stayed on `/login` with: `Cadivor could not connect. Refresh the page or contact support.`
- Evidence: `prod_localhost_reject.json`

## Status
Uncommitted; production Streamlit / Railway untouched. Local servers stopped after smoke.
