-- Separate public maintenance notices from the enforced workspace pause.
-- Planned notices are informational; only maintenance_mode blocks non-admins.

alter table public.admin_platform_settings
  add column if not exists planned_maintenance_message text not null default '',
  add column if not exists planned_maintenance_starts_at timestamptz,
  add column if not exists planned_maintenance_ends_at timestamptz;

-- Expose only fields intended for a public service-status notice. The row policy
-- allows the singleton, while column grants prevent access to admin metadata.
revoke all on table public.admin_platform_settings from anon, authenticated;
grant select (
  singleton,
  maintenance_mode,
  maintenance_message,
  planned_maintenance_message,
  planned_maintenance_starts_at,
  planned_maintenance_ends_at
) on table public.admin_platform_settings to anon, authenticated;

drop policy if exists admin_platform_settings_public_status
  on public.admin_platform_settings;
create policy admin_platform_settings_public_status
  on public.admin_platform_settings
  for select
  to anon, authenticated
  using (singleton = true);

drop function if exists public.cadivor_admin_runtime_access();
create function public.cadivor_admin_runtime_access()
returns table (
  maintenance_mode boolean,
  maintenance_message text,
  account_status text,
  planned_maintenance_message text,
  planned_maintenance_starts_at timestamptz,
  planned_maintenance_ends_at timestamptz
)
language sql stable security definer set search_path = public as $$
  select settings.maintenance_mode,
         settings.maintenance_message,
         coalesce(controls.account_status, 'active'),
         settings.planned_maintenance_message,
         settings.planned_maintenance_starts_at,
         settings.planned_maintenance_ends_at
  from public.admin_platform_settings settings
  left join public.admin_user_controls controls on controls.user_id = auth.uid()
  where settings.singleton = true;
$$;

create or replace function public.cadivor_admin_get_planned_maintenance()
returns table (
  planned_maintenance_message text,
  planned_maintenance_starts_at timestamptz,
  planned_maintenance_ends_at timestamptz
)
language sql stable security definer set search_path = public as $$
  select settings.planned_maintenance_message,
         settings.planned_maintenance_starts_at,
         settings.planned_maintenance_ends_at
  from public.admin_platform_settings settings
  where public.cadivor_is_admin() and settings.singleton = true;
$$;

create or replace function public.cadivor_admin_set_planned_maintenance(
  next_message text,
  next_starts_at timestamptz,
  next_ends_at timestamptz
)
returns void
language plpgsql security definer set search_path = public as $$
declare
  normalized_message text := left(trim(coalesce(next_message, '')), 280);
begin
  if not public.cadivor_is_admin() then
    raise exception 'Cadivor administrator access is required';
  end if;
  if normalized_message = '' and (next_starts_at is not null or next_ends_at is not null) then
    raise exception 'Clear the scheduled notice message and both dates together';
  end if;
  if normalized_message <> '' and (next_starts_at is null or next_ends_at is null) then
    raise exception 'Enter both the planned maintenance start and end times';
  end if;
  if next_starts_at is not null and next_ends_at <= next_starts_at then
    raise exception 'The planned maintenance end must be after its start';
  end if;

  update public.admin_platform_settings
  set planned_maintenance_message = normalized_message,
      planned_maintenance_starts_at = next_starts_at,
      planned_maintenance_ends_at = next_ends_at,
      updated_by = auth.uid(),
      updated_at = now()
  where singleton = true;

  insert into public.admin_audit_events (actor_id, action, metadata)
  values (
    auth.uid(),
    'planned_maintenance_notice_changed',
    jsonb_build_object(
      'message', normalized_message,
      'starts_at', next_starts_at,
      'ends_at', next_ends_at
    )
  );
end;
$$;

revoke all on function public.cadivor_admin_runtime_access() from public;
revoke all on function public.cadivor_admin_get_planned_maintenance() from public;
revoke all on function public.cadivor_admin_set_planned_maintenance(text, timestamptz, timestamptz) from public;
grant execute on function public.cadivor_admin_runtime_access() to authenticated;
grant execute on function public.cadivor_admin_get_planned_maintenance() to authenticated;
grant execute on function public.cadivor_admin_set_planned_maintenance(text, timestamptz, timestamptz) to authenticated;

notify pgrst, 'reload schema';
