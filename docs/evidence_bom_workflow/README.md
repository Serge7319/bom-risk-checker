# BOM analyzer guided workflow evidence

Screenshots for the `/bom-analyzer` seven-stage guidance:

| State | Desktop | Mobile |
| --- | --- | --- |
| Initial (Received current) | `screenshots/initial_desktop.png` | `screenshots/initial_mobile.png` |
| Validation preview | `screenshots/validation_desktop.png` | `screenshots/validation_mobile.png` |
| In progress (indeterminate) | `screenshots/progress_desktop.png` | `screenshots/progress_mobile.png` |
| Completed → Risks | `screenshots/completed_desktop.png` | `screenshots/completed_mobile.png` |
| Error (file retained) | `screenshots/error_desktop.png` | `screenshots/error_mobile.png` |

Regenerate:

```bash
node docs/evidence_bom_workflow/capture_screenshots.mjs
```
