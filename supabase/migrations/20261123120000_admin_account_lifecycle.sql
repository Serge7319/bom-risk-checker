-- Restore platform account management and make deletion preserve shared and
-- financial history while removing private workspace data and account PII.

-- Keep durable usage and billing rows when their account is removed. These
-- surrogate keys allow the user references to be anonymized to NULL.
alter table public.cadivor_usage_credit_reservations
  add column if not exists lifecycle_id uuid not null default gen_random_uuid();
alter table public.cadivor_usage_credit_reservations
  drop constraint if exists cadivor_usage_credit_reservations_pkey;
alter table public.cadivor_usage_credit_reservations
  add constraint cadivor_usage_credit_reservations_pkey primary key (lifecycle_id);
create unique index if not exists cadivor_usage_credit_reservations_user_reservation_uidx
  on public.cadivor_usage_credit_reservations (user_id, reservation_id);
alter table public.cadivor_usage_credit_reservations alter column user_id drop not null;
alter table public.cadivor_usage_credit_reservations
  drop constraint if exists cadivor_usage_credit_reservations_user_id_fkey;
alter table public.cadivor_usage_credit_reservations
  add constraint cadivor_usage_credit_reservations_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete set null;

alter table public.cadivor_professional_api_addons
  add column if not exists lifecycle_id uuid not null default gen_random_uuid();
alter table public.cadivor_professional_api_addons
  drop constraint if exists cadivor_professional_api_addons_pkey;
alter table public.cadivor_professional_api_addons
  add constraint cadivor_professional_api_addons_pkey primary key (lifecycle_id);
create unique index if not exists cadivor_professional_api_addons_user_uidx
  on public.cadivor_professional_api_addons (user_id);
alter table public.cadivor_professional_api_addons alter column user_id drop not null;
alter table public.cadivor_professional_api_addons
  drop constraint if exists cadivor_professional_api_addons_user_id_fkey;
alter table public.cadivor_professional_api_addons
  add constraint cadivor_professional_api_addons_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete set null;

alter table public.cadivor_usage_credit_grants alter column user_id drop not null;
alter table public.cadivor_usage_credit_grants
  drop constraint if exists cadivor_usage_credit_grants_user_id_fkey;
alter table public.cadivor_usage_credit_grants
  add constraint cadivor_usage_credit_grants_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete set null;

alter table public.cadivor_monitored_part_allocations alter column paid_by_user drop not null;
alter table public.cadivor_monitored_part_allocations
  drop constraint if exists cadivor_monitored_part_allocations_paid_by_user_fkey;
alter table public.cadivor_monitored_part_allocations
  add constraint cadivor_monitored_part_allocations_paid_by_user_fkey
  foreign key (paid_by_user) references auth.users(id) on delete set null;

-- A one-time report is a financial record. Its report link and user link are
-- removed during deletion, while the Stripe payment references are retained.
alter table public.cadivor_one_time_bom_orders alter column user_id drop not null;
alter table public.cadivor_one_time_bom_orders
  drop constraint if exists cadivor_one_time_bom_orders_user_id_fkey;
alter table public.cadivor_one_time_bom_orders
  add constraint cadivor_one_time_bom_orders_user_id_fkey
  foreign key (user_id) references public.users(id) on delete set null;

-- Retain admin and support audit events without retaining the deleted account's
-- identity. Shared engineering rows are likewise kept with a NULL author id.
alter table public.admin_audit_events alter column actor_id drop not null;
alter table public.admin_audit_events
  drop constraint if exists admin_audit_events_actor_id_fkey;
alter table public.admin_audit_events
  add constraint admin_audit_events_actor_id_fkey
  foreign key (actor_id) references auth.users(id) on delete set null;
alter table public.admin_audit_events
  drop constraint if exists admin_audit_events_target_user_id_fkey;
alter table public.admin_audit_events
  add constraint admin_audit_events_target_user_id_fkey
  foreign key (target_user_id) references auth.users(id) on delete set null;

alter table public.admin_support_activity_events alter column user_id drop not null;
alter table public.admin_support_activity_events
  drop constraint if exists admin_support_activity_events_user_id_fkey;
alter table public.admin_support_activity_events
  add constraint admin_support_activity_events_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete set null;

alter table public.admin_platform_settings
  drop constraint if exists admin_platform_settings_updated_by_fkey;
