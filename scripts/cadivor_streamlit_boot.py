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


def main() -> None:
    if "PORT" not in os.environ or not str(os.environ.get("PORT") or "").strip():
        raise SystemExit("Missing required environment variable: PORT")

    apply_streamlit_public_origin_patches()

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
