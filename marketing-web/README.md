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
- `#/product`
- `#/solutions`
- `#/pricing`
- `#/resources`
- `#/company`
- `#/contact`
- `#/security`
- `#/privacy`
- `#/terms`

## Application URL

The frontend defaults Sign In and trial links to `https://app.cadivor.com`. To override it before `app.js` loads, set:

```html
<script>window.CADIVOR_APP_URL = 'https://your-streamlit-url.example';</script>
```

## Deployment

This is a zero-build static site. Deploy `marketing-web/` as the site root on Cloudflare Pages, Vercel, Netlify, Railway, or another static host.

## Premium v1.0 recovery
This release is based on the full Experience Engine rather than the stripped-down Premium regression. The marketing site remains a zero-build static frontend. Keep the Streamlit product deployed separately and configure the application URL before production deployment.
