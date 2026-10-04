# One-time BOM report rollout

This offer uses Cadivor's existing BOM Analyzer and Reports workspace. A verified Cadivor account with no active analysis entitlement can buy **one full analysis for up to 100 unique components**, with the standard PDF/CSV reports for that saved BOM. It does not start a subscription. The account is needed to retrieve and revisit the private report. The free anonymous audit at `https://www.cadivor.com/#/analyze` remains free and separate.

**Code deployment is safe with the offer disabled.** The purchase button requires `CADIVOR_ONE_TIME_BOM_ORDERS_READY=true` (set only after the SQL migration), `CADIVOR_ONE_TIME_BOM_REPORT_ENABLED=true`, `STRIPE_ONE_TIME_BOM_REPORT_PRICE_ID=price_...`, and the existing server-side `SUPABASE_SERVICE_ROLE_KEY`. Both flags default to off. The button shows the active, nonrecurring Stripe price amount before checkout; misconfigured or unavailable pricing blocks purchase.

Turning the flag off stops **new** checkouts. Existing paid credits remain redeemable while the service-role database connection is available.

## Preconditions before enabling a test purchase

1. Confirm the **existing** Stripe subscription webhook is working in a Stripe sandbox. `supabase/functions/stripe-webhook/index.ts` is versioned source; the repository's deployment notes say it has **not** replaced the live exported function. Do not assume merging this PR deploys it. The existing live destination must safely ignore `mode=payment` Checkout events, or it will retry every one-time payment as a missing subscription.
2. Inspect the live `stripe_webhook_events` schema. If the lease RPCs from `supabase/migrations/20260912_stripe_webhook_event_lease.sql` are not installed, review and apply that earlier migration first. It deliberately refuses to invent a missing live table. Verify normal Starter/Professional/Business checkout and renewal in sandbox afterward.
3. In the same Supabase project, run `supabase/migrations/20261004_one_time_bom_reports.sql` in SQL Editor. Confirm `public.users.id`, `public.analyses.id`, and `public.analyses.user_id` are UUID columns before applying. The migration creates private orders and service-only atomic fulfillment/reserve/consume RPCs. No anonymous or authenticated PostgREST role can read or write the order table. Set `CADIVOR_ONE_TIME_BOM_ORDERS_READY=true` on the corresponding Railway service after this migration succeeds; leave the sales flag off.
4. Deploy the versioned `stripe-webhook` function to a **sandbox** Stripe destination with its existing secret/JWT settings. Subscribe that destination to `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, and `checkout.session.expired`, plus the existing subscription/invoice events. The function must receive the correct sandbox `STRIPE_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY`. Keep production configuration off while testing.
5. Create a **one-time, nonrecurring USD** Price in Stripe test mode. Set its `price_...` ID in Railway staging as `STRIPE_ONE_TIME_BOM_REPORT_PRICE_ID`; set `CADIVOR_ONE_TIME_BOM_REPORT_ENABLED=true` only there. Finance must decide the amount and any refund/tax policy. The code does not hardcode a price.

## Sandbox acceptance test

1. Sign in to a test account whose trial has expired (or whose subscription is inactive). Open **BOMs → New analysis**. Expect **Buy one BOM report · USD [Stripe amount]**, the 100-component limit, and a **Compare plans** alternative. No report credit should exist yet.
2. Open the Stripe checkout and pay with a Stripe test card. The browser returns to **BOM Analyzer**; while the webhook is processing, it may say to refresh. In Supabase, check this user's private order moves `pending → paid`, with `stripe_session_id` and `payment_intent_id`. A browser return alone must never mark it paid.
3. Upload a CSV or XLSX with `MPN` and `Qty`, click **Analyze BOM**, and wait for the saved analysis. The order moves `paid → reserved → consumed` and stores the matching `analysis_id`. **Analysis Details** opens; **Reports** must provide the same PDF and CSV packages as a subscription analysis. The BOM Analyzer's Excel download must contain only this BOM.
4. Open **BOMs → New analysis** again. Another analysis must require another payment or a subscription. An upload with 101 distinct MPNs must be blocked before supplier lookups and must leave the paid credit available.
5. Cancel an in-progress analysis or induce a supplier analysis failure. The order should return from `reserved` to `paid` and be usable again. A browser crash may hold a reservation for up to four hours; a stale reservation is recoverable on the next analysis attempt. A persistence error should never silently consume a second credit.
6. Repeat the paid event delivery, then deliver an unpaid `checkout.session.completed` and a failed delayed payment in sandbox. Only a paid event for the same stored order, Stripe Session, user, and Price can grant a credit. Existing subscription checkout must still activate only its subscription plan.
7. Sign into a different account and confirm it cannot see, reserve, or consume the first account's purchase or saved BOM. Check the order table is unreadable with the anon and authenticated API keys.

After this passes, deploy the webhook to the live destination under the normal release procedure, create a live one-time Price, repeat one controlled live purchase and report retrieval, then enable the Railway production flag. The marketing homepage can get a direct one-time offer only after the live path is proven. Never share Stripe keys, webhook secrets, customer BOMs, or sign-in links in a support message.

## Operational notes

- The webhook is the only grant path. Duplicate events return an idempotent outcome. A pending session can be reopened; a completed session awaiting the webhook cannot trigger a second purchase from the page.
- A full saved analysis consumes its credit after component records are written. Reports remain accessible under the existing saved-work policy when a trial ends.
- A failed save after its summary is created attempts to remove the incomplete summary and restore the credit. If database reconciliation fails, the user sees a support error and the private order remains auditable.
- Orders contain IDs and status, not a copy of the BOM. The existing saved BOM workspace owns the analysis data and its access policy.
