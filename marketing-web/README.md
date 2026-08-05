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

## Application and marketing URLs

Configure these optional globals before `app.js` loads:

```html
<script>
  window.CADIVOR_APP_ORIGIN = 'https://app.cadivor.com';
  window.CADIVOR_MARKETING_ORIGIN = 'https://www.cadivor.com';
</script>
```

If unset, Sign In and trial links default to the verified Streamlit Cloud deployment. The marketing origin defaults to the current site origin when served locally.

The Python app uses the same concepts via environment variables:

- `CADIVOR_MARKETING_ORIGIN` (default `https://www.cadivor.com`)
- `CADIVOR_APP_ORIGIN` (default Streamlit Cloud production URL)

## Deployment

This is a zero-build static site. Deploy `marketing-web/` as the site root on Cloudflare Pages, Vercel, Netlify, Railway, or another static host.

## Premium v1.0 recovery
This release is based on the full Experience Engine rather than the stripped-down Premium regression. The marketing site remains a zero-build static frontend. Keep the Streamlit product deployed separately and configure the application URL before production deployment.
