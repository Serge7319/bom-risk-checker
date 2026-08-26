-- Admin Console v2: audited account controls and an administrator-safe
-- maintenance switch. Paid-plan changes remain owned by Stripe/webhooks.

create table if not exists public.admin_user_controls (
  user_id uuid primary key references auth.users(id) on delete cascade,
  account_status text not null default 'active'
    check (account_status in ('active', 'suspended')),
  suspended_reason text,
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now()
);

create table if not exists public.admin_platform_settings (
  singleton boolean primary key default true check (singleton),
  maintenance_mode boolean not null default false,
  maintenance_message text not null default 'Cadivor is undergoing scheduled maintenance. Please try again shortly.',
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now()
);

alter table public.admin_user_controls enable row level security;
alter table public.admin_platform_settings enable row level security;

insert into public.admin_platform_settings (singleton)
values (true)
on conflict (singleton) do nothing;

create or replace function public.cadivor_admin_runtime_access()
returns table (maintenance_mode boolean, maintenance_message text, account_status text)
language sql stable security definer set search_path = public as $$
  select settings.maintenance_mode,
         settings.maintenance_message,
         coalesce(controls.account_status, 'active')
  from public.admin_platform_settings settings
  left join public.admin_user_controls controls on controls.user_id = auth.uid()
  where settings.singleton = true;
$$;

create or replace function public.cadivor_admin_overview()
returns table (registered_users bigint, active_last_30_days bigint, suspended_users bigint,
               maintenance_mode boolean, maintenance_message text)
language sql stable security definer set search_path = public, auth as $$
  select count(*)::bigint,
         count(*) filter (where auth_user.last_sign_in_at >= now() - interval '30 days')::bigint,
         count(*) filter (where controls.account_status = 'suspended')::bigint,
         settings.maintenance_mode,
         settings.maintenance_message
  from public.users user_profile
  join auth.users auth_user on auth_user.id = user_profile.id
  left join public.admin_user_controls controls on controls.user_id = user_profile.id
  cross join public.admin_platform_settings settings
  where public.cadivor_is_admin() and settings.singleton = true
  group by settings.maintenance_mode, settings.maintenance_message;
$$;

create or replace function public.cadivor_admin_list_users_v2()
returns table (
  id uuid, email text, full_name text, company_name text, role text, plan text,
  account_status text, suspended_reason text, trial_ends_at timestamptz,
  signup_at timestamptz, last_sign_in_at timestamptz
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
         auth_user.last_sign_in_at
  from public.users user_profile
  join auth.users auth_user on auth_user.id = user_profile.id
  left join public.admin_user_controls controls on controls.user_id = user_profile.id
  where public.cadivor_is_admin()
  order by auth_user.created_at desc;
$$;

create or replace function public.cadivor_admin_set_account_status(
  target_user_id uuid, next_status text, reason text default ''
)
returns void language plpgsql security definer set search_path = public as $$
declare
  normalized_status text := lower(trim(coalesce(next_status, '')));
  normalized_reason text := left(trim(coalesce(reason, '')), 500);
begin
  if not public.cadivor_is_admin() then
    raise exception 'Cadivor administrator access is required';
  end if;
  if target_user_id = auth.uid() then
    raise exception 'Administrators cannot change their own account status';
  end if;
  if normalized_status not in ('active', 'suspended') then
    raise exception 'Unsupported account status';
  end if;
  if exists (select 1 from public.users where id = target_user_id and lower(coalesce(role, '')) = 'admin') then
    raise exception 'Administrator accounts cannot be suspended';
  end if;

  insert into public.admin_user_controls (user_id, account_status, suspended_reason, updated_by, updated_at)
  values (target_user_id, normalized_status,
          case when normalized_status = 'suspended' then normalized_reason else null end,
          auth.uid(), now())
  on conflict (user_id) do update set
    account_status = excluded.account_status,
    suspended_reason = excluded.suspended_reason,
    updated_by = excluded.updated_by,
    updated_at = excluded.updated_at;

  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (auth.uid(), 'account_status_changed', target_user_id,
          jsonb_build_object('account_status', normalized_status, 'reason', normalized_reason));
end;
$$;

create or replace function public.cadivor_admin_set_role(
  target_user_id uuid, next_role text, reason text default ''
)
returns void language plpgsql security definer set search_path = public as $$
declare
  normalized_role text := lower(trim(coalesce(next_role, '')));
  normalized_reason text := left(trim(coalesce(reason, '')), 500);
begin
  if not public.cadivor_is_admin() then
    raise exception 'Cadivor administrator access is required';
  end if;
  if target_user_id = auth.uid() then
    raise exception 'Administrators cannot change their own role';
  end if;
  if normalized_role not in ('user', 'admin') then
    raise exception 'Unsupported role';
  end if;
  if not exists (select 1 from public.users where id = target_user_id) then
    raise exception 'User was not found';
  end if;
  if normalized_role = 'user'
     and exists (select 1 from public.users where id = target_user_id and lower(coalesce(role, '')) = 'admin')
     and (select count(*) from public.users where lower(coalesce(role, '')) = 'admin') <= 1 then
    raise exception 'Cadivor must retain at least one administrator';
  end if;

  update public.users set role = normalized_role where id = target_user_id;
  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (auth.uid(), 'role_changed', target_user_id,
          jsonb_build_object('role', normalized_role, 'reason', normalized_reason));
end;
$$;

create or replace function public.cadivor_admin_set_maintenance(
  next_enabled boolean, next_message text default ''
)
returns void language plpgsql security definer set search_path = public as $$
declare
  normalized_message text := left(trim(coalesce(next_message, '')), 280);
begin
  if not public.cadivor_is_admin() then
    raise exception 'Cadivor administrator access is required';
  end if;
  if next_enabled and normalized_message = '' then
    raise exception 'A maintenance message is required';
  end if;

  update public.admin_platform_settings
  set maintenance_mode = coalesce(next_enabled, false),
      maintenance_message = case when normalized_message = ''
        then 'Cadivor is undergoing scheduled maintenance. Please try again shortly.'
        else normalized_message end,
      updated_by = auth.uid(),
      updated_at = now()
  where singleton = true;

  insert into public.admin_audit_events (actor_id, action, metadata)
  values (auth.uid(), 'maintenance_mode_changed',
          jsonb_build_object('enabled', coalesce(next_enabled, false), 'message', normalized_message));
end;
$$;

revoke all on function public.cadivor_admin_runtime_access() from public;
revoke all on function public.cadivor_admin_overview() from public;
revoke all on function public.cadivor_admin_list_users_v2() from public;
revoke all on function public.cadivor_admin_set_account_status(uuid, text, text) from public;
revoke all on function public.cadivor_admin_set_role(uuid, text, text) from public;
revoke all on function public.cadivor_admin_set_maintenance(boolean, text) from public;

grant execute on function public.cadivor_admin_runtime_access() to authenticated;
grant execute on function public.cadivor_admin_overview() to authenticated;
grant execute on function public.cadivor_admin_list_users_v2() to authenticated;
grant execute on function public.cadivor_admin_set_account_status(uuid, text, text) to authenticated;
grant execute on function public.cadivor_admin_set_role(uuid, text, text) to authenticated;
grant execute on function public.cadivor_admin_set_maintenance(boolean, text) to authenticated;
