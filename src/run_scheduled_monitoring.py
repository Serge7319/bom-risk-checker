from supabase import create_client
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from integrations.supplier_aggregator import get_best_part_data
from src.monitoring_engine import (
    build_monitor_record,
    detect_monitor_alerts,
)

print("Starting scheduled BOM monitoring...")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase environment variables")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
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

        print(f"Fresh data for {part_number}: {fresh_data}")

        current_snapshot = {
            "user_id": user_id,
            "part_number": part_number,
            "supplier": fresh_data.get("source", ""),
            "lifecycle_status": fresh_data.get("lifecycle_status", ""),
            "stock": fresh_data.get("stock_total", 0),
            "unit_price": fresh_data.get("unit_price", 0.0),
            "risk_level": previous_snapshot.get("risk_level", ""),
        }

        print(
            f"{part_number}: stock={current_snapshot['stock']}, "
            f"lifecycle={current_snapshot['lifecycle_status']}"
        )

print("Scheduled BOM monitoring completed.")