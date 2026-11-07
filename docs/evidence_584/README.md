# Evidence for PR — Next parity integrations (#584 follow-up)

## Regression tests (2026-11-07)

```text
28 passed — tests/test_nextjs_parity_followup.py
            tests/test_next_team_settings.py
            tests/test_nextjs_invitations.py
```

Includes:

1. Standalone `AM29F010B-70EC` with no saved report
2. Standalone search with stale analysis ID in request
3. BOM-row search preserving only that BOM’s context
4. Inaccessible report ID — no cross-workspace data; search not blocked
5. Invite create → register → accept with role persistence (email sink)
6. Profile/preferences persist after refresh

## Screenshots

| File | Viewport |
| --- | --- |
| `screenshots/settings_desktop.png` | 1280×900 |
| `screenshots/settings_mobile.png` | 390×844 |
| `screenshots/find_replacement_desktop.png` | 1280×900 |
| `screenshots/find_replacement_mobile.png` | 390×844 |

Static layout captures of the rebuilt Settings shell and Find a Replacement standalone path (no live customer data).

## Config gaps (exact names)

See `docs/SUPPLIER_EMAIL_CONFIG_GAP_584.md`. Production `cadivor-next-api-prod` still missing supplier and Resend variables; live provider coverage remains incomplete until operators transfer secrets via Railway.
