from apps.api import marketing_analytics


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


def test_funnel_summary_groups_by_event_entry_and_source():
    rows = [
        {"event": "page_view", "source": "marketing", "utm_source": "newsletter", "session_id": "hash-1"},
        {"event": "page_view", "source": "marketing", "utm_source": "newsletter", "session_id": "hash-1"},
        {"event": "signup_started", "source": "app", "utm_source": "newsletter", "session_id": "hash-1"},
    ]
    summary = marketing_analytics._summary(rows, 30)
    grouped = {(row["event"], row["source"], row["traffic_source"]): row for row in summary["rows"]}
    assert grouped[("page_view", "marketing", "newsletter")]["events"] == 2
    assert grouped[("page_view", "marketing", "newsletter")]["sessions"] == 1
    assert grouped[("signup_started", "app", "newsletter")]["events"] == 1
