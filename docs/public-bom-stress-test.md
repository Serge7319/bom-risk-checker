# Public BOM stress test: launch checklist

The public uploader is live at https://app.cadivor.com/?public=stress. The homepage launch change enables the embedded uploader and points its **Analyze a BOM free** buttons to that route. Before sharing the homepage in outreach, complete the email-to-Reports check in step 7. Use the Supabase project and Railway production service already serving app.cadivor.com. Do not send API keys, the signing secret, or a live email link in chat.

**Expected visitor flow:** Upload a CSV/XLSX BOM (1–30 rows, up to 1 MB, with MPN and Qty columns), see the first five rows, verify a work email, then see the complete audit in Reports. There are two anonymous uploads per IP per rolling 24 hours. The full report expires after seven days and downloads as CSV; this feature does not generate a PDF.

## 1. Supabase: run the database migration

1. Open [Supabase Dashboard](https://supabase.com/dashboard). Select the **production project Cadivor uses**. If you have several projects, compare its project URL with the existing SUPABASE_URL in Railway. Do not change that variable.
2. Click **SQL Editor → New query**.
3. Open [the migration file on GitHub](https://github.com/Serge7319/bom-risk-checker/blob/main/supabase/migrations/20261003_public_bom_stress_test.sql), click **Raw**, copy all the SQL, paste it into the new query, and click **Run**.
4. Create a second query and run this read-only check:

~~~sql
select
  to_regclass('public.cadivor_public_bom_stress_tests') as reports,
  to_regclass('public.cadivor_public_bom_leads') as leads,
  has_function_privilege('anon', 'public.cadivor_reserve_public_bom_stress_test(text)', 'EXECUTE') as anonymous_can_reserve,
  has_function_privilege('authenticated', 'public.cadivor_reserve_public_bom_stress_test(text)', 'EXECUTE') as signed_in_can_reserve,
  has_function_privilege('service_role', 'public.cadivor_reserve_public_bom_stress_test(text)', 'EXECUTE') as server_can_reserve;
~~~

Expected: both table names appear; anonymous_can_reserve=false, signed_in_can_reserve=false, server_can_reserve=true. If the query fails or those values differ, leave the public feature disabled.

## 2. Supabase: schedule seven-day cleanup

Find **Cron → Jobs → Create job** in the Supabase sidebar (its placement can vary). Name the job **cadivor-public-bom-cleanup**, set the schedule below (daily at 03:00 UTC), choose **SQL snippet**, paste the delete query, and save:

~~~text
0 3 * * *
~~~

~~~sql
delete from public.cadivor_public_bom_stress_tests
where created_at < now() - interval '7 days';
~~~

Check that the job is Active. If Cron is unavailable, stop and tell me before enabling the feature. The separate minimal lead record remains after the detailed report is deleted.

## 3. Supabase: allow the return URL

Open **Authentication → URL Configuration → Redirect URLs**. Add this **exact new URL** and save:

~~~text
https://app.cadivor.com/?cadivor_signup_confirm=1&cadivor_stress_report=1
~~~

Keep all existing URLs and the existing Site URL. Cadivor sends this URL when requesting the verification email.

## 4. Supabase: check both email templates

New work-email addresses may receive **Confirm sign up**; existing accounts may receive **Magic Link**. The generic "Confirm your email" message is a verification email, not the full report. Both buttons need to reach Cadivor's token-hash callback so the verified visitor can continue to **Reports**.

1. Open **Authentication → Email Templates**. Make a private backup of **Confirm sign up** and **Magic Link or OTP** before editing either. Leave the other templates alone.
2. In each of those two templates, find the clickable link's `href`. Keep the surrounding layout and set the link to use the request-specific redirect:

~~~html
href="{{ .RedirectTo }}&amp;token_hash={{ .TokenHash }}&amp;type=email"
~~~

For example, a minimal anchor is:

~~~html
<a href="{{ .RedirectTo }}&amp;token_hash={{ .TokenHash }}&amp;type=email">Confirm email and continue to Cadivor</a>
~~~

3. Use a neutral subject/body that works for normal signup too, for example subject **Confirm your Cadivor email**, and text **Confirm your email to continue to Cadivor. If you requested a BOM audit, your full report is available in Reports after sign-in.** Save both templates. Do not hard-code `cadivor_stress_report=1` in a global template: `RedirectTo` already carries it for this request. This app supplies a redirect URL with existing query parameters, so appending `&amp;` is correct here. If other products share these templates with redirects lacking a query string, check those flows before applying this exact link globally.
4. The confirmation email's link should begin with the exact redirect URL in section 3, then include `token_hash` and `type=email`. Do not share the full live URL; it is a one-time sign-in credential. **Click it and verify the actual Reports result**; the appearance of an email alone does not complete the test.

## 5. Cloudflare: sign requests reaching the app

1. In **Cloudflare → cadivor.com → DNS**, inspect the app.cadivor.com record. A Worker Route requires the record to say **Proxied** (orange cloud). If it says **DNS only**, stop and send me a screenshot of the record before changing it. Leave the feature disabled; changing the production app's proxy path needs a separate check. Also check for an existing Worker Route on app.cadivor.com; if one exists, pause rather than replace it.
2. In **Workers & Pages**, create a Worker named, for example, **cadivor-public-bom-visitor**. Replace its starter code with the full [Worker source file](https://github.com/Serge7319/bom-risk-checker/blob/main/infra/cloudflare/public_bom_visitor_worker.js) and deploy it.
3. On your Mac, run **openssl rand -hex 32** in Terminal. Keep the 64-character output temporarily in a password manager. In the Worker's **Settings → Variables and Secrets → Add**, choose **Secret**, name it **CADIVOR_PUBLIC_BOM_HMAC_SECRET**, paste the value, and deploy the settings.
4. On that Worker, go to **Settings → Domains & Routes → Add → Route**. Zone: **cadivor.com**. Copy this exact route pattern, then save:

~~~text
app.cadivor.com/*
~~~

   The route must cover normal pages, uploader requests, and /_stcore/stream WebSocket traffic. Do not route www.cadivor.com through this Worker.
5. With the public flag still off, test normal app sign-in and open a saved BOM. If the app fails to connect, disable the new Worker Route and report the error before proceeding.

## 6. Railway: enable the public upload

1. Open the **production environment** in Railway and the app service serving app.cadivor.com. Go to **Variables**.
2. Keep SUPABASE_URL and SUPABASE_KEY unchanged. If SUPABASE_SERVICE_ROLE_KEY is already present, leave it. Otherwise get the **service_role** key from the same Supabase project's **Settings → API Keys** and add it as **SUPABASE_SERVICE_ROLE_KEY**. Do not use the anon/publishable key. Keep this key server-side only.
3. Add **CADIVOR_PUBLIC_BOM_HMAC_SECRET** with the **identical secret from step 5**. It must be at least 32 characters.
4. Add **CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED** with value **true** last. Review Railway's staged changes and deploy. Wait for a successful production deployment.

Open [the direct stress-test route](https://app.cadivor.com/?public=stress) in a signed-out window. It should now show an uploader. If it still says "being prepared," check the three Railway variables and deploy status. If upload fails with a connection message, check the Worker Route and matching secrets. Do not expose the marketing section yet.

## 7. Test with a six-row CSV

Create a local file named cadivor-stress-test.csv with these contents:

~~~csv
MPN,Qty
LM358N,10
MCP2551-I/SN,2
TPS5430DDAR,5
W25Q64JVSSIQ,3
SN74LVC2T45DCUR,4
ADS1115IDGSR,2
~~~

1. In a fresh incognito window, upload it on the direct route. Expect **five visible component rows and one locked row**. The sixth MPN must not appear in the anonymous results.
2. Try test@gmail.com; expect a work-email error. Then use a work email you control, accept the Terms, and click **Email my full report**. Follow the one-time email link and continue to the workspace. In **Reports**, expect six components and **Download audit CSV**.
3. From the same network, a second anonymous upload should work and a third within 24 hours should show the daily-limit message. Check email confirmation for both a new and an existing account. Rows without verified distributor data must say **Needs verification**.
4. Sign into another account and confirm it cannot view the first person's full report.

## 8. Enable and deploy the marketing homepage

The homepage flag is set in `marketing-web/index.html` by the launch change:

~~~html
window.CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED = true;
~~~

After step 7 passes, deploy the launch change to both the app and `marketing-web/` through their existing release processes. In a signed-out window open [www.cadivor.com](https://www.cadivor.com/). Click **Analyze a BOM free** in the hero and desktop/mobile navigation; each should open the branded anonymous uploader at https://app.cadivor.com/?public=stress instead of signup. The homepage's embedded **Try your own BOM** uploader uses the homepage header, while the full-page route has its own Cadivor header. Test both the embedded uploader and **Open the stress test in a full page** link. Share the homepage in outreach after the confirmed-email route unlocks the six-row audit in Reports.

## Send me only the checkpoint result

For example: "Step 1 returned two table names and false/false/true"; "Cron active"; "Auth URL/template saved"; "app DNS Proxied"; "Worker route installed and normal app works"; "Railway deployed"; "six-row test passed." Screenshots are useful when a dashboard label differs. Hide all keys, signing secrets, live email links, and customer BOM contents.
