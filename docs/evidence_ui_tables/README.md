# Evidence notices + table polish

Branch: `ui/evidence-notices-and-tables`

## Changes
- Yellow “Evidence note” cards no longer repeat service availability (billing / monitoring email / connectors) on Reports and Home; those belong in Settings → Billing → Service readiness.
- Routine “based on saved analyses” gaps render as compact neutral `cv-evidence-context` notes.
- Decision-critical disclosures (synthetic prices, offline/incomplete Compare Parts evidence) remain amber beside the relevant workflow.
- Shared table style: light vertical + horizontal dividers, stronger header band, hover row, numeric alignment, wrap for rationale cells.
- Design Impact and Portfolio use `cv-table--fit` inside `cv-card--table` so desktop widths avoid inner horizontal scroll; grids stack under 900px. Page-level `overflow-x: hidden` on `html, body`.

## Screenshots
| File | Notes |
| --- | --- |
| `screenshots/before_design_impact_desktop.png` | Yellow multi-topic banner + clipped wide table |
| `screenshots/after_design_impact_desktop.png` | Compact context note + fit table |
| `screenshots/before_design_impact_mobile.png` | Before at 390px |
| `screenshots/after_design_impact_mobile.png` | After at 390px |
| `screenshots/after_compare_desktop.png` | Critical offline/incomplete disclosure retained |

## Do not deploy
Open PR for review and merge first; do not push a production deploy from this work until approved.
