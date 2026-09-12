-- Proposed only. Do not apply until approved.
-- Do not create, alter, or query the live database from this work.
--
-- Schema inspection (repository only; live Supabase was not queried):
-- public.stripe_webhook_events is not defined anywhere in this repository.
-- The exported deployed function inserts these columns and depends on a
-- unique violation (SQLSTATE 23505) on event_id:
--   event_id, event_type, livemode, user_id,
--   stripe_customer_id, stripe_subscription_id
-- That function records the event only after a successful user update
-- (check, then apply, then insert). A crash after a unique claim-style
-- insert would permanently block Stripe retries. This migration does not
-- recreate the table. It adds a lease so a failed apply can be retried,
-- and a watermark so an older snapshot cannot overwrite a newer one.
--
-- Assumed existing user columns, already written by the deployed function:
--   stripe_customer_id, stripe_subscription_id, stripe_subscription_status,
--   stripe_price_id, stripe_current_period_end, stripe_cancel_at_period_end,
--   billing_updated_at, plan, plan_changed_at, role
-- If public.stripe_webhook_events is absent, this file stops. Inspect the
-- live columns before creating a guessed table.

do $$
begin
  if to_regclass('public.stripe_webhook_events') is null then
    raise exception
      'public.stripe_webhook_events is not in this database. The deployed webhook inserts into that table, but this repository has no CREATE TABLE for it. Inspect the live schema before creating one. Do not apply a guessed table.';
  end if;
end $$;

alter table public.stripe_webhook_events
  add column if not exists event_created timestamptz,
  add column if not exists processing_status text not null default 'processed',
  add column if not exists lease_expires_at timestamptz,
  add column if not exists last_error text,
  add column if not exists apply_outcome text default 'applied';

comment on column public.stripe_webhook_events.processing_status is
  'processing, processed, or failed. Existing rows default to processed because the deployed function inserted an event only after a successful apply.';
comment on column public.stripe_webhook_events.lease_expires_at is
  'Claim lease. A failed apply expires the lease so Stripe can retry. A processed row never keeps a lease.';
comment on column public.stripe_webhook_events.apply_outcome is
  'applied, skipped_stale, admin_untouched, or ignored. Existing rows default to applied.';
comment on column public.stripe_webhook_events.event_created is
  'Stripe event.created. Null on rows recorded before this migration, so those rows cannot order newer snapshots.';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.stripe_webhook_events'::regclass
      and conname = 'stripe_webhook_events_processing_status_check'
  ) then
    alter table public.stripe_webhook_events
      add constraint stripe_webhook_events_processing_status_check
      check (processing_status in ('processing', 'processed', 'failed'));
  end if;
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.stripe_webhook_events'::regclass
      and conname = 'stripe_webhook_events_apply_outcome_check'
  ) then
    alter table public.stripe_webhook_events
      add constraint stripe_webhook_events_apply_outcome_check
      check (
        apply_outcome is null
        or apply_outcome in ('applied', 'skipped_stale', 'admin_untouched', 'ignored')
      );
  end if;
end $$;

-- The deployed function already relies on uniqueness of event_id (23505).
-- Add a single-column unique index only if one does not already exist.
do $$
begin
  if not exists (
    select 1
    from pg_index i
    join pg_class c on c.oid = i.indrelid
    join pg_namespace n on n.oid = c.relnamespace
    join pg_attribute a on a.attrelid = c.oid and a.attnum = any (i.indkey)
    where n.nspname = 'public'
      and c.relname = 'stripe_webhook_events'
      and i.indisunique
      and i.indnkeyatts = 1
      and a.attname = 'event_id'
  ) then
    create unique index stripe_webhook_events_event_id_uidx
      on public.stripe_webhook_events (event_id);
  end if;
end $$;

create index if not exists stripe_webhook_events_subscription_created_idx
  on public.stripe_webhook_events (stripe_subscription_id, event_created desc)
  where processing_status = 'processed' and apply_outcome = 'applied';

alter table public.users
  add column if not exists stripe_last_event_created timestamptz,
  add column if not exists plan_grandfather_source text;

comment on column public.users.stripe_last_event_created is
  'Stripe event.created of the last applied billing snapshot. Older events must not overwrite the row.';

comment on column public.users.plan_grandfather_source is
  'Durable beta-eligibility marker. Null means not grandfathered. This function must never clear it. Population of existing unpaid starter/free rows is 20260912_grandfather_unpaid_starter.sql, which is also unapplied.';

