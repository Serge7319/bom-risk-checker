-- Recurring monitored-parts capacity is an active subscription entitlement,
-- not a one-time credit balance. Preserve subscription history if an account
-- is later deleted, while detaching the personal user identity.

create table if not exists public.cadivor_monitored_parts_addons (
  subscription_id text primary key,
  user_id uuid references auth.users(id) on delete set null,
  price_id text not null,
  status text not null,
  capacity integer not null check (capacity > 0 and capacity <= 100000),
  updated_at timestamptz not null default now()
);

create unique index if not exists cadivor_monitored_parts_addons_active_user_uidx
  on public.cadivor_monitored_parts_addons (user_id)
  where user_id is not null and status in ('active', 'trialing');

alter table public.cadivor_monitored_parts_addons enable row level security;
revoke all on public.cadivor_monitored_parts_addons from public, anon, authenticated;
grant all on public.cadivor_monitored_parts_addons to service_role;

create or replace function public.cadivor_set_monitored_parts_addon(
  p_user_id uuid,
  p_subscription_id text,
  p_price_id text,
  p_status text,
  p_capacity integer,
  p_event_created timestamptz
) returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  did_apply boolean := false;
  affected_rows bigint := 0;
begin
  if p_user_id is null
     or length(coalesce(p_subscription_id, '')) = 0
     or length(coalesce(p_price_id, '')) = 0
     or p_status not in ('active', 'trialing', 'past_due', 'unpaid', 'canceled', 'incomplete', 'incomplete_expired', 'paused')
     or p_capacity <= 0
     or p_capacity > 100000
     or p_event_created is null then
    raise exception 'invalid monitored-parts add-on snapshot';
  end if;

  if p_status in ('active', 'trialing') then
    insert into public.cadivor_monitored_parts_addons
      (subscription_id, user_id, price_id, status, capacity, updated_at)
    values
      (p_subscription_id, p_user_id, p_price_id, p_status, p_capacity, p_event_created)
    on conflict (subscription_id) do update set
      user_id = excluded.user_id,
      price_id = excluded.price_id,
      status = excluded.status,
      capacity = excluded.capacity,
      updated_at = excluded.updated_at
    where public.cadivor_monitored_parts_addons.updated_at <= excluded.updated_at
      and (public.cadivor_monitored_parts_addons.user_id is null
           or public.cadivor_monitored_parts_addons.user_id = excluded.user_id);
    get diagnostics affected_rows = row_count;
    did_apply := affected_rows > 0;
  else
    update public.cadivor_monitored_parts_addons
       set status = p_status,
           updated_at = p_event_created
     where subscription_id = p_subscription_id
       and (user_id = p_user_id or user_id is null)
       and updated_at <= p_event_created;
    get diagnostics affected_rows = row_count;
    did_apply := affected_rows > 0;
  end if;

  return case when did_apply then 'applied' else 'skipped_stale' end;
end;
$$;

revoke all on function public.cadivor_set_monitored_parts_addon(uuid, text, text, text, integer, timestamptz)
  from public, anon, authenticated;
grant execute on function public.cadivor_set_monitored_parts_addon(uuid, text, text, text, integer, timestamptz)
  to service_role;