alter table public.admin_platform_settings
  add constraint admin_platform_settings_updated_by_fkey
  foreign key (updated_by) references auth.users(id) on delete set null;
alter table public.admin_user_controls
  drop constraint if exists admin_user_controls_updated_by_fkey;
alter table public.admin_user_controls
  add constraint admin_user_controls_updated_by_fkey
  foreign key (updated_by) references auth.users(id) on delete set null;

-- This marker intentionally has no FK to auth.users. It survives the Auth
-- deletion call so a failed final cleanup remains visible and retryable.
create table if not exists public.admin_account_deletion_pending (
  user_id uuid primary key,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint admin_account_deletion_pending_created_by_fkey
    foreign key (created_by) references auth.users(id) on delete set null
);
alter table public.admin_account_deletion_pending enable row level security;
revoke all on public.admin_account_deletion_pending from public, anon, authenticated;
grant all on public.admin_account_deletion_pending to service_role;

do $$
declare
  item record;
begin
  for item in
    select * from (values
      ('analysis_comments', 'analysis_comments_user_id_fkey', 'user_id'),
      ('analysis_decisions', 'analysis_decisions_user_id_fkey', 'user_id'),
      ('engineering_decision_events', 'engineering_decision_events_user_id_fkey', 'user_id'),
      ('engineering_decision_notes', 'engineering_decision_notes_user_id_fkey', 'user_id'),
      ('engineering_decisions', 'engineering_decisions_user_id_fkey', 'user_id'),
      ('engineering_review_comments', 'engineering_review_comments_user_id_fkey', 'user_id'),
      ('engineering_review_events', 'engineering_review_events_user_id_fkey', 'user_id'),
      ('engineering_review_items', 'engineering_review_items_user_id_fkey', 'user_id'),
      ('engineering_review_sessions', 'engineering_review_sessions_user_id_fkey', 'user_id'),
      ('monitoring_events', 'monitoring_events_user_id_fkey', 'user_id')
    ) as refs(table_name, constraint_name, column_name)
  loop
    execute format('alter table public.%I alter column %I drop not null', item.table_name, item.column_name);
    execute format('alter table public.%I drop constraint if exists %I', item.table_name, item.constraint_name);
    execute format(
      'alter table public.%I add constraint %I foreign key (%I) references auth.users(id) on delete set null',
      item.table_name, item.constraint_name, item.column_name
    );
  end loop;
end $$;

alter table public.alternative_recommendations alter column user_id drop not null;

-- The API and supported external-key route also reject suspended users; this
-- helper lets direct access to the shared Alternative Finder table fail closed.
create or replace function public.cadivor_current_account_is_active()
returns boolean
language sql stable security definer
set search_path = public, auth
as $$
  select auth.uid() is not null
     and exists (select 1 from auth.users account where account.id = auth.uid())
     and exists (select 1 from public.users user_profile where user_profile.id = auth.uid())
     and not exists (
       select 1 from public.admin_user_controls controls
       where controls.user_id = auth.uid()
         and controls.account_status = 'suspended'
     )
     and not exists (
       select 1 from public.admin_account_deletion_pending pending
       where pending.user_id = auth.uid()
     );
$$;

revoke all on function public.cadivor_current_account_is_active() from public;
grant execute on function public.cadivor_current_account_is_active() to authenticated;

-- Existing SECURITY DEFINER admin RPCs call cadivor_is_admin(). Keep those
-- RPCs unavailable to suspended users with still-valid access tokens.
create or replace function public.cadivor_is_admin()
returns boolean
language sql stable security definer
set search_path = public, auth
as $$
  select auth.uid() is not null
     and public.cadivor_current_account_is_active()
     and exists (
       select 1 from public.users user_profile
       where user_profile.id = auth.uid()
         and lower(coalesce(user_profile.role, '')) = 'admin'
     );
$$;
revoke all on function public.cadivor_is_admin() from public;
grant execute on function public.cadivor_is_admin() to authenticated;

-- These SECURITY DEFINER membership helpers are also callable through RPC.
-- Make suspended/deletion-pending accounts fail closed there as well as in RLS.
create or replace function public.cadivor_is_workspace_member(target_workspace_id uuid)
returns boolean
language sql stable security definer set search_path = public as $$
  select public.cadivor_current_account_is_active() and exists (
    select 1 from public.workspace_members wm
    where wm.workspace_id = target_workspace_id
      and wm.user_id = auth.uid()
      and lower(coalesce(wm.status, '')) = 'active'
  );
