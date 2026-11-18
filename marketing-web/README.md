# Cadivor Interactive Marketing Website

This folder is the dedicated public frontend for `cadivor.com`. The existing Streamlit application remains the authenticated product and should be deployed at `app.cadivor.com`.

## Run locally

```bash
cd marketing-web
python3 -m http.server 3000
```

Open `http://localhost:3000/#/home`.

## Routes

- `#/home`
- `#/analyze` (free anonymous BOM audit)
- `#/one-time-report` (one-time report details and report-only account checkout entry)
- `#/product`
- `#/solutions`
- `#/pricing`
- `#/resources`
- `#/company`
- `#/contact`
- `#/security`
- `#/privacy`
- `#/terms`

## Application and marketing URLs

Configure these optional globals before `app.js` loads:

```html
<script>
  window.CADIVOR_APP_ORIGIN = 'https://app.cadivor.com';
  window.CADIVOR_MARKETING_ORIGIN = 'https://www.cadivor.com';
</script>
```

If unset, Sign In and trial links default to `https://app.cadivor.com`. The marketing origin defaults to `https://www.cadivor.com`.

The Python app uses the same concepts via environment variables:

- `CADIVOR_MARKETING_ORIGIN` (default `https://www.cadivor.com`)
- `CADIVOR_APP_ORIGIN` (default `https://app.cadivor.com`)

The contact, demo, and student request form posts to
`{CADIVOR_APP_ORIGIN}/api/public/contact`. The API stores the request in the
migration Postgres database and emails the appropriate Cadivor inbox through
the configured transactional email provider. Resend must have an API key and
a verified sender configured before automatic notifications can be sent. On
the Railway API service, set `RESEND_API_KEY` and `TRANSACTIONAL_FROM_EMAIL`
(or the supported `CADIVOR_FROM_EMAIL` fallback). Verify the sending domain in
Resend and publish the SPF, DKIM, and DMARC records it provides in the DNS host
for that domain before relying on delivery. If
delivery is unavailable, the page tells the visitor that the request was saved
and provides an email fallback.

First-party marketing events are optional and remain off until a visitor accepts
the analytics choice on the marketing site or app. The API stores a strict event
allowlist and aggregate UTM attribution in the migration Postgres database;
records are retained for up to 180 days. Only verified platform admins can view
the funnel at `/admin/marketing-analytics`.

## Crawlable static pages

The root marketing experience remains a client-side site, with crawlable pages at `/product/`, `/solutions/` (including role pages), `/pricing/`, `/resources/`, `/security/`, `/privacy/`, and `/terms/`. Each page has a canonical URL and server-delivered content. `robots.txt` points crawlers to `sitemap.xml`. These direct pages reuse the current product copy and do not rely on JavaScript for their main content.

## Deployment

This is a zero-build static site. Deploy `marketing-web/` as the site root on Cloudflare Pages, Vercel, Netlify, Railway, or another static host.

## Premium v1.0 recovery
This release is based on the full Experience Engine rather than the stripped-down Premium regression. The marketing site remains a zero-build static frontend. Keep the Streamlit product deployed separately and configure the application URL before production deployment.
