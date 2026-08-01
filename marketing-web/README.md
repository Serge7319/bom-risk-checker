# Cadivor Interactive Marketing Experience

Sprint 64 introduces a dedicated, zero-dependency public frontend for `cadivor.com` while preserving the existing Streamlit product for `app.cadivor.com`.

## Run locally

```bash
cd marketing-web
python3 -m http.server 3000
```

Open `http://localhost:3000`.

## Configure the application URL

By default, Sign In and Start Free Trial point to `https://app.cadivor.com`.
To override this before `app.js` loads, define:

```html
<script>window.CADIVOR_APP_URL = "https://your-streamlit-app.example.com";</script>
```

## Deployment

Upload the contents of `marketing-web/` to Cloudflare Pages, Vercel static hosting, Netlify, Railway, or any static host. Set the public domain to `cadivor.com`, and keep the current Streamlit deployment on `app.cadivor.com`.

No build step or JavaScript package installation is required.