$$;

create or replace function public.cadivor_workspace_role(target_workspace_id uuid)
returns text
language sql stable security definer set search_path = public as $$
  select lower(wm.role)
  from public.workspace_members wm
  where public.cadivor_current_account_is_active()
    and wm.workspace_id = target_workspace_id
    and wm.user_id = auth.uid()
    and lower(coalesce(wm.status, '')) = 'active'
  order by wm.joined_at nulls last, wm.id
  limit 1;
$$;

create or replace function public.is_workspace_admin(target_workspace uuid)
returns boolean
language sql stable security definer set search_path = public as $$
  select public.cadivor_current_account_is_active() and exists (
    select 1 from public.workspace_members wm
    where wm.workspace_id = target_workspace
      and wm.user_id = auth.uid()
      and wm.status = 'active'
      and wm.role in ('owner', 'admin')
  );
$$;

create or replace function public.is_workspace_member(target_workspace uuid)
returns boolean
language sql stable security definer set search_path = public as $$
  select public.cadivor_current_account_is_active() and exists (
    select 1 from public.workspace_members wm
    where wm.workspace_id = target_workspace
      and wm.user_id = auth.uid()
      and wm.status = 'active'
  );
$$;

create or replace function public.is_workspace_owner(target_workspace uuid)
returns boolean
language sql stable security definer set search_path = public as $$
  select public.cadivor_current_account_is_active() and exists (
    select 1 from public.workspaces w
    where w.id = target_workspace and w.owner_id = auth.uid()
  );
$$;

create or replace function public.cadivor_record_support_activity(
  event_type text, event_metadata jsonb default '{}'::jsonb
)
returns void language plpgsql security definer set search_path = public as $$
declare
  normalized_type text := lower(trim(coalesce(event_type, '')));
begin
  if not public.cadivor_current_account_is_active() then
    raise exception 'Active account access is required';
  end if;
  if normalized_type not in ('session_started', 'page_viewed') then
    raise exception 'Unsupported support activity event';
  end if;
  if normalized_type = 'session_started' and exists (
    select 1 from public.admin_support_activity_events
    where user_id = auth.uid() and event_type = 'session_started'
      and created_at >= now() - interval '10 minutes'
  ) then
    return;
  end if;
  insert into public.admin_support_activity_events (user_id, event_type, metadata)
  values (auth.uid(), normalized_type, coalesce(event_metadata, '{}'::jsonb));
end;
$$;

create or replace function public.cadivor_record_user_activity()
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.cadivor_current_account_is_active() then
    raise exception 'Active account access is required';
  end if;
  insert into public.admin_user_activity (user_id, last_seen_at)
  values (auth.uid(), now())
  on conflict (user_id) do update set last_seen_at = excluded.last_seen_at;
end;
$$;

create or replace function public.cadivor_set_my_workspace_functional_roles(
  target_workspace_id uuid, next_roles text[]
)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.cadivor_current_account_is_active() then
    raise exception 'Active account access is required';
  end if;
  if coalesce(next_roles, '{}'::text[]) <@ array[
    'Supply Chain Manager', 'Electrical Engineer',
    'Procurement Specialist', 'Component Engineer'
  ]::text[] is not true then
    raise exception 'Unsupported responsibility role.';
  end if;
  update public.workspace_members
     set functional_roles = coalesce(next_roles, '{}'::text[]), updated_at = now()
   where workspace_id = target_workspace_id
     and user_id = auth.uid()
     and status = 'active';
  if not found then
    raise exception 'Active workspace membership is required.';
  end if;
end;
$$;

-- A restrictive guard composes with existing table policies, so one suspended
-- or deleted account cannot keep using a previously issued JWT through direct
-- PostgREST requests. Service-role jobs continue to use their intended access.
do $$
declare
  item record;
begin
  for item in
    select c.relname
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public'
       and c.relkind in ('r', 'p')
       and c.relrowsecurity
  loop
    execute format('drop policy if exists cadivor_active_account_guard on public.%I', item.relname);
    execute format(
      'create policy cadivor_active_account_guard on public.%I as restrictive for all to authenticated using (public.cadivor_current_account_is_active()) with check (public.cadivor_current_account_is_active())',
      item.relname
    );
  end loop;
end $$;

