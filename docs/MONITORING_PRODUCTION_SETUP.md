# Monitoring production setup

Monitoring stays off until the API and scheduled workflow both have their
configuration. The scheduler runs every six hours and can make live distributor
requests. It processes only saved BOMs whose workspace members opted into
supplier checks. Alert email also requires the workspace/member email
preferences and the separate email gate.

## Railway production API

Add these variables to the \`cadivor-next-api-prod\` service in the
\`production\` environment:

| Variable | Value |
| --- | --- |
| \`CADIVOR_MONITORING_SCHEDULER_ENABLED\` | \`1\` |
| \`CADIVOR_MONITORING_SCHEDULE_ATTACHED\` | \`1\` |
| \`CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED\` | \`1\` |
| \`CADIVOR_MONITORING_CRON_TOKEN\` | A long random secret also stored in GitHub Actions |
| \`CADIVOR_MONITORING_EMAIL_ENABLED\` | \`1\`, only after Resend setup below |
| \`RESEND_API_KEY\` | Resend production API key |
| \`TRANSACTIONAL_FROM_EMAIL\` | Sender on the verified \`cadivor.com\` domain |

Use the existing verified supplier credentials. Do not include the cron token
or Resend API key in commits, issue comments, or screenshots.

## GitHub Actions

In repository **Settings → Secrets and variables → Actions**:

- Add repository variables \`CADIVOR_MONITORING_SCHEDULER_ENABLED\` and
  \`CADIVOR_MONITORING_SCHEDULE_ATTACHED\`; each accepts \`true\` or \`1\`.
- Set \`CADIVOR_API_BASE\` to the production API origin.
- Add secret \`CADIVOR_MONITORING_CRON_TOKEN\` with exactly the same value as
  the Railway API variable.

The protected endpoint rejects requests unless the token matches. The scheduled
workflow is disabled when either GitHub variable is missing or false.

## Email and first run

Verify the sender/domain in Resend before setting the email flag. Then enable
email preferences only for the intended test workspace and verify a single
alert to an authorized test recipient. Do not use a scheduled production run
as a delivery test: schedule runs are live, while manual dispatch defaults to
\`dry_run=true\`.