create or replace function public.cadivor_claim_stripe_webhook_event(
  p_event_id text,
  p_event_type text,
  p_livemode boolean,
  p_event_created timestamptz,
  p_lease_seconds integer default 120
) returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_status text;
  v_lease timestamptz;
  v_lease_end timestamptz;
begin
  if p_event_id is null or btrim(p_event_id) = '' then
    raise exception 'missing stripe event id';
  end if;

  v_lease_end := now() + make_interval(secs => greatest(coalesce(p_lease_seconds, 120), 1));

  insert into public.stripe_webhook_events (
    event_id,
    event_type,
    livemode,
    event_created,
    processing_status,
    lease_expires_at,
    apply_outcome,
    last_error
  ) values (
    p_event_id,
    p_event_type,
    coalesce(p_livemode, false),
    p_event_created,
    'processing',
    v_lease_end,
    null,
    null
  )
  on conflict do nothing;

  if found then
    return 'claimed';
  end if;

  select processing_status, lease_expires_at
    into v_status, v_lease
  from public.stripe_webhook_events
  where event_id = p_event_id
  for update;

  if not found then
    raise exception 'stripe webhook event disappeared during claim';
  end if;

  if v_status = 'processed' then
    return 'duplicate';
  end if;

  if v_status = 'processing' and v_lease is not null and v_lease > now() then
    return 'busy';
  end if;

  update public.stripe_webhook_events
  set
    processing_status = 'processing',
    lease_expires_at = v_lease_end,
    event_type = coalesce(nullif(btrim(p_event_type), ''), event_type),
    event_created = coalesce(p_event_created, event_created),
    livemode = coalesce(p_livemode, livemode),
    last_error = null
  where event_id = p_event_id;

  return 'claimed';
end;
$$;

create or replace function public.cadivor_complete_stripe_webhook_event(
  p_event_id text,
  p_user_id text,
  p_stripe_customer_id text,
  p_stripe_subscription_id text,
  p_outcome text
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id_sql text;
begin
  if p_outcome not in ('applied', 'skipped_stale', 'admin_untouched', 'ignored') then
    raise exception 'unexpected stripe webhook outcome';
  end if;

  -- One guarded update. A quoted user_id literal assigns to uuid or text.
  -- A row that is already processed must not change user_id, outcome, or timestamps.
  v_user_id_sql := case
    when p_user_id is null or btrim(p_user_id) = '' then 'null'
    else quote_literal(p_user_id)
  end;

  execute format(
    'update public.stripe_webhook_events
     set
       processing_status = ''processed'',
       lease_expires_at = null,
       stripe_customer_id = %L,
       stripe_subscription_id = %L,
       apply_outcome = %L,
       last_error = null,
       user_id = %s
     where event_id = %L
       and processing_status <> ''processed''',
    p_stripe_customer_id,
    p_stripe_subscription_id,
    p_outcome,
    v_user_id_sql,
    p_event_id
  );
end;
$$;

create or replace function public.cadivor_release_stripe_webhook_event(
  p_event_id text,
  p_error text
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.stripe_webhook_events
  set
    processing_status = 'failed',
    lease_expires_at = now(),
    last_error = left(coalesce(p_error, 'apply failed'), 500)
  where event_id = p_event_id
    and processing_status <> 'processed';
end;
$$;

create or replace function public.cadivor_apply_stripe_billing_snapshot(
  p_user_id uuid,
  p_event_id text,
  p_event_created timestamptz,
  p_stripe_customer_id text,
  p_stripe_subscription_id text,
  p_stripe_subscription_status text,
  p_stripe_price_id text,
  p_stripe_current_period_end text,
  p_stripe_cancel_at_period_end boolean,
  p_set_plan boolean,
  p_plan text
) returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_role text;
  v_watermark timestamptz;
  v_status text;
  v_plan text;
  v_grandfather_source text;
  v_set_plan boolean;
  v_next_plan text;
  v_sets text;
begin
  select
    lower(coalesce(role, '')),
    stripe_last_event_created,
    plan,
    plan_grandfather_source
    into v_role, v_watermark, v_plan, v_grandfather_source
  from public.users
  where id = p_user_id
  for update;

  if not found then
    return 'not_found';
  end if;

  if v_role = 'admin' then
    return 'admin_untouched';
  end if;

  if v_watermark is not null
     and p_event_created is not null
     and p_event_created < v_watermark then
    return 'skipped_stale';
  end if;

  if p_stripe_subscription_id is not null
     and p_event_created is not null
     and exists (
       select 1
       from public.stripe_webhook_events
       where stripe_subscription_id = p_stripe_subscription_id
         and processing_status = 'processed'
         and apply_outcome = 'applied'
         and event_created is not null
         and event_created > p_event_created
         and event_id is distinct from p_event_id
     ) then
    return 'skipped_stale';
  end if;

  v_status := lower(coalesce(p_stripe_subscription_status, ''));
  v_set_plan := coalesce(p_set_plan, false)
    and v_status in ('active', 'trialing')
    and p_plan in ('Starter', 'Professional', 'Business');

  -- A paid write never clears plan_grandfather_source. A non-entitling
  -- snapshot restores Grandfathered beta only when that marker is set.
  -- Otherwise a paid or beta label becomes Subscription inactive. Student,
  -- Trial, and Trial expired are not overwritten. Never write plan = Starter
  -- from a non-entitling status.
  v_next_plan := null;
  if v_set_plan then
    v_next_plan := p_plan;
  elsif v_status not in ('active', 'trialing')
        and lower(btrim(coalesce(v_plan, ''))) not in ('student', 'trial', 'trial expired') then
    if nullif(btrim(coalesce(v_grandfather_source, '')), '') is not null then
      v_next_plan := 'Grandfathered beta';
    elsif lower(btrim(coalesce(v_plan, ''))) in (
      'starter', 'professional', 'business', 'grandfathered beta'
    ) then
      v_next_plan := 'Subscription inactive';
    end if;
  end if;

  -- Quoted literals assign to text or timestamptz.
  v_sets :=
    'stripe_customer_id = ' || quote_nullable(p_stripe_customer_id) ||
    ', stripe_subscription_id = ' || quote_nullable(p_stripe_subscription_id) ||
    ', stripe_subscription_status = ' || quote_nullable(p_stripe_subscription_status) ||
    ', stripe_price_id = ' || quote_nullable(p_stripe_price_id) ||
    ', stripe_current_period_end = ' || quote_nullable(p_stripe_current_period_end) ||
    ', stripe_cancel_at_period_end = ' || case
      when p_stripe_cancel_at_period_end is null then 'null'
      when p_stripe_cancel_at_period_end then 'true'
      else 'false'
    end ||
    ', billing_updated_at = now()' ||
    ', stripe_last_event_created = ' || quote_nullable(p_event_created);

  if v_next_plan is not null and v_next_plan is distinct from v_plan then
    v_sets := v_sets ||
      ', plan = ' || quote_literal(v_next_plan) ||
      ', plan_changed_at = now()';
  end if;

  execute format(
    'update public.users set %s where id = %L::uuid',
    v_sets,
    p_user_id
  );

  return 'applied';
end;
$$;

revoke all on function public.cadivor_claim_stripe_webhook_event(text, text, boolean, timestamptz, integer) from public, anon, authenticated;
revoke all on function public.cadivor_complete_stripe_webhook_event(text, text, text, text, text) from public, anon, authenticated;
revoke all on function public.cadivor_release_stripe_webhook_event(text, text) from public, anon, authenticated;
revoke all on function public.cadivor_apply_stripe_billing_snapshot(uuid, text, timestamptz, text, text, text, text, text, boolean, boolean, text) from public, anon, authenticated;

grant execute on function public.cadivor_claim_stripe_webhook_event(text, text, boolean, timestamptz, integer) to service_role;
grant execute on function public.cadivor_complete_stripe_webhook_event(text, text, text, text, text) to service_role;
grant execute on function public.cadivor_release_stripe_webhook_event(text, text) to service_role;
grant execute on function public.cadivor_apply_stripe_billing_snapshot(uuid, text, timestamptz, text, text, text, text, text, boolean, boolean, text) to service_role;

-- Reverse, only after the versioned function no longer calls these RPCs:
-- drop function if exists public.cadivor_apply_stripe_billing_snapshot(uuid, text, timestamptz, text, text, text, text, text, boolean, boolean, text);
-- drop function if exists public.cadivor_release_stripe_webhook_event(text, text);
-- drop function if exists public.cadivor_complete_stripe_webhook_event(text, text, text, text, text);
-- drop function if exists public.cadivor_claim_stripe_webhook_event(text, text, boolean, timestamptz, integer);
-- alter table public.users drop column if exists stripe_last_event_created;
-- alter table public.stripe_webhook_events
--   drop column if exists event_created,
--   drop column if exists processing_status,
--   drop column if exists lease_expires_at,
--   drop column if exists last_error,
--   drop column if exists apply_outcome;