do $$
begin
  if to_regclass('storage.objects') is not null then
    drop policy if exists cadivor_active_account_guard on storage.objects;
    create policy cadivor_active_account_guard
      on storage.objects as restrictive for all to authenticated
      using (public.cadivor_current_account_is_active())
      with check (public.cadivor_current_account_is_active());
  end if;
end $$;

-- A previously issued JWT must stop working in app routes after the account is
-- deleted, even though access tokens are stateless until their expiry.
create or replace function public.cadivor_admin_runtime_access()
returns table (maintenance_mode boolean, maintenance_message text, account_status text)
language sql stable security definer set search_path = public, auth as $$
  select settings.maintenance_mode,
         settings.maintenance_message,
         case
           when auth.uid() is null or not exists (
             select 1 from auth.users account where account.id = auth.uid()
           ) or not exists (
             select 1 from public.users user_profile where user_profile.id = auth.uid()
           ) or exists (
             select 1 from public.admin_account_deletion_pending pending
             where pending.user_id = auth.uid()
           ) then 'suspended'
           else coalesce(controls.account_status, 'active')
         end
  from public.admin_platform_settings settings
  left join public.admin_user_controls controls on controls.user_id = auth.uid()
  where settings.singleton = true;
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
         case when pending.user_id is not null then 'suspended'
              else coalesce(controls.account_status, 'active') end,
         case when pending.user_id is not null then 'Account deletion pending'
              else controls.suspended_reason end,
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
    left join auth.users auth_user on auth_user.id = user_profile.id
    left join public.admin_user_controls controls on controls.user_id = user_profile.id
    left join public.admin_user_activity activity on activity.user_id = user_profile.id
    left join public.admin_account_deletion_pending pending on pending.user_id = user_profile.id
   where public.cadivor_is_admin()
     and (auth_user.id is not null or pending.user_id is not null)
   order by activity.last_seen_at desc nulls last, auth_user.created_at desc nulls last;
$$;

-- Shared workspace decisions remain visible to active workspace members after
-- the original author's account is removed. Standalone decisions stay private.
drop policy if exists analysis_decisions_authenticated_select on public.analysis_decisions;
create policy analysis_decisions_authenticated_select
  on public.analysis_decisions for select to authenticated
  using (
    public.cadivor_current_account_is_active()
    and (
      (workspace_id is null and user_id::text = auth.uid()::text)
      or (workspace_id is not null and exists (
        select 1 from public.workspace_members wm
        where wm.workspace_id::text = analysis_decisions.workspace_id::text
          and wm.user_id = auth.uid() and wm.status = 'active'
      ))
    )
  );

drop policy if exists analysis_decisions_authenticated_insert on public.analysis_decisions;
create policy analysis_decisions_authenticated_insert
  on public.analysis_decisions for insert to authenticated
  with check (
    public.cadivor_current_account_is_active()
    and user_id = auth.uid()
    and (workspace_id is null or exists (
      select 1 from public.workspace_members wm
      where wm.workspace_id::text = analysis_decisions.workspace_id::text
        and wm.user_id = auth.uid() and wm.status = 'active'
    ))
  );

drop policy if exists analysis_decisions_authenticated_update on public.analysis_decisions;
create policy analysis_decisions_authenticated_update
  on public.analysis_decisions for update to authenticated
  using (
    public.cadivor_current_account_is_active()
    and (
      (workspace_id is null and user_id::text = auth.uid()::text)
      or (workspace_id is not null and exists (
        select 1 from public.workspace_members wm
        where wm.workspace_id::text = analysis_decisions.workspace_id::text
          and wm.user_id = auth.uid() and wm.status = 'active'
      ))
    )
  )
  with check (
    public.cadivor_current_account_is_active()
    and (
      (workspace_id is null and user_id = auth.uid())
      or (workspace_id is not null and exists (
        select 1 from public.workspace_members wm
        where wm.workspace_id::text = analysis_decisions.workspace_id::text
          and wm.user_id = auth.uid() and wm.status = 'active'
      ))
    )
  );

