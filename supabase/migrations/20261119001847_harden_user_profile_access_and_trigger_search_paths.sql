begin;

-- Ownership-only row policies let a user change every column on their own
-- account row. Restrict direct Data API writes to non-entitlement profile
-- fields; trusted provisioning, billing, and admin code keeps its own access.
revoke all privileges on table public.users from anon, authenticated;
grant select on table public.users to authenticated;
grant update (full_name, company_name, role_title, profile_image_url)
  on table public.users to authenticated;

-- Account creation/deletion must go through trusted auth/admin workflows.
drop policy if exists "Allow users to insert own record" on public.users;
drop policy if exists "Users can delete own user record" on public.users;

-- Pin the search path on the two trigger functions flagged by the security
-- advisor. Their bodies use only NEW and pg_catalog's now().
alter function public.cadivor_touch_updated_at()
  set search_path = pg_catalog, public;
alter function public.cadivor_touch_monitor_alert_updated_at()
  set search_path = pg_catalog, public;

commit;
