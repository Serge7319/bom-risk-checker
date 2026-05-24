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