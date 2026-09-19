# Cadivor Email Delivery Audit

This document is the production contract for inbound routing and
application-generated email. It intentionally separates code-controlled
behavior from settings that must be verified in Google Workspace, Supabase,
Resend, Stripe, Railway, and the scheduled-monitoring workflow.

## Inbound routing

| Request | Destination |
|---|---|
| General inquiries, demos, student access | `info@cadivor.com` |
| Beta invitations and launch blockers | `beta@cadivor.com` |
| Customer and product help | `support@cadivor.com` |
| Security and responsible disclosure | `security@cadivor.com` |
| Legal, terms, and privacy | `legal@cadivor.com` |
| Stripe and subscription help | `billing@cadivor.com` |

Public marketing, authenticated pricing/settings, maintenance, security,
privacy, terms, and help surfaces use this mapping. Keep the canonical Python
constants in `src/email_routing.py` synchronized with the static marketing
site mapping in `marketing-web/app.js`.

## Application-generated email

### Workspace invitations

- Workspace owners and admins can create and resend invitations.
- Cadivor submits the email through Resend using the authenticated recipient
  address and the configured verified-domain sender.
- The invitation opens Cadivor's Workspace page.
- The database accepts only pending, unexpired invitations matching the email
  in the authenticated user's Supabase JWT.
- Invitation controls remain disabled until both the database acceptance RPC
  and minimum Resend configuration are available.

Apply this migration before enabling the flow:

`supabase/migrations/20260919_workspace_invitation_acceptance.sql`

### Monitoring alerts

- Only high-severity monitoring alerts generate email.
- Both `email_notifications` and `monitoring_notifications` must be enabled in
  `user_preferences`.
- A preference-read error fails closed and sends no email.
- Existing duplicate suppression remains active.
- The scheduled job does not log recipient email addresses.

Use `SUPABASE_SERVICE_ROLE_KEY` only in the server-side scheduled job so it can
read preferences for all users. The legacy `SUPABASE_KEY` fallback remains for
deployment continuity, but the dedicated server-only secret is preferred.

## Required runtime configuration

| Variable | Example / purpose |
|---|---|
| `RESEND_API_KEY` | Resend API key |
| `TRANSACTIONAL_FROM_EMAIL` | `Cadivor <no-reply@cadivor.com>` |
| `ALERT_FROM_EMAIL` | `Cadivor Alerts <no-reply@cadivor.com>` |
| `EMAIL_REPLY_TO` | `support@cadivor.com` |
| `CADIVOR_APP_ORIGIN` | `https://app.cadivor.com` |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only scheduled-monitoring credential |

Do not use Resend's sandbox sender in production.

## Provider verification

These checks require access to the provider dashboards and cannot be proven by
repository tests alone.

### Google Workspace

- Confirm every inbound alias delivers to the intended monitored mailbox.
- Send a new external test message to each alias after Google propagation.
- Confirm reply behavior and any routing/group rules.

### Resend

- Confirm `cadivor.com` shows as verified and all required DNS records pass.
- Confirm the configured sender uses the verified domain.
- Send one workspace invitation and one monitoring test to an authorized test
  recipient; verify delivery, reply-to, and provider event status.

### Supabase Auth

- Configure custom SMTP for production rather than the default development
  mail service.
- Set the sender to a verified Cadivor-domain identity.
- Confirm the production site URL and allowed redirect URLs include
  `https://app.cadivor.com/**`.
- Test signup confirmation and password recovery end to end.

### Stripe

- Confirm Checkout receives the authenticated customer's email; Cadivor passes
  it as `customer_email` when creating a session.
- In both test and live mode, verify Stripe customer email settings for
  receipts, invoices, failed payments, and trial/subscription notices.
- Set the public billing support contact to `billing@cadivor.com`.
- Confirm the Customer Portal return URL uses the production app origin.

## Deployment order

1. Confirm Google alias delivery.
2. Verify the Resend domain and sender.
3. Apply the workspace invitation-acceptance migration.
4. Add the runtime and scheduled-job variables above.
5. Configure Supabase custom SMTP and redirect URLs.
6. Configure Stripe customer emails and billing support in test and live mode.
7. Deploy Cadivor.
8. Run the end-to-end tests listed above with authorized test accounts.