-- An administrator can suspend an account. A deletion-pending account cannot
-- be restored because its private workspaces and personal data are already gone.
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
  perform pg_advisory_xact_lock(hashtextextended('cadivor.admin-account-lifecycle', 0));
  if target_user_id = auth.uid() then
    raise exception 'Administrators cannot change their own account status';
  end if;
  if normalized_status not in ('active', 'suspended') then
    raise exception 'Unsupported account status';
  end if;
  if exists (
       select 1 from public.admin_user_controls
       where user_id = target_user_id and suspended_reason = 'Account deletion pending'
     ) or exists (
       select 1 from public.admin_account_deletion_pending
       where user_id = target_user_id
     ) then
    raise exception 'Account deletion is pending; retry deletion to finish it';
  end if;
  if normalized_status = 'suspended'
     and exists (
       select 1 from public.users where id = target_user_id and lower(coalesce(role, '')) = 'admin'
     )
     and coalesce((
       select controls.account_status from public.admin_user_controls controls
       where controls.user_id = target_user_id
     ), 'active') = 'active' then
    if (
      select count(*)
        from public.users admin_user
        left join public.admin_user_controls controls on controls.user_id = admin_user.id
        left join public.admin_account_deletion_pending pending on pending.user_id = admin_user.id
       where lower(coalesce(admin_user.role, '')) = 'admin'
         and coalesce(controls.account_status, 'active') = 'active'
         and pending.user_id is null
         and admin_user.id <> target_user_id
         and exists (select 1 from auth.users auth_admin where auth_admin.id = admin_user.id)
    ) = 0 then
      raise exception 'Cadivor must retain at least one active administrator';
    end if;
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
  perform pg_advisory_xact_lock(hashtextextended('cadivor.admin-account-lifecycle', 0));
  if target_user_id = auth.uid() then
    raise exception 'Administrators cannot change their own role';
  end if;
  if normalized_role not in ('user', 'admin') then
    raise exception 'Unsupported role';
  end if;
  if not exists (select 1 from public.users where id = target_user_id) then
    raise exception 'User was not found';
  end if;
  if exists (
    select 1 from public.admin_account_deletion_pending
    where user_id = target_user_id
  ) then
    raise exception 'Account deletion is pending; retry deletion to finish it';
  end if;
  if normalized_role = 'user'
     and exists (
       select 1 from public.users where id = target_user_id and lower(coalesce(role, '')) = 'admin'
     )
     and coalesce((
       select controls.account_status from public.admin_user_controls controls
       where controls.user_id = target_user_id
     ), 'active') = 'active'
     and (
       select count(*)
         from public.users admin_user
         left join public.admin_user_controls controls on controls.user_id = admin_user.id
         left join public.admin_account_deletion_pending pending on pending.user_id = admin_user.id
        where lower(coalesce(admin_user.role, '')) = 'admin'
          and coalesce(controls.account_status, 'active') = 'active'
          and pending.user_id is null
          and admin_user.id <> target_user_id
          and exists (select 1 from auth.users auth_admin where auth_admin.id = admin_user.id)
     ) = 0 then
    raise exception 'Cadivor must retain at least one active administrator';
  end if;

  update public.users set role = normalized_role where id = target_user_id;
  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (auth.uid(), 'role_changed', target_user_id,
          jsonb_build_object('role', normalized_role, 'reason', normalized_reason));
end;
$$;

create or replace function public.cadivor_admin_prepare_account_deletion(
  p_target_user_id uuid,
  p_actor_user_id uuid
)
returns jsonb
language plpgsql security definer
set search_path = public, auth
as $$
declare
  target_role text;
  target_account_status text;
  target_email text;
  target_name text;
  target_pending boolean := false;
  workspace_row record;
  successor_id uuid;
  private_workspace_ids uuid[] := array[]::uuid[];
  shared_workspace_ids uuid[] := array[]::uuid[];
  private_count integer := 0;
  transfer_count integer := 0;
  shared_count integer := 0;
