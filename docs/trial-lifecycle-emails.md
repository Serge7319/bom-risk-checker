# Trial lifecycle emails

The trial onboarding sequence runs as a separate daily GitHub Actions workflow. It does not share or change the six-hour monitoring schedule.

## Messages

- Day 0: welcome and start the first BOM review
- Day 2: use the sample BOM
- Day 7: create a decision record and consider monitoring
- Day 12: trial expiry reminder

The sender processes only verified, non-admin accounts whose current plan is Trial. It skips trials that started before the configured launch timestamp, so enabling the sequence does not backfill emails to existing trial users. The send ledger is idempotent per account and milestone.

## Configuration

Deploy the `trial-lifecycle-emails` Supabase function and apply its migration first. Keep the sequence disabled until email delivery and the scheduler are ready.

Set these Supabase function secrets:

- `CADIVOR_TRIAL_EMAIL_CRON_TOKEN`: a new random token used only by this job
- `RESEND_API_KEY`: the transactional email provider credential
- `TRANSACTIONAL_FROM_EMAIL`: a verified sender address
- `CADIVOR_TRIAL_EMAIL_SEQUENCE_ENABLED`: `true` to enable sends
- `CADIVOR_TRIAL_EMAIL_SEQUENCE_LAUNCH_AT`: UTC ISO timestamp; trials started before this time are excluded

Set these GitHub repository values:

- Variable `CADIVOR_TRIAL_EMAIL_SEQUENCE_ENABLED`: `true` to enable the scheduled workflow
- Variable `CADIVOR_SUPABASE_URL`: the project's Supabase URL
- Secret `CADIVOR_TRIAL_EMAIL_CRON_TOKEN`: the same job token as the Supabase function secret

The function rejects requests without the job token. The workflow reports only aggregate counts and never prints recipient addresses or secret values.
