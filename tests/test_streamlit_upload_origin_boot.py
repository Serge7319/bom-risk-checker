"""Production upload CORS origin must match https://app.cadivor.com."""
from __future__ import annotations

import importlib.util
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "scripts" / "cadivor_streamlit_boot.py"
RAILWAY = ROOT / "scripts" / "railway_start.sh"
CONFIG = ROOT / ".streamlit" / "config.toml"
WORKER = ROOT / "infra" / "cloudflare" / "public_bom_visitor_worker.js"


def _load_boot():
    spec = importlib.util.spec_from_file_location("cadivor_streamlit_boot", BOOT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StreamlitUploadOriginBootTests(unittest.TestCase):
    def test_railway_start_keeps_cors_and_xsrf_enabled(self) -> None:
        start = RAILWAY.read_text(encoding="utf-8")
        self.assertIn("scripts/cadivor_streamlit_boot.py", start)
        self.assertNotIn("enableCORS=false", start)
        self.assertNotIn("enableXsrfProtection=false", start)
        config = CONFIG.read_text(encoding="utf-8")
        self.assertIn('corsAllowedOrigins = ["https://app.cadivor.com"]', config)
        self.assertIn("enableXsrfProtection = true", config)
        self.assertIn("enableCORS = true", config)

    def test_boot_patch_forces_https_origin_and_secure_xsrf_cookie(self) -> None:
        boot = _load_boot()
        server_util = types.SimpleNamespace(get_url=lambda host: f"http://{host}:443")
        cookies: list[dict] = []

        def _set_cookie(response, name, value, *, same_site="Lax", secure=False):
            cookies.append(
                {
                    "name": name,
                    "same_site": same_site,
                    "secure": secure,
                    "response": response,
                }
            )
            return response

        routes = types.SimpleNamespace(
            get_url=server_util.get_url,
            _set_unquoted_cookie=_set_cookie,
            XSRF_COOKIE_NAME="_streamlit_xsrf",
        )
        origin = boot.apply_streamlit_public_origin_patches(
            origin="https://app.cadivor.com",
            get_url_module=server_util,
            routes_module=routes,
        )
        self.assertEqual(origin, "https://app.cadivor.com")
        self.assertEqual(server_util.get_url("app.cadivor.com"), "https://app.cadivor.com")
        self.assertEqual(routes.get_url("app.cadivor.com"), "https://app.cadivor.com")
        self.assertNotIn(":443", routes.get_url("app.cadivor.com"))
        self.assertFalse(routes.get_url("app.cadivor.com").startswith("http://"))

        routes._set_unquoted_cookie(object(), "_streamlit_xsrf", "2|mask|token|1", same_site="Lax", secure=False)
        self.assertTrue(cookies[-1]["secure"])

    def test_cloudflare_worker_rewrites_bad_upload_acao(self) -> None:
        worker = WORKER.read_text(encoding="utf-8")
        self.assertIn('out.set("Access-Control-Allow-Origin", "https://app.cadivor.com")', worker)
        self.assertIn("_streamlit_xsrf=", worker)
        self.assertIn("Secure", worker)


class ComparePartsTimeoutContractTests(unittest.TestCase):
    def test_live_compare_has_bounded_timeout_copy(self) -> None:
        source = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
        self.assertIn("COMPARE_PARTS_JOB_TIMEOUT_SECONDS = 90", source)
        status = source.split("def _render_compare_parts_job_status", 1)[1].split(
            "def render_compare_live", 1
        )[0]
        self.assertIn("after 90 seconds", status)
        self.assertIn("Search time:", status)
        self.assertNotIn("API", status)


if __name__ == "__main__":
    unittest.main()
