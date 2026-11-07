# BOM analyzer guided workflow evidence

Screenshots for the `/bom-analyzer` seven-stage guidance.

## Static markup fixtures (legacy)

Earlier captures rendered static HTML with live `globals.css`. Kept for visual CSS reference only:

| State | Desktop | Mobile |
| --- | --- | --- |
| Initial | `screenshots/initial_desktop.png` | `screenshots/initial_mobile.png` |
| Validation | `screenshots/validation_desktop.png` | `screenshots/validation_mobile.png` |
| Progress | `screenshots/progress_desktop.png` | `screenshots/progress_mobile.png` |
| Completed | `screenshots/completed_desktop.png` | `screenshots/completed_mobile.png` |
| Error | `screenshots/error_desktop.png` | `screenshots/error_mobile.png` |

```bash
node docs/evidence_bom_workflow/capture_screenshots.mjs
```

## Real signed-in Next.js route (preferred)

Captured from the actual authenticated `/bom-analyzer` route against the local sandbox API using `tests/fixtures/synthetic_bom_25parts.csv`. The UI shows a synthetic-sample label (`data-testid="synthetic-sample-label"`).

| State | Desktop | Mobile |
| --- | --- | --- |
| Initial | `screenshots/real_initial_desktop.png` | `screenshots/real_initial_mobile.png` |
| Ready to analyze | `screenshots/real_ready_desktop.png` | `screenshots/real_ready_mobile.png` |
| Analyzing | `screenshots/real_analyzing_desktop.png` | `screenshots/real_analyzing_mobile.png` |
| Leave/return | `screenshots/real_resume_inflight_or_done_desktop.png` | `screenshots/real_resume_inflight_or_done_mobile.png` |
| Success | `screenshots/real_success_desktop.png` | `screenshots/real_success_mobile.png` |
| Risks | `screenshots/real_risks_desktop.png` | `screenshots/real_risks_mobile.png` |
| Evidence | `screenshots/real_evidence_desktop.png` | `screenshots/real_evidence_mobile.png` |
| Decision | `screenshots/real_decision_desktop.png` | `screenshots/real_decision_mobile.png` |
| Monitor | `screenshots/real_monitor_desktop.png` | `screenshots/real_monitor_mobile.png` |
| Validation error | `screenshots/real_validation_error_desktop.png` | `screenshots/real_validation_error_mobile.png` |

```bash
# From repo root (starts API :8787 + Next :3000 unless already up)
node docs/evidence_bom_workflow/capture_real_route.mjs
```

Manifest: `screenshots/real_route_manifest.json`.

**Not production.** These captures use sandbox JWT auth and synthetic fixtures only. This PR does not merge, deploy, or change production.
