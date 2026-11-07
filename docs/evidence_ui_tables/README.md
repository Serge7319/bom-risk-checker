# Evidence notices + table polish

Branch: `ui/evidence-notices-and-tables`

## Changes
- Yellow “Evidence note” cards no longer repeat service availability (billing / monitoring email / connectors) on Reports and Home; those belong in Settings → Billing → Service readiness.
- Settings → Service readiness reads `/integrations/service-readiness` and reports **operational** status (not enable flags alone):
  - Monitoring email is Ready only when a deliverable transport is wired; flag-on without transport is Not connected.
  - Scheduler requires the cron token; external schedule attachment is not verified, so configured schedulers report Partial.
  - Billing checkout is not Ready while `prepare_checkout_intent` returns `not_implemented`.
  - Failures return a generic detail only (no raw exception string in the API body).
- Routine “based on saved analyses” gaps render as compact neutral `cv-evidence-context` notes.
- Shared table style: light vertical + horizontal dividers, stronger header band, hover row, numeric alignment, wrap for rationale cells.
- Design Impact and Portfolio use `cv-table--fit` inside `cv-card--table`. At ≤520px, fit tables stack as labeled cards so columns are not clipped.

## Screenshots (markup fixtures)
`docs/evidence_ui_tables/capture_screenshots.mjs` is a **CSS markup fixture** capture. It does **not** boot the Next.js app shell or hit live `/design-impact`, `/portfolio-intelligence`, or `/compare-parts` routes. PNGs illustrate CSS/layout intent with synthetic table data and check `documentElement.scrollWidth` against the viewport at **390px**, **696px**, and **desktop**. They are not proof that authenticated Next routes are overflow-free.

| File | Viewport |
| --- | --- |
| `screenshots/after_design_impact_mobile.png` | 390px fixture |
| `screenshots/after_design_impact_tablet_696.png` | 696px fixture |
| `screenshots/after_design_impact_desktop.png` | desktop fixture |
| `screenshots/after_portfolio_*.png` | same widths |
| `screenshots/after_compare_*.png` | same widths |
| `screenshots/overflow_report.json` | fixture overflow measurements |

```bash
node docs/evidence_ui_tables/capture_screenshots.mjs
```

## Verification
- `pytest tests/test_evidence_notice_behavior.py tests/test_evidence_notice_classification.py tests/test_service_readiness.py -q`

## Do not deploy
Open PR for review; do not merge or deploy until approved.
