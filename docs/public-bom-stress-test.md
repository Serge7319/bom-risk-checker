# Anonymous BOM stress test rollout

The real `marketing-web/` homepage embeds the dedicated Streamlit route
`https://app.cadivor.com/?public=stress&embed=true`. The homepage section
is hidden until `window.CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED = true` is set
in `marketing-web/index.html` before `app.js` loads. The app route displays
the upload only when all three Railway settings are present:
`CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED=true`,
`CADIVOR_PUBLIC_BOM_HMAC_SECRET` (at least 32 random characters), and
`SUPABASE_SERVICE_ROLE_KEY`. Keep the enable flag off during setup.

1. Apply `supabase/migrations/20261003_public_bom_stress_test.sql` in the Cadivor
   Supabase project. Its private report and lead tables grant no access to the
   public `anon` or normal `authenticated` roles. Confirm the atomic reservation
   RPC can be called from the service role, and not from either public role.
2. Configure the **Supabase Magic Link email template** to contain a direct
   Cadivor verification link with the token hash, for example:
   `https://app.cadivor.com/?cadivor_signup_confirm=1&cadivor_stress_report=1&token_hash={{ .TokenHash }}&type=email`.
   Use the equivalent origin in staging and allow it in Supabase Auth Redirect
   URLs. This feeds the existing token-hash callback; the default implicit
   fragment URL cannot complete Cadivor's server-side confirmation. Test a new
   and an existing account before enabling the homepage hook.
3. Route **all** requests for `app.cadivor.com/*` through
   `infra/cloudflare/public_bom_visitor_worker.js`, including the Streamlit
   `/_stcore/stream` WebSocket. Bind the Worker secret
   `CADIVOR_PUBLIC_BOM_HMAC_SECRET`; set the same secret in Railway. The Worker
   overwrites the visitor header. Requests that bypass it cannot run a public
   audit. If Cloudflare is not the Cadivor ingress, port the same HMAC contract
   to the trusted ingress before enabling the funnel. A client-provided
   `X-Forwarded-For` or `st.context.ip_address` is insufficient for this limit.
4. Put `SUPABASE_SERVICE_ROLE_KEY` **only** on the server, never in HTML, the
   Worker, or client-side JavaScript. Set the enable flag last. Schedule a daily
   delete of report rows older than seven days, as described in the migration.
   Minimal sales leads (work email, row count, verified high-risk count, and
   unverified count) remain in `cadivor_public_bom_leads` after report removal.
5. Deploy the app and its public route first. Once steps 1–4 work, set the
   homepage JavaScript flag to `true` and deploy `marketing-web/`. Check that the uploader works in
   the homepage iframe from `www.cadivor.com` and in a full-page app view. The
   host must allow the iframe, its WebSocket, and Streamlit's uploader request;
   the two subdomains are same-site over HTTPS. Keep the full-page link visible
   for visitors whose browser blocks an embedded uploader. Authenticated
   workspaces continue to use Cadivor's normal BOM upload and are not subject
   to the two-per-IP public rate limit.

The preview checks up to 30 BOM rows, including all rows needed for an accurate
remaining-risk count, but sends complete supplier data for only the first five
to the anonymous browser. Supabase stores the full audit. A work email is
validated and logged as a lead. With consent, Supabase sends a passwordless
email link and provisions an account if the address is new. Cadivor's existing
token-hash callback verifies the link. Once verified and signed in, the user
lands on **Reports**, where the complete audit is available for seven days. Existing
account holders can switch to **Sign In** in that form.

This deliberately does **not** unlock the BOM on merely entering an email:
the owner must verify that address first. Supplier API evidence can be partial;
unverified rows are labeled as such and excluded from high-risk counts.

## Manual check after the ingress, migration, and application deploy

1. Open `www.cadivor.com` in a signed-out window and scroll to **Try your own
   BOM**. Upload a 6-row CSV with `MPN,Qty`
   columns. Inspect the teaser: exactly five component rows should be visible,
   with one row locked. In Network/Streamlit messages, the sixth row's MPN,
   stock, lead time, and lifecycle must not appear in a response.
2. Upload a second different BOM from the same connection; the second audit
   should work. Try a third within 24 hours; it should show the daily-limit
   message before any distributor lookup.
3. Enter `someone@gmail.com`; see a work-email validation error. Enter a real
   work email and accept the Terms; click **Email my full report**. Follow the
   one-time email link, continue to the workspace, and verify **Reports** opens
   with the complete audit and CSV export.
4. Sign in with another account and open Reports; it must not show the lead's
   audit. Test a supplier outage: affected rows say `Needs verification`, not
   `High` by inference from missing data.
