# Public BOM audit — Next.js app preview smoke

**Not Cloudflare Pages.** Marketing `*.cadivor.pages.dev` is out of scope for this check.

## Stub upload / lead smoke (signed-out)

| Field | Value |
| --- | --- |
| Kind | **stub-api upload + lead** |
| App preview | `http://127.0.0.1:13017` (local Next.js `next dev`) |
| Stub API | `http://127.0.0.1:18080` (`scripts/public_bom_preview_api.py`) |
| Runner | `apps/web/scripts/public_bom_browser_smoke.mjs` (Playwright) |
| Result | **PASS** |
| Proves | status → upload → preliminary audit → lead email-request UI |
| Does **not** prove | email confirmation, verified-report ownership, Reports handoff |

```json
{
  "ok": true,
  "results": {
    "base": "http://127.0.0.1:13017",
    "statusLoadingSeen": true,
    "statusEnabledUpload": true,
    "auditUploadOk": true,
    "leadSubmitOk": true,
    "statusErrorPath": true
  }
}
```

## Report-delivery smoke (authenticated handoff)

| Field | Value |
| --- | --- |
| Kind | **report-delivery** (stub bearer gate; not live Supabase OTP) |
| App preview | `http://127.0.0.1:13017` |
| Stub API | bearer-gated `/public/bom-stress/verified-report` |
| Runner | `apps/web/scripts/public_bom_report_delivery_smoke.mjs` |
| Result | **PASS** |
| Proves | owner token + `report_id` selector loads full audit in Reports; cross-user denied; reopen after reload via cache + re-fetch |
| Does **not** prove | live OTP email delivery / Supabase confirm click |

```json
{
  "ok": true,
  "results": {
    "kind": "report-delivery",
    "stubApi": true,
    "liveOtp": false,
    "base": "http://127.0.0.1:13017",
    "authorizedVisible": true,
    "crossUserHidden": true,
    "reopenAfterReload": true
  }
}
```

Live OTP confirmation remains an environment check outside this stub smoke.
