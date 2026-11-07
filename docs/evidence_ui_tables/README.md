# Evidence notices + table polish

Branch: `ui/evidence-notices-and-tables`

## Changes
- Yellow “Evidence note” cards no longer repeat service availability (billing / monitoring email / connectors) on Reports and Home; those belong in Settings → Billing → Service readiness.
- Settings → Service readiness reads `/integrations/service-readiness` (actual monitoring-email, scheduler, connector readiness fields). Shows **Unknown** if the endpoint cannot be fetched. Does not infer email status from `/billing/status` or `/plan/usage`.
- Routine “based on saved analyses” gaps render as compact neutral `cv-evidence-context` notes.
- Decision-critical disclosures (synthetic prices, offline/incomplete Compare Parts evidence) remain amber beside the relevant workflow.
- Shared table style: light vertical + horizontal dividers, stronger header band, hover row, numeric alignment, wrap for rationale cells.
- Design Impact and Portfolio use `cv-table--fit` inside `cv-card--table`. At ≤520px, fit tables stack as labeled cards so columns are not clipped. Page-level `overflow-x: hidden` was removed from `html`/`body`; overflow is contained in shell/table wrappers.

## Screenshots
Captured with `docs/evidence_ui_tables/capture_screenshots.mjs` using the **live** `apps/web/src/app/globals.css` and the Design Impact / Portfolio / Compare Parts route markup (same structure as the Next pages). No fixture stylesheet overrides the mobile grid rule.

| File | Notes |
| --- | --- |
| `screenshots/before_design_impact_desktop.png` | Prior yellow multi-topic banner + clipped wide table |
| `screenshots/before_design_impact_mobile.png` | Prior 390px capture |
| `screenshots/after_design_impact_desktop.png` | Compact context note + fit table |
| `screenshots/after_design_impact_mobile.png` | 390px stacked cards / labeled rows |
| `screenshots/after_portfolio_desktop.png` | Portfolio fit tables |
| `screenshots/after_portfolio_mobile.png` | Portfolio at 390px |
| `screenshots/after_compare_desktop.png` | Critical offline/incomplete disclosure retained |

## Verification
- `pytest tests/test_evidence_notice_behavior.py tests/test_evidence_notice_classification.py tests/test_service_readiness.py`
- Desktop + mobile screenshot capture via Playwright against Next route CSS/markup

## Do not deploy
Open PR for review and merge first; do not push a production deploy from this work until approved.
