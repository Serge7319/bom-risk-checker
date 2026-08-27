-- Admin Console v2.1: privacy-safe authenticated activity heartbeat.
-- REVIEW ONLY: do not apply until this pull request has been approved.

create table if not exists public.admin_user_activity (
  user_id uuid primary key references auth.users(id) on delete cascade,
  last_seen_at timestamptz not null default now()
);

alter table public.admin_user_activity enable row level security;

create or replace function public.cadivor_record_user_activity()
returns void language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then
    raise exception 'Authenticated access is required';
  end if;

  insert into public.admin_user_activity (user_id, last_seen_at)
  values (auth.uid(), now())
  on conflict (user_id) do update set last_seen_at = excluded.last_seen_at;
end;
$$;

create or replace function public.cadivor_admin_overview()
returns table (registered_users bigint, active_now bigint, active_last_30_days bigint, suspended_users bigint,
               maintenance_mode boolean, maintenance_message text)
language sql stable security definer set search_path = public, auth as $$
  select count(*)::bigint,
         count(*) filter (where activity.last_seen_at >= now() - interval '2 minutes')::bigint,
         count(*) filter (where auth_user.last_sign_in_at >= now() - interval '30 days')::bigint,
         count(*) filter (where controls.account_status = 'suspended')::bigint,
         settings.maintenance_mode,
         settings.maintenance_message
  from public.users user_profile
  join auth.users auth_user on auth_user.id = user_profile.id
  left join public.admin_user_controls controls on controls.user_id = user_profile.id
  left join public.admin_user_activity activity on activity.user_id = user_profile.id
  cross join public.admin_platform_settings settings
  where public.cadivor_is_admin() and settings.singleton = true
  group by settings.maintenance_mode, settings.maintenance_message;
$$;

create or replace function public.cadivor_admin_list_users_v2()
returns table (
  id uuid, email text, full_name text, company_name text, role text, plan text,
  account_status text, suspended_reason text, trial_ends_at timestamptz,
  signup_at timestamptz, last_sign_in_at timestamptz, last_active_at timestamptz,
  activity_status text
)
language sql stable security definer set search_path = public, auth as $$
  select user_profile.id,
         to_jsonb(user_profile) ->> 'email',
         to_jsonb(user_profile) ->> 'full_name',
         to_jsonb(user_profile) ->> 'company_name',
         to_jsonb(user_profile) ->> 'role',
         to_jsonb(user_profile) ->> 'plan',
         coalesce(controls.account_status, 'active'),
         controls.suspended_reason,
         nullif(to_jsonb(user_profile) ->> 'trial_ends_at', '')::timestamptz,
         auth_user.created_at,
         auth_user.last_sign_in_at,
         activity.last_seen_at,
         case
           when activity.last_seen_at >= now() - interval '2 minutes' then 'active'
           when activity.last_seen_at >= now() - interval '15 minutes' then 'idle'
           else 'offline'
         end
  from public.users user_profile
  join auth.users auth_user on auth_user.id = user_profile.id
  left join public.admin_user_controls controls on controls.user_id = user_profile.id
  left join public.admin_user_activity activity on activity.user_id = user_profile.id
  where public.cadivor_is_admin()
  order by activity.last_seen_at desc nulls last, auth_user.created_at desc;
$$;

revoke all on function public.cadivor_record_user_activity() from public;
grant execute on function public.cadivor_record_user_activity() to authenticated;