begin
  if p_actor_user_id is null or p_target_user_id is null then
    raise exception 'An administrator and target account are required';
  end if;
  if p_actor_user_id = p_target_user_id then
    raise exception 'Administrators cannot delete their own account';
  end if;
  if not exists (
    select 1 from public.users actor
    where actor.id = p_actor_user_id and lower(coalesce(actor.role, '')) = 'admin'
  ) then
    raise exception 'Cadivor administrator access is required';
  end if;

  perform pg_advisory_xact_lock(hashtextextended('cadivor.admin-account-lifecycle', 0));

  select lower(coalesce(target.role, '')), target.email, target.full_name
    into target_role, target_email, target_name
    from public.users target where target.id = p_target_user_id for update;
  if not found then
    select exists (
      select 1 from public.admin_user_controls controls
      where controls.user_id = p_target_user_id
        and controls.account_status = 'suspended'
        and controls.suspended_reason = 'Account deletion pending'
    ) into target_pending;
    if not target_pending then
      raise exception 'User was not found';
    end if;
  else
    select coalesce(controls.account_status, 'active') into target_account_status
      from public.admin_user_controls controls
     where controls.user_id = p_target_user_id;
    target_account_status := coalesce(target_account_status, 'active');
    if target_role = 'admin' and target_account_status = 'active' and (
      select count(*)
        from public.users admin_user
        left join public.admin_user_controls controls on controls.user_id = admin_user.id
        left join public.admin_account_deletion_pending pending on pending.user_id = admin_user.id
       where lower(coalesce(admin_user.role, '')) = 'admin'
         and coalesce(controls.account_status, 'active') = 'active'
         and pending.user_id is null
         and admin_user.id <> p_target_user_id
         and exists (select 1 from auth.users auth_admin where auth_admin.id = admin_user.id)
    ) = 0 then
      raise exception 'Cadivor must retain at least one active administrator';
    end if;
  end if;

  perform 1 from public.workspace_members
  where user_id = p_target_user_id for update;

  -- Transfer owned shared workspaces before removing the owner. An owner-only
  -- workspace is private and can be deleted with its BOMs and reports.
  for workspace_row in
    select w.id from public.workspaces w where w.owner_id = p_target_user_id for update
  loop
    successor_id := null;
    select wm.user_id into successor_id
      from public.workspace_members wm
     where wm.workspace_id = workspace_row.id
       and wm.user_id <> p_target_user_id
       and wm.status = 'active'
     order by case when wm.role = 'owner' then 0 when wm.role = 'admin' then 1 else 2 end,
              wm.joined_at nulls last, wm.user_id
     limit 1;
    if successor_id is not null then
      update public.workspaces set owner_id = successor_id, updated_at = now()
       where id = workspace_row.id;
      update public.workspace_members set role = 'owner', updated_at = now()
       where workspace_id = workspace_row.id and user_id = successor_id;
      shared_workspace_ids := array_append(shared_workspace_ids, workspace_row.id);
      transfer_count := transfer_count + 1;
    elsif exists (
      select 1 from public.workspace_members wm
      where wm.workspace_id = workspace_row.id and wm.user_id <> p_target_user_id
    ) then
      raise exception 'A shared workspace has no active member to receive ownership';
    else
      private_workspace_ids := array_append(private_workspace_ids, workspace_row.id);
      -- Several workspace-scoped engineering tables intentionally do not have
      -- workspace foreign keys. Erase their private rows before deleting the
      -- workspace so no orphaned BOM review data remains.
      delete from public.engineering_review_comments where workspace_id = workspace_row.id;
      delete from public.engineering_review_events where workspace_id = workspace_row.id;
      delete from public.engineering_review_items where workspace_id = workspace_row.id;
      delete from public.engineering_review_sessions where workspace_id = workspace_row.id;
      delete from public.engineering_decision_events where workspace_id = workspace_row.id;
      delete from public.engineering_decision_notes where workspace_id = workspace_row.id;
      delete from public.engineering_decisions where workspace_id = workspace_row.id;
      delete from public.monitoring_events where workspace_id = workspace_row.id;
      delete from public.workspaces where id = workspace_row.id;
      private_count := private_count + 1;
    end if;
  end loop;

  for workspace_row in
    select distinct wm.workspace_id
      from public.workspace_members wm
     where wm.user_id = p_target_user_id
       and not (wm.workspace_id = any(private_workspace_ids))
  loop
    shared_workspace_ids := array_append(shared_workspace_ids, workspace_row.workspace_id);
  end loop;

  select count(distinct workspace_id) into shared_count
    from unnest(shared_workspace_ids) as workspaces(workspace_id);

  -- Stop all access immediately. Keep a separate marker because the FK-backed
  -- control row is removed automatically when Auth deletes the target user.
  insert into public.admin_account_deletion_pending (user_id, created_by, created_at, updated_at)
  values (p_target_user_id, p_actor_user_id, now(), now())
  on conflict (user_id) do update set
    created_by = excluded.created_by,
    updated_at = excluded.updated_at;
  if exists (select 1 from auth.users where id = p_target_user_id) then
    insert into public.admin_user_controls
      (user_id, account_status, suspended_reason, updated_by, updated_at)
    values
      (p_target_user_id, 'suspended', 'Account deletion pending', p_actor_user_id, now())
    on conflict (user_id) do update set
      account_status = 'suspended',
      suspended_reason = 'Account deletion pending',
      updated_by = p_actor_user_id,
      updated_at = now();
  end if;

  -- Keep shared workspace content while removing identity from the author fields.
  update public.workspace_activity
     set actor_id = null, actor_name = 'Former member',
         summary = 'Activity by former member', metadata = '{}'::jsonb
   where actor_id = p_target_user_id;
  update public.workspace_audit_log
     set actor_user_id = null, actor_name = 'Former member', actor_email = '',
         summary = 'Action by former member', metadata = '{}'::jsonb,
         search_text = 'Action by former member'
   where actor_user_id = p_target_user_id;
  update public.workspace_invites
     set invited_by = null, invited_by_name = null
   where invited_by = p_target_user_id;
  if target_email is not null then
    delete from public.workspace_invites where lower(email) = lower(target_email);
  end if;

  -- Workspace-less engineering records are private to their creator. Shared
  -- workspace rows are retained below after their author identity is scrubbed.
  delete from public.engineering_review_comments
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.engineering_review_events
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.engineering_review_items
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.engineering_review_sessions
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.engineering_decision_events
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.engineering_decision_notes
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.engineering_decisions
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.monitoring_events
   where workspace_id is null and user_id = p_target_user_id;
  delete from public.analysis_decisions
   where workspace_id is null and user_id = p_target_user_id;

  update public.analyses set user_id = null where user_id = p_target_user_id;
  update public.alternative_recommendations set user_id = null where user_id = p_target_user_id;
  update public.analysis_parts set user_id = null where user_id = p_target_user_id;
  update public.analysis_comments
     set user_id = null, author_name = 'Former member', author_email = ''
   where user_id = p_target_user_id;
  update public.analysis_decisions
     set user_id = null, engineer_name = 'Former member'
   where user_id = p_target_user_id;
  update public.engineering_decision_events
     set user_id = null, actor_name = 'Former member', event_payload = '{}'::jsonb
   where user_id = p_target_user_id;
  update public.engineering_decision_notes
     set user_id = null, author_name = 'Former member'
   where user_id = p_target_user_id;
  update public.engineering_decisions
     set user_id = null,
         assigned_owner = case
           when lower(trim(coalesce(assigned_owner, ''))) in (lower(coalesce(target_name, '')), lower(coalesce(target_email, '')))
             then 'Former member' else assigned_owner end,
         created_by = case when created_by = p_target_user_id then null else created_by end,
         updated_by = case when updated_by = p_target_user_id then null else updated_by end
   where user_id = p_target_user_id;
  update public.engineering_review_sessions
     set user_id = null, reviewer_name = 'Former member', reviewer_email = ''
   where user_id = p_target_user_id;
  update public.engineering_review_items
     set user_id = null,
         owner = case when lower(trim(coalesce(owner, ''))) in (lower(coalesce(target_name, '')), lower(coalesce(target_email, ''))) then 'Former member' else owner end,
         reviewer_name = case when user_id = p_target_user_id or lower(coalesce(reviewer_email, '')) = lower(coalesce(target_email, '')) then 'Former member' else reviewer_name end,
         reviewer_email = case when user_id = p_target_user_id or lower(coalesce(reviewer_email, '')) = lower(coalesce(target_email, '')) then '' else reviewer_email end,
         assignee_name = case when lower(coalesce(assignee_email, '')) = lower(coalesce(target_email, '')) or lower(coalesce(assignee_name, '')) = lower(coalesce(target_name, '')) then 'Former member' else assignee_name end,
         assignee_email = case when lower(coalesce(assignee_email, '')) = lower(coalesce(target_email, '')) then '' else assignee_email end,
         assignee_user_id = case when assignee_user_id = p_target_user_id then null else assignee_user_id end
   where user_id = p_target_user_id or assignee_user_id = p_target_user_id
      or lower(coalesce(reviewer_email, '')) = lower(coalesce(target_email, ''));
  update public.engineering_review_comments
     set user_id = null, author_name = 'Former member', author_email = ''
   where user_id = p_target_user_id;
  update public.engineering_review_events
     set user_id = null, actor_name = 'Former member', actor_email = '', metadata = '{}'::jsonb
   where user_id = p_target_user_id;
  update public.monitoring_events
     set user_id = null, metadata = '{}'::jsonb
   where user_id = p_target_user_id;
  update public.monitor_alerts set user_id = null where user_id = p_target_user_id;
  update public.part_monitor_history set user_id = null where user_id = p_target_user_id;

  delete from public.analysis_followers where user_id = p_target_user_id;
  delete from public.copilot_conversation_threads where user_id = p_target_user_id;
  delete from public.workspace_notifications where user_id = p_target_user_id;
  delete from public.workspace_presence where user_id = p_target_user_id;
  delete from public.user_workspace_preferences where user_id = p_target_user_id;
  delete from public.user_preferences where user_id = p_target_user_id;
  delete from public.onboarding_progress where user_id = p_target_user_id;
  delete from public.customer_profiles where user_id = p_target_user_id;
  delete from public.cadivor_developer_api_keys where user_id = p_target_user_id;
  delete from public.cadivor_api_access_overrides where user_id = p_target_user_id;
  delete from public.cadivor_usage_credit_balances where user_id = p_target_user_id;
  delete from public.cadivor_trial_lifecycle_email_sends where user_id = p_target_user_id;

  update public.admin_support_activity_events
     set user_id = null, metadata = '{}'::jsonb
   where user_id = p_target_user_id;
  update public.cadivor_usage_credit_grants set user_id = null
   where user_id = p_target_user_id;
  update public.cadivor_usage_credit_reservations set user_id = null
   where user_id = p_target_user_id;
  update public.cadivor_monitored_part_allocations
     set paid_by_user = null
   where paid_by_user = p_target_user_id;
  delete from public.cadivor_monitored_part_allocations
   where workspace_id in (
     select private_id::text from unnest(private_workspace_ids) as ids(private_id)
   );
  update public.cadivor_one_time_bom_orders
     set user_id = null, analysis_id = null
   where user_id = p_target_user_id;
  update public.stripe_webhook_events
     set user_id = null,
         stripe_customer_id = null,
         stripe_subscription_id = null,
         last_error = null
   where user_id = p_target_user_id;

  update public.admin_platform_settings set updated_by = null where updated_by = p_target_user_id;
  update public.admin_user_controls set updated_by = null where updated_by = p_target_user_id;
  update public.admin_audit_events
     set actor_id = case when actor_id = p_target_user_id then null else actor_id end,
         target_user_id = null,
         metadata = '{}'::jsonb
   where actor_id = p_target_user_id or target_user_id = p_target_user_id;

  delete from public.workspace_members where user_id = p_target_user_id;

  return jsonb_build_object(
    'private_workspaces_deleted', private_count,
    'shared_workspaces_preserved', shared_count,
    'shared_workspace_ownership_transferred', transfer_count
  );
