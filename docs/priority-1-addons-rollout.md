# Priority 1 add-ons and access controls

Annual plan prices are separate from these optional add-ons. This setup does not change plan prices or the monitoring schedule.

## Stripe products still needed

Create three Stripe products and prices in the same mode as the active Cadivor subscriptions:

| Product | Stripe price type | Cadivor environment setting |
| --- | --- | --- |
| BOM analysis overage pack | One-time, USD | STRIPE_BOM_ANALYSIS_OVERAGE_PRICE_ID |
| Monitored parts overage pack | One-time, USD | STRIPE_MONITORED_PARTS_OVERAGE_PRICE_ID |
| Professional API access | Monthly recurring, USD | STRIPE_PROFESSIONAL_API_ADDON_PRICE_ID |

For the two one-time packs, also set the included unit counts:

- CADIVOR_BOM_ANALYSIS_OVERAGE_CREDITS: positive whole number of analyses
- CADIVOR_MONITORED_PARTS_OVERAGE_CREDITS: positive whole number of monitored-part slots

Cadivor reads the amount and currency from Stripe and displays them in Settings. Pack sizes and prices are not guessed. The API add-on is available only with an active Professional subscription.

## Deploy and enable

1. Apply supabase/migrations/20261119150000_stripe_usage_addons.sql.
2. Deploy the updated subscription-checkout and stripe-webhook Edge Functions.
3. Set the five Stripe / pack-size settings above in Supabase Function secrets.
4. Confirm the existing Stripe webhook subscription includes checkout.session.completed, checkout.session.async_payment_succeeded, checkout.session.async_payment_failed, checkout.session.expired, and the subscription lifecycle events already used by Cadivor.
5. Verify test-mode checkout and webhook fulfillment before setting live-mode prices.

No annual plan price is changed by these steps.

The Professional API add-on unlocks developer API keys for workspace-scoped BOM
analysis submissions and report reads. API keys are revocable. Apply the
migration and deploy `subscription-checkout` before creating keys. Endpoint and
key behavior are documented in `developer-api.md`.

## Slack

Set CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY on the Cadivor API service to a Fernet key generated in a trusted secrets manager. Do not paste it into chat or commit it. Workspace owners/admins can then connect a Slack incoming webhook from Monitoring. The webhook URL is stored encrypted; posted messages include only aggregate alert counts and a link back to Cadivor.

## Trial email sequence

Deploy trial-lifecycle-emails, apply its migration, and configure its sender, launch timestamp, and separate cron token as documented in trial-lifecycle-emails.md. The sequence remains disabled until its explicit enable flags are set.
