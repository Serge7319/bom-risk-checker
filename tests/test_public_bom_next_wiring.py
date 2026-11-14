"""Source-level wiring for the Next.js anonymous public BOM audit."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]


class PublicBomNextWiringTests(unittest.TestCase):
    def test_middleware_redirect_preserves_non_public_query_params(self):
        middleware = (ROOT / "apps/web/src/middleware.ts").read_text()
        self.assertIn('pathname = "/public-bom-audit"', middleware)
        self.assertIn('searchParams.delete("public")', middleware)
        self.assertIn("request.nextUrl.clone()", middleware)
        # Simulate the redirect contract: keep embed + UTM, drop only public=.
        source = "https://app.cadivor.com/?public=stress&embed=true&utm_source=guide&utm_campaign=rr"
        parsed = urlparse(source)
        params = parse_qs(parsed.query, keep_blank_values=True)
        self.assertEqual(params.get("public"), ["stress"])
        params.pop("public", None)
        target_qs = "&".join(
            f"{key}={values[0]}" for key, values in params.items() if values
        )
        target = f"https://app.cadivor.com/public-bom-audit?{target_qs}"
        target_params = parse_qs(urlparse(target).query)
        self.assertNotIn("public", target_params)
        self.assertEqual(target_params.get("embed"), ["true"])
        self.assertEqual(target_params.get("utm_source"), ["guide"])
        self.assertEqual(target_params.get("utm_campaign"), ["rr"])

    def test_same_origin_proxies_forward_visitor_header_and_prefer_server_api_base(self):
        proxy = (ROOT / "apps/web/src/lib/publicBomProxy.ts").read_text()
        audit_route = (
            ROOT / "apps/web/src/app/api/public/bom-stress/audit/route.ts"
        ).read_text()
        status_route = (
            ROOT / "apps/web/src/app/api/public/bom-stress/status/route.ts"
        ).read_text()
        lead_route = (
            ROOT / "apps/web/src/app/api/public/bom-stress/lead/route.ts"
        ).read_text()
        self.assertIn('request.headers.get("x-cadivor-visitor")', proxy)
        self.assertIn('"X-Cadivor-Visitor": visitorHeader(request)', proxy)
        self.assertIn("process.env.CADIVOR_API_BASE", proxy)
        self.assertIn("readPublicBomAuditForm", proxy)
        self.assertIn("readBodyWithByteLimit", proxy)
        self.assertNotIn("Content-Length is required", proxy)
        self.assertLess(
            proxy.index("process.env.CADIVOR_API_BASE"),
            proxy.index("process.env.NEXT_PUBLIC_API_BASE"),
        )
        self.assertNotIn("CADIVOR_PUBLIC_BOM_HMAC_SECRET", proxy)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", proxy)
        self.assertNotIn("NEXT_PUBLIC_CADIVOR_PUBLIC_BOM", proxy)
        for route in (audit_route, status_route, lead_route):
            self.assertIn("proxyPublicBom", route)

    def test_public_page_is_signed_out_and_uses_same_origin_client_helpers(self):
        page = (ROOT / "apps/web/src/app/public-bom-audit/page.tsx").read_text()
        client = (ROOT / "apps/web/src/lib/publicBomStress.ts").read_text()
        self.assertNotIn("useRequireSession", page)
        self.assertNotIn("getSession", page)
        self.assertIn('data-testid="public-bom-audit"', page)
        self.assertIn("cv-stress-site-header", page)
        self.assertIn('fetch("/api/public/bom-stress/status"', client)
        self.assertIn('fetch("/api/public/bom-stress/audit"', client)
        self.assertIn('fetch("/api/public/bom-stress/lead"', client)
        # Client helpers stay same-origin; they must not call the API base directly.
        self.assertNotIn("NEXT_PUBLIC_API_BASE", client)
        self.assertNotIn("CADIVOR_API_BASE", client)

    def test_public_page_fails_closed_until_status_enabled(self):
        page = (ROOT / "apps/web/src/app/public-bom-audit/page.tsx").read_text()
        self.assertIn("status?.enabled === true", page)
        self.assertIn('data-testid="public-bom-status-loading"', page)
        self.assertIn('data-testid="public-bom-status-error"', page)
        self.assertIn('data-testid="public-bom-status-unavailable"', page)
        self.assertIn("STATUS_UNAVAILABLE_MESSAGE", page)
        self.assertIn("disabled={!file || busy || !auditEnabled}", page)
        # Upload UI is gated on confirmed enabled=true, not merely "not disabled".
        self.assertIn("{auditEnabled && !report ? (", page)
        self.assertNotIn("{!disabled && !report ? (", page)

    def test_public_page_status_request_failure_keeps_upload_hidden(self):
        """Status fetch rejection must not reveal an enabled upload flow."""
        page = (ROOT / "apps/web/src/app/public-bom-audit/page.tsx").read_text()
        self.assertIn("setStatus(null)", page)
        self.assertIn("setStatusError(", page)
        self.assertIn("STATUS_UNAVAILABLE_MESSAGE", page)
        # Failure path clears status so auditEnabled stays false.
        failure_chunk = page[
            page.index("fetchPublicBomStatus()") : page.index("async function onAudit")
        ]
        self.assertIn(".catch(", failure_chunk)
        self.assertIn("setStatus(null)", failure_chunk)
        self.assertIn("setStatusResolved(true)", page)

    def test_browser_smoke_script_targets_next_app_not_cloudflare_pages(self):
        smoke = (ROOT / "apps/web/scripts/public_bom_browser_smoke.mjs").read_text()
        self.assertIn("PUBLIC_BOM_APP_PREVIEW_URL", smoke)
        self.assertIn("/public-bom-audit", smoke)
        self.assertIn("public-bom-status-loading", smoke)
        self.assertIn("public-bom-status-error", smoke)
        self.assertIn("public-bom-run-audit", smoke)
        self.assertNotIn("cadivor.pages.dev", smoke)

    def test_verified_report_handoff_wiring(self):
        main = (ROOT / "apps/api/main.py").read_text()
        login = (ROOT / "apps/web/src/app/login/page.tsx").read_text()
        reports = (ROOT / "apps/web/src/app/reports/page.tsx").read_text()
        middleware = (ROOT / "apps/web/src/middleware.ts").read_text()
        page = (ROOT / "apps/web/src/app/public-bom-audit/page.tsx").read_text()
        proxy = (
            ROOT / "apps/web/src/app/api/public/bom-stress/verified-report/route.ts"
        ).read_text()
        delivery = (
            ROOT / "apps/web/scripts/public_bom_report_delivery_smoke.mjs"
        ).read_text()
        self.assertIn('/public/bom-stress/verified-report', main)
        self.assertIn("verified_report", main)
        verified_handler = main[main.index("public_bom_stress_verified_get") :][
            :1800
        ]
        self.assertIn("_auth_context", verified_handler)
        helpers = (ROOT / "apps/web/src/lib/publicBomStress.ts").read_text()
        funnel = (ROOT / "src/public_bom_stress_test.py").read_text()
        confirm = (ROOT / "apps/web/src/lib/signupEmailConfirm.ts").read_text()
        self.assertIn("markStressReportPending", login)
        self.assertIn("reportsHandoffHref", login)
        self.assertIn("stressReportIdFromSearch", login)
        self.assertIn("public-bom-verified-report", reports)
        self.assertIn("fetchVerifiedPublicBomReport", reports)
        self.assertIn("reportIdFromQuery", reports)
        self.assertIn("cacheVerifiedPublicBomReport", reports)
        self.assertIn("cadivor_signup_confirm", middleware)
        self.assertIn("verification_sent", page)
        self.assertIn("already sent recently", page)
        self.assertIn("params.delete(\"email\")", proxy)
        self.assertIn("Authorization: auth", proxy)
        self.assertIn("public-bom-verified-table", delivery)
        self.assertIn("report-delivery", delivery)
        self.assertIn("stubApi: true", delivery)
        self.assertIn("liveOtp: false", delivery)
        self.assertIn("cadivor_stress_report_id", funnel)
        self.assertIn("STRESS_REPORT_ID_QUERY_PARAM", funnel)
        self.assertIn("PUBLIC_BOM_STRESS_REPORT_ID_FLAG", helpers)
        self.assertIn("reportsHandoffHref", helpers)
        self.assertIn("STRESS_REPORT_ID_QUERY_FLAG", confirm)

    def test_api_routes_registered_without_auth_context(self):
        main = (ROOT / "apps/api/main.py").read_text()
        for path in (
            "/public/bom-stress/status",
            "/public/bom-stress/audit",
            "/public/bom-stress/lead",
        ):
            self.assertIn(f'Route("{path}"', main)
        # Handlers must not call the authenticated workspace gate.
        for handler in (
            "async def public_bom_stress_status",
            "async def public_bom_stress_audit",
            "async def public_bom_stress_lead",
        ):
            start = main.index(handler)
            chunk = main[start : start + 1800]
            self.assertNotIn("_auth_context", chunk)
        # Failure logs stay message-only (no BOM/token interpolation).
        self.assertIn('logging.exception("public_bom_stress_audit_failed")', main)
        self.assertIn('logging.exception("public_bom_stress_lead_failed")', main)
        self.assertIsNone(
            re.search(
                r'logging\.exception\("public_bom_stress_audit_failed".+payload',
                main,
            )
        )


if __name__ == "__main__":
    unittest.main()
