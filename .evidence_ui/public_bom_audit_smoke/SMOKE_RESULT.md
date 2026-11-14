# Public BOM audit — Next.js app preview smoke

**Not Cloudflare Pages.** Marketing `*.cadivor.pages.dev` is out of scope for this check.

| Field | Value |
| --- | --- |
| App preview | `http://127.0.0.1:13017` (local Next.js `next dev`) |
| Stub API | `http://127.0.0.1:18080` (`scripts/public_bom_preview_api.py`) |
| Runner | `apps/web/scripts/public_bom_browser_smoke.mjs` (Playwright) |
| Result | **PASS** |

Checks exercised (signed-out):

- status loading visible, then enabled upload
- multipart BOM upload → preliminary audit
- lead submission → verification email confirmation copy
- forced status `503` → unavailable/error UI, upload hidden

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
