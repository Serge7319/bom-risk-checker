#!/usr/bin/env python3
"""Start Streamlit with a public HTTPS origin for TLS-terminated Railway.

Streamlit 1.60 builds the XSRF-protected upload CORS origin via
``get_url(browser.serverAddress)``. Without ``server.sslCertFile`` that helper
emits ``http://app.cadivor.com:443``, which does not match the browser Origin
``https://app.cadivor.com``. Credentialed Axios PUT to ``/_stcore/upload_file``
then fails as a Network Error before bytes reach the server.

This boot path keeps CORS and XSRF enabled. It only forces the public HTTPS
origin used for upload ACAO and the Secure flag on the XSRF cookie.
"""
from __future__ import annotations

import os
import sys
from typing import Callable


def public_app_origin() -> str:
    raw = str(os.environ.get("CADIVOR_APP_ORIGIN") or "https://app.cadivor.com").strip()
    origin = raw.rstrip("/")
    if not origin.startswith("https://"):
        raise SystemExit(
            "CADIVOR_APP_ORIGIN must be an https:// URL for production uploads."
        )
    return origin


def apply_streamlit_public_origin_patches(
    *,
    origin: str | None = None,
    get_url_module=None,
    routes_module=None,
) -> str:
    """Patch Streamlit upload origin helpers. Returns the origin applied."""
    applied = (origin or public_app_origin()).rstrip("/")

    if get_url_module is None:
        from streamlit.web.server import server_util as get_url_module
    if routes_module is None:
        from streamlit.web.server.starlette import starlette_routes as routes_module

    def _public_get_url(_host_ip: str) -> str:
        return applied

    get_url_module.get_url = _public_get_url
    # starlette_routes imported get_url by name; patch that binding too.
    routes_module.get_url = _public_get_url

    original_set_cookie: Callable = routes_module._set_unquoted_cookie

    def _set_unquoted_cookie_secure(
        response,
        cookie_name: str,
        cookie_value: str,
        *,
        same_site: str = "Lax",
        secure: bool = False,
    ):
        cookie = str(cookie_name or "")
        xsrf_name = getattr(routes_module, "XSRF_COOKIE_NAME", "_streamlit_xsrf")
        if cookie == xsrf_name and applied.startswith("https://"):
            secure = True
        return original_set_cookie(
            response,
            cookie_name,
            cookie_value,
            same_site=same_site,
            secure=secure,
        )

    routes_module._set_unquoted_cookie = _set_unquoted_cookie_secure
    return applied


