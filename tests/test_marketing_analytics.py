from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

from apps.api import marketing_analytics


ROOT = Path(__file__).resolve().parents[1]
MARKETING = ROOT / "marketing-web"
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def test_event_schema_strips_unapproved_and_sensitive_properties():
    event = marketing_analytics.validate_event(
        {
            "event": "cta_click",
            "source": "marketing",
            "page": "/pricing/",
            "session_id": "a3f8b850-71a4-4ee2-931e-30c43f862394",
            "utm": {"utm_source": "newsletter", "utm_campaign": "november launch", "utm_other": "ignored"},
            "properties": {
                "location": "pricing",
                "cta": "Start trial",
                "part_number": "MPU-6050",
                "email": "person@example.com",
            },
        }
    )

    assert event is not None
    assert event["utm_source"] == "newsletter"
    assert event["utm_campaign"] == "november launch"
    assert "utm_other" not in event
    assert event["properties"] == {"location": "pricing", "cta": "Start trial"}
    assert event["session_id"] != "a3f8b850-71a4-4ee2-931e-30c43f862394"


def test_event_validation_rejects_unlisted_names_and_query_urls():
    base = {"source": "app", "page": "/reports", "session_id": ""}
    assert marketing_analytics.validate_event({**base, "event": "arbitrary"}) is None
    assert marketing_analytics.validate_event({**base, "event": "page_view", "page": "https://example.com"}) is None


def test_marketing_attribution_rejects_address_like_and_markup_values():
    assert marketing_analytics.sanitize_utm(
        {
            "utm_source": "partner-newsletter",
            "utm_medium": "a@b.example",
            "utm_campaign": "<script>",
            "utm_content": "summer campaign",
        }
    ) == {"utm_source": "partner-newsletter", "utm_content": "summer campaign"}


def test_funnel_summary_deduplicates_cross_site_sessions_and_calculates_visit_rates():
    rows = [
        {"event": "page_view", "source": "marketing", "utm_source": "newsletter", "session_id": "hash-1"},
        {"event": "page_view", "source": "app", "utm_source": "newsletter", "session_id": "hash-1"},
        {"event": "page_view", "source": "marketing", "utm_source": "newsletter", "session_id": "hash-2"},
        {"event": "signup_started", "source": "app", "utm_source": "newsletter", "session_id": "hash-2"},
        {"event": "free_audit_completed", "source": "app", "utm_source": "newsletter", "session_id": "hash-1"},
        {"event": "one_time_report_purchased", "source": "app", "utm_source": "", "session_id": "hash-3"},
    ]
    summary = marketing_analytics._summary(rows, 30)
    grouped = {(row["event"], row["traffic_source"]): row for row in summary["rows"]}

    visits = grouped[("page_view", "newsletter")]
    assert visits["events"] == 3
    assert visits["sessions"] == 2
    assert visits["origins"] == ["app", "marketing"]
    assert visits["visit_sessions"] == 2
    assert visits["conversion_from_visit_pct"] is None

    signup = grouped[("signup_started", "newsletter")]
    assert signup["sessions"] == 1
    assert signup["visit_sessions"] == 2
    assert signup["conversion_from_visit_pct"] == 50.0

    paid_without_visit = grouped[("one_time_report_purchased", "(direct)")]
    assert paid_without_visit["sessions"] == 1
    assert paid_without_visit["visit_sessions"] == 0
    assert paid_without_visit["conversion_from_visit_pct"] is None


def _static_file_for_path(path: str) -> Path:
    if path == "/":
        return MARKETING / "index.html"
    if path == "/release-readiness":
        return MARKETING / "release-readiness.html"
    candidate = MARKETING / path.lstrip("/")
    if path.endswith("/"):
        return candidate / "index.html"
    return candidate if candidate.suffix else candidate / "index.html"


def test_sitemap_routes_resolve_to_static_pages_with_metadata_and_content():
    sitemap = ElementTree.parse(MARKETING / "sitemap.xml").getroot()
    urls = [
        node.findtext("s:loc", namespaces=SITEMAP_NS)
        for node in sitemap.findall("s:url", SITEMAP_NS)
    ]
    assert urls

    for url in urls:
        assert url
        path = urlsplit(url).path or "/"
        page = _static_file_for_path(path)
        assert page.is_file(), f"{path} has no static page"
        content = page.read_text(encoding="utf-8")
        assert re.search(r"<title>[^<]+</title>", content, re.IGNORECASE), path
        assert re.search(
            r'<meta\s+name="description"\s+content="[^\"]{20,}"', content, re.IGNORECASE
        ), path
        assert re.search(r'<link\s+rel="canonical"\s+href="[^\"]+"', content, re.IGNORECASE), path
        assert re.search(r"<h1(?:\s[^>]*)?>\s*[^<]+", content, re.IGNORECASE), path


def test_home_and_guides_have_meaningful_server_delivered_content():
    home = (MARKETING / "index.html").read_text(encoding="utf-8")
    assert '<section class="page active" data-page="home">' in home
    assert "Know when your hardware is" in home

    for page in (
        MARKETING / "release-readiness.html",
        MARKETING / "guides" / "alternate-qualification" / "index.html",
        MARKETING / "guides" / "implementation" / "index.html",
    ):
        content = page.read_text(encoding="utf-8")
        assert "<h1" in content
        assert "<ol" in content
        assert "data-seo-consent" in content


def test_robots_and_resources_discover_every_standalone_guide():
    robots = (MARKETING / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://www.cadivor.com/sitemap.xml" in robots

    resources = (MARKETING / "resources" / "index.html").read_text(encoding="utf-8")
    for path in (
        "/release-readiness",
        "/guides/alternate-qualification/",
        "/guides/implementation/",
    ):
        assert path in resources


def test_marketing_static_examples_do_not_render_zero_confidence_placeholders():
    html = "\n".join(path.read_text(encoding="utf-8") for path in MARKETING.rglob("*.html"))
    assert not re.search(r"confidence\s*0\s*%", html, re.IGNORECASE)
    assert 'data-kpi-counter="0"' not in html
    assert "Illustrative sample" in html