end;
$$;

create or replace function public.cadivor_admin_finalize_account_deletion(
  p_target_user_id uuid,
  p_actor_user_id uuid
)
returns jsonb
language plpgsql security definer
set search_path = public, auth
as $$
begin
  if p_actor_user_id is null or p_target_user_id is null
     or p_actor_user_id = p_target_user_id then
    raise exception 'An administrator and target account are required';
  end if;
  if not exists (
    select 1 from public.users actor
    where actor.id = p_actor_user_id and lower(coalesce(actor.role, '')) = 'admin'
  ) then
    raise exception 'Cadivor administrator access is required';
  end if;
  if exists (select 1 from auth.users where id = p_target_user_id) then
    raise exception 'The Auth account must be deleted before profile cleanup';
  end if;

  delete from public.users where id = p_target_user_id;
  delete from public.admin_account_deletion_pending where user_id = p_target_user_id;
  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (p_actor_user_id, 'account_deleted', null, '{"target_anonymized": true}'::jsonb);
  return jsonb_build_object('deleted', true);
end;
$$;

revoke all on function public.cadivor_admin_prepare_account_deletion(uuid, uuid) from public, anon, authenticated;
revoke all on function public.cadivor_admin_finalize_account_deletion(uuid, uuid) from public, anon, authenticated;
grant execute on function public.cadivor_admin_prepare_account_deletion(uuid, uuid) to service_role;
grant execute on function public.cadivor_admin_finalize_account_deletion(uuid, uuid) to service_role;

revoke all on function public.cadivor_admin_set_account_status(uuid, text, text) from public;
grant execute on function public.cadivor_admin_set_account_status(uuid, text, text) to authenticated;
