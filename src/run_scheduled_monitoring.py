from supabase import create_client
import html
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from integrations.supplier_aggregator import get_best_part_data
from src.email_delivery import EmailDeliveryError, send_transactional_email
from src.email_routing import DEFAULT_ALERT_FROM
from src.monitoring_engine import detect_monitor_alerts
from src.monitoring_email_preferences import monitoring_email_enabled

print("Starting scheduled BOM monitoring...")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_MONITORING_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
)

if not SUPABASE_URL or not SUPABASE_MONITORING_KEY:
    raise ValueError("Missing Supabase environment variables")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_MONITORING_KEY,
)

ALERT_FROM_EMAIL = (
    os.getenv("ALERT_FROM_EMAIL")
    or os.getenv("CADIVOR_FROM_EMAIL")
    or DEFAULT_ALERT_FROM
)


users_response = (
    supabase.table("users")
    .select("id,email")
    .execute()
)

users = users_response.data or []


def recently_alerted(user_id, part_number, alert_type, hours=24):
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    response = (
        supabase.table("monitor_alerts")
        .select("id, created_at")
        .eq("user_id", user_id)
        .eq("part_number", part_number)
        .eq("alert_type", alert_type)
        .gte("created_at", cutoff_time.isoformat())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    recent_alerts = response.data or []

    return len(recent_alerts) > 0

print(f"Found {len(users)} users for monitoring.")

for user in users:
    user_id = user.get("id")
    user_email = user.get("email")

    print(f"Checking monitored parts for user id: {user_id}")
    email_allowed, preference_error = monitoring_email_enabled(
        supabase,
        str(user_id or ""),
    )
    if preference_error:
        print(
            "Monitoring email disabled because notification preferences "
            "could not be verified."
        )

    monitor_response = (
        supabase.table("part_monitor_history")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )

    monitor_rows = monitor_response.data or []

    unique_parts = {}

    for row in monitor_rows:
        part_number = row.get("part_number")

        if part_number and part_number not in unique_parts:
            unique_parts[part_number] = row

    print(f"Found {len(unique_parts)} unique monitored parts.")

    for part_number, previous_snapshot in unique_parts.items():
        print(f"Rechecking part: {part_number}")

        fresh_data = get_best_part_data(part_number)

       

        current_snapshot = {
            "user_id": user_id,
            "part_number": part_number,
            "supplier": fresh_data.get("source", ""),
            "lifecycle_status": fresh_data.get("lifecycle_status", ""),
            "stock": fresh_data.get("stock_total", 0),
            "unit_price": fresh_data.get("unit_price", 0.0),
            "risk_level": previous_snapshot.get("risk_level", ""),
        }

        new_alert_records, alert_messages = detect_monitor_alerts(
            user_id,
            part_number,
            previous_snapshot,
            current_snapshot,
        )

        filtered_alert_records = []

        for alert in new_alert_records:
            if recently_alerted(
                user_id,
                part_number,
                alert.get("alert_type"),
            ):
                print(
                    f"Skipping duplicate alert for {part_number}: "
                    f"{alert.get('alert_type')}"
                )
            else:
                filtered_alert_records.append(alert)

        new_alert_records = filtered_alert_records

        if new_alert_records:
            supabase.table("monitor_alerts").insert(
                new_alert_records
            ).execute()

            print(f"Saved {len(new_alert_records)} alerts for {part_number}")

            for alert in new_alert_records:
                if (
                    alert.get("severity") == "High"
                    and email_allowed
                    and user_email
                ):
                    try:
                        send_transactional_email(
                            from_email=ALERT_FROM_EMAIL,
                            to_email=user_email,
                            subject="High Severity BOM Monitoring Alert",
                            html_body=(
                                f"<p><strong>Part:</strong> {html.escape(str(part_number))}</p>"
                                f"<p><strong>Alert:</strong> {html.escape(str(alert.get('alert_message') or ''))}</p>"
                                f"<p><strong>Severity:</strong> {html.escape(str(alert.get('severity') or ''))}</p>"
                            ),
                        )

                        print(f"Sent alert email for monitored part {part_number}")

                    except EmailDeliveryError:
                        print(f"Could not send alert email for {part_number}")

        for message in alert_messages:
            print(f"{part_number}: {message}")

        supabase.table("part_monitor_history").insert(
            current_snapshot
        ).execute()

        print(f"Saved monitoring snapshot for {part_number}")

        print(
            f"{part_number}: stock={current_snapshot['stock']}, "
            f"lifecycle={current_snapshot['lifecycle_status']}"
        )

print("Scheduled BOM monitoring completed.")