def apply_light_boot_splash() -> bool:
    """Force a branded light canvas before Streamlit's JS theme hydrates.

    Marketing → app cold loads otherwise flash Streamlit's dark skeleton
    (#0e1117) or an empty white frame before the Login card mounts. The
    Nov 2 recordings captured both: a dark AppSkeleton and a pure-white
    blank lasting multiple frames after HTML arrived.
    """
    try:
        import re
        from pathlib import Path

        import streamlit

        index = Path(streamlit.__file__).resolve().parent / "static" / "index.html"
        if not index.is_file():
            return False
        text = index.read_text(encoding="utf-8")
        style_marker = 'id="cadivor-light-boot"'
        splash_marker = 'id="cadivor-boot-splash"'
        style = (
            f"<style {style_marker}>"
            "html,body,#root,.stApp,[data-testid='stAppViewContainer']{"
            "background:#F5F7FB!important;color-scheme:light!important}"
            ".stAppSkeleton,[data-testid='stAppSkeleton']{"
            "display:none!important;visibility:hidden!important}"
            "#cadivor-boot-splash{position:fixed;inset:0;z-index:2147483000;"
            "display:flex;align-items:center;justify-content:center;"
            "background:#F5F7FB;color:#0F172A;"
            "font:650 14px/1.45 Inter,ui-sans-serif,system-ui,sans-serif}"
            "#cadivor-boot-splash .cv-boot-card{min-width:280px;max-width:360px;"
            "padding:28px 30px;border-radius:18px;background:#fff;"
            "border:1px solid #E2E8F0;box-shadow:0 24px 60px rgba(15,23,42,.08);"
            "text-align:center}"
            "#cadivor-boot-splash .cv-boot-mark{width:40px;height:40px;"
            "margin:0 auto 14px;border-radius:10px;background:#2563EB;color:#fff;"
            "display:grid;place-items:center;font:800 18px/1 Inter,system-ui,sans-serif}"
            "#cadivor-boot-splash .cv-boot-title{margin:0 0 6px;"
            "font:800 18px/1.2 Inter,system-ui,sans-serif;color:#0F172A}"
            "#cadivor-boot-splash .cv-boot-copy{margin:0;color:#64748B;"
            "font:550 13px/1.45 Inter,system-ui,sans-serif}"
            "</style>"
        )
        body = (
            f'<div {splash_marker} data-testid="cadivor-boot-splash" aria-live="polite">'
            '<div class="cv-boot-card">'
            '<div class="cv-boot-mark" aria-hidden="true">C</div>'
            '<p class="cv-boot-title">Cadivor</p>'
            '<p class="cv-boot-copy">Loading your workspace…</p>'
            "</div></div>"
            "<script id=\"cadivor-boot-splash-retire\">"
            "(function(){"
            "var splash=document.getElementById('cadivor-boot-splash');"
            "if(!splash)return;"
            "var done=false;"
            "function hide(){"
            "if(done||!splash)return;done=true;"
            "splash.style.opacity='0';"
            "splash.style.pointerEvents='none';"
            "splash.style.transition='opacity .18s ease';"
            "setTimeout(function(){if(splash&&splash.parentNode)"
            "splash.parentNode.removeChild(splash);},220);"
            "}"
            "function ready(){"
            "try{"
            "if(document.querySelector("
            "'.cv-auth-gate,[data-testid=\"cadivor-auth-gate\"],"
            "input[type=\"password\"]'"
            "))return true;"
            "var text=(document.body&&document.body.innerText||'')"
            ".replace(/\\s+/g,' ');"
            "if(/Access your workspace|Good afternoon|Analyzing BOM|"
            "New BOM analysis|Preparing your workspace|Opening Dashboard|"
            "Signing you in|Restoring your session|Manage saved BOMs/"
            ".test(text))"
            "return true;"
            "}catch(e){}"
            "return false;"
            "}"
            "var iv=setInterval(function(){if(ready()){clearInterval(iv);hide();}},50);"
            "setTimeout(function(){clearInterval(iv);hide();},12000);"
            "})();"
            "</script>"
        )
        # Replace any prior Cadivor boot fragments so redeploys upgrade the splash.
        text = re.sub(
            r"<style id=\"cadivor-light-boot\"[^>]*>.*?</style>",
            "",
            text,
            flags=re.DOTALL,
        )
        start = text.find('<div id="cadivor-boot-splash"')
        if start >= 0:
            end_script = text.find("</script>", start)
            if end_script >= 0 and 'id="cadivor-boot-splash-retire"' in text[start:end_script]:
                text = text[:start] + text[end_script + len("</script>") :]
            else:
                # Fallback: drop through the splash root by balancing div tags.
                i = start
                depth = 0
                while i < len(text):
                    if text.startswith("<div", i):
                        depth += 1
                        i = text.find(">", i) + 1
                        continue
                    if text.startswith("</div>", i):
                        depth -= 1
                        i += len("</div>")
                        if depth == 0:
                            text = text[:start] + text[i:]
                            break
                        continue
                    i += 1
        text = re.sub(
            r"<script id=\"cadivor-boot-splash-retire\">[\s\S]*?</script>",
            "",
            text,
        )
        if "</head>" not in text or "<body>" not in text:
            return False
        text = text.replace("</head>", style + "</head>", 1)
        text = text.replace("<body>", "<body>" + body, 1)
        index.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


def main() -> None:
    if "PORT" not in os.environ or not str(os.environ.get("PORT") or "").strip():
        raise SystemExit("Missing required environment variable: PORT")

    apply_streamlit_public_origin_patches()
    apply_light_boot_splash()

    from streamlit.web.cli import main as streamlit_main

    sys.argv = [
        "streamlit",
        "run",
        "streamlit_app.py",
        "--server.address=0.0.0.0",
        f"--server.port={os.environ['PORT']}",
        "--server.headless=true",
        "--server.enableCORS=true",
        "--server.enableXsrfProtection=true",
        "--browser.serverAddress=app.cadivor.com",
        "--browser.serverPort=443",
        "--browser.gatherUsageStats=false",
    ]
    streamlit_main()


if __name__ == "__main__":
    main()
