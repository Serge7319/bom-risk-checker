from supabase import create_client
import os

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

print("Scheduled BOM monitoring completed.")