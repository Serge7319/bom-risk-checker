# Cadivor developer API v1

Developer keys are workspace-scoped, shown once at creation, stored as SHA-256
hashes, and can be managed from **APIs** in the workspace navigation. Each request checks the key,
current API entitlement, and the key owner's active workspace membership. A
revoked key or inactive entitlement stops working immediately.

Key management and usage-credit mutations are accepted by the Edge Function
only with a server-generated HMAC proof. Direct browser calls cannot bypass
the API's workspace-admin checks or restore consumed credits.

API access is included with Trial, Business, and Enterprise entitlements. An
active Professional subscription needs the separate monthly Professional API
add-on. Platform administrators can also grant or disable the `api_access`
account override.

## Authentication

Send the key as a bearer token:

```http
Authorization: Bearer cdv_live_<key>
```

Treat the full key like a password. Do not place it in browser code, source
control, or shared logs. Cadivor displays the full value only once.

## Endpoints

`POST /v1/analyses` accepts a `multipart/form-data` upload with a `file` field
(CSV or XLSX, up to 10 MB). Optional text fields are `project_name`, `bom_name`,
and `revision`. It runs the same server-side validation, plan-limit checks, and
analysis pipeline as the Cadivor web app, saves the result to the key's
workspace, and returns an `analysis_id`, summary, and `report_url`. The report
can then be retrieved through `GET /v1/reports/{analysis_id}`.

Analysis submission is a write operation. It can use supplier sources enabled
for the Cadivor environment and can consume the account's included analysis
allowance. It never starts a one-time report checkout or charges a payment
method; if the account cannot create an analysis under its current entitlements,
the API returns `402` with `billing_action: "none"`. Submissions are limited to
5 per minute per API key. The general API limit remains 180 requests per minute.

`GET /v1/reports?limit=25&offset=0` returns up to 100 report summaries. Follow
`next_offset` until it is `null` to page through the workspace. The response
includes the total count and a `reports` array.

`GET /v1/reports/{analysis_id}` returns the saved report, including its
component findings and evidence, only when that report belongs to the key's
workspace.

Report reads are workspace-scoped. Keep API keys in an OS credential store or
server-side secret manager; never embed one in public browser code or a shared
KiCad project.

## Outgoing webhooks

Workspace owners and admins with API access can add HTTPS destinations under
**Settings → Billing → Developer API keys → Outgoing webhooks**. Cadivor
encrypts the destination and signing secret at rest. The signing secret is
shown once when the endpoint is created. The API service must have
`CADIVOR_DEVELOPER_WEBHOOK_ENCRYPTION_KEY` or the existing
`CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY` configured with a valid Fernet key.

Supported event types:

- `analysis.completed` — a BOM analysis submitted through `POST /v1/analyses`
  was saved.
- `monitoring.alerts.created` — scheduled monitoring recorded a new or changed
  source-backed alert for an opted-in workspace.
- `webhook.test` — a one-off connection test initiated in Settings.

Every request includes `X-Cadivor-Webhook-Id`, `X-Cadivor-Webhook-Event`,
`X-Cadivor-Webhook-Timestamp`, and `X-Cadivor-Webhook-Signature: v1=<hex>`.
The signature is HMAC-SHA256 over the exact request body prefixed by the
timestamp and a period. Verify it against the raw bytes before parsing JSON:

```python
import hashlib
import hmac

signed = timestamp.encode("ascii") + b"." + request_body
expected = "v1=" + hmac.new(signing_secret.encode(), signed, hashlib.sha256).hexdigest()
valid = hmac.compare_digest(expected, signature_header)
```

Reject timestamps outside a short replay window and deduplicate on the event
`id` (or delivery header) before applying side effects. Retries keep the same
delivery ID and event ID.

Deliveries use a durable outbox, are attempted immediately for API events and
on scheduled monitoring runs, and retry with backoff up to five times. Cadivor
does not follow redirects and rejects destinations that do not use public
HTTPS addresses. The Settings page shows recent delivery status. Treat the
payload as workspace data: alert events may include part numbers, alert text,
and evidence links. A monitoring event is emitted only when a live scheduled
check reports a source-backed change; dry-run checks do not send webhooks.

## Provisioning

Apply the `20261119150000_stripe_usage_addons.sql` Supabase migration and deploy
the updated `subscription-checkout` Edge Function before using API keys. See
`priority-1-addons-rollout.md` for the separate Stripe add-on settings.
