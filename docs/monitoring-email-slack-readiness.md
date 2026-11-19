# Production monitoring delivery setup

This config enables alert delivery and validates the existing six-hour
monitoring path. It does not change the cadence or start an off-schedule run.

## 1. Enable email alert delivery

In Railway, open the production `cadivor-next-api-prod` service and set:

- `CADIVOR_MONITORING_EMAIL_ENABLED=1`
- `RESEND_API_KEY` to the production Resend API key
- `TRANSACTIONAL_FROM_EMAIL` to a verified Resend sender; `ALERT_FROM_EMAIL` is
  accepted as the fallback sender

The Resend credential and sender variables already exist in production. Check
that the sender is verified in Resend before enabling the email flag. Save the
variable change and let Railway redeploy the API.

Each workspace member must then open **Monitoring** and opt in to email alerts
or the weekly digest. Cadivor sends monitoring email only to that signed-in
member's verified account address.

## 2. Connect a Slack channel

In the same Railway API service, confirm
`CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY` is a valid Fernet key. The value must be
managed in Railway or a trusted secrets manager; do not place it in chat or
source control. If it must be generated, create a Fernet key in a trusted local
environment and paste it directly into Railway's masked variable editor.

In Slack, create or select an app, enable **Incoming Webhooks**, add it to the
target channel, and copy that channel's webhook URL. A Cadivor workspace owner
or admin then opens **Monitoring**, enters the URL, and enables Slack alerts.
Cadivor validates the Slack host and encrypts the URL before storing it. Posts
contain aggregate alert counts and a Cadivor link, not BOM names or part
numbers.

## 3. Confirm scheduled monitoring readiness

The production API must report all of the following as ready:

- `CADIVOR_MONITORING_SCHEDULER_ENABLED=1`
- `CADIVOR_MONITORING_SCHEDULE_ATTACHED=1`
- `CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED=1`
- A configured `CADIVOR_MONITORING_CRON_TOKEN` that matches the protected cron
  caller's credential
- At least one authorized supplier credential
- At least one workspace member opted in to supplier checks

Check **Settings → Service readiness** after deployment. The scheduled runner
must continue to use the existing six-hour expression `0 */6 * * *`; do not
replace the schedule or trigger a manual run as a readiness check. Keep the
cron in dry-run mode until a naturally scheduled dry run reports
`ok=true`, `status=dry_run`, `supplier_calls=0`, `persisted=false`, and
`email_sent=false` and the readiness values above are confirmed.

## Current production gap recorded during rollout

`CADIVOR_MONITORING_EMAIL_ENABLED` was absent from the API service variable
names when this setup was documented, so application alert email delivery was
disabled. The Slack encryption variable name was present, but a workspace
still needs to save its own channel webhook and enable delivery. Verify current
readiness in the production Settings page after making changes; secret values
are not displayed by Cadivor.

The Railway cron is configured with `dry_run=true` and `cronSchedule` is
`0 */6 * * *`. Its latest observed scheduled execution (2026-11-19 18:00 UTC)
logged only `ok=true` and `status=accepted`; it did not log the required
`status=dry_run`, `supplier_calls=0`, `persisted=false`, and `email_sent=false`
result. Treat this as an unresolved readiness blocker. Do not switch the cron
to live mode until a naturally scheduled run records those dry-run fields and
the API readiness endpoint confirms the required settings.
