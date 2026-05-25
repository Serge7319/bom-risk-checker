from supabase import create_client
import os
import sys
from pathlib import Path
import resend

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from integrations.supplier_aggregator import get_best_part_data
from src.monitoring_engine import detect_monitor_alerts

print("Starting scheduled BOM monitoring...")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase environment variables")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)

resend.api_key = os.getenv("RESEND_API_KEY")
ALERT_FROM_EMAIL = os.getenv(
    "ALERT_FROM_EMAIL",
    "BOM Risk Checker <onboarding@resend.dev>",
)


users_response = (
    supabase.table("users")
    .select("id,email")
    .execute()
)

users = users_response.data or []

print(f"Found {len(users)} users for monitoring.")

for user in users:
    user_id = user.get("id")
    user_email = user.get("email")

    print(f"Checking monitored parts for user: {user_email}")

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


        if new_alert_records:
            supabase.table("monitor_alerts").insert(
                new_alert_records
            ).execute()

            print(f"Saved {len(new_alert_records)} alerts for {part_number}")

            for alert in new_alert_records:
                if alert.get("severity") == "High":
                    try:
                        resend.Emails.send(
                            {
                                "from": ALERT_FROM_EMAIL,
                                "to": [user_email],
                                "subject": "High Severity BOM Monitoring Alert",
                                "html": (
                                    f"<p><strong>Part:</strong> {part_number}</p>"
                                    f"<p><strong>Alert:</strong> {alert.get('alert_message')}</p>"
                                    f"<p><strong>Severity:</strong> {alert.get('severity')}</p>"
                                ),
                            }
                        )

                        print(f"Sent alert email for {part_number} to {user_email}")

                    except Exception as e:
                        print(f"Could not send alert email for {part_number}: {e}")

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