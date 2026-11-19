-- Optional purchases for analysis overages and Professional API access.
-- Price IDs and pack sizes remain operator-configured Stripe/Supabase values.

create table if not exists public.cadivor_usage_credit_balances (
  user_id uuid not null references auth.users(id) on delete cascade,
  credit_kind text not null check (credit_kind in ('bom_analysis', 'monitored_part')),
  credits bigint not null default 0 check (credits >= 0),
  updated_at timestamptz not null default now(),
  primary key (user_id, credit_kind)
);

create table if not exists public.cadivor_usage_credit_grants (
  checkout_session_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  payment_intent_id text not null unique,
  price_id text not null,
  credit_kind text not null check (credit_kind in ('bom_analysis', 'monitored_part')),
  credits bigint not null check (credits > 0),
  created_at timestamptz not null default now()
);

create table if not exists public.cadivor_usage_credit_reservations (
  user_id uuid not null references auth.users(id) on delete cascade,
  reservation_id text not null,
  credit_kind text not null check (credit_kind = 'bom_analysis'),
  status text not null check (status in ('reserved', 'committed')),
  created_at timestamptz not null default now(),
  primary key (user_id, reservation_id)
);

create table if not exists public.cadivor_professional_api_addons (
  user_id uuid primary key references auth.users(id) on delete cascade,
  subscription_id text not null unique,
  price_id text not null,
  status text not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.cadivor_developer_api_keys (
  id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  workspace_id text not null,
  name text not null check (length(name) between 1 and 80),
  key_prefix text not null,
  key_hash text not null unique check (length(key_hash) = 64),
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);

create table if not exists public.cadivor_api_access_overrides (
  user_id uuid primary key references auth.users(id) on delete cascade,
  enabled boolean not null,
  updated_at timestamptz not null default now()
);

create index if not exists cadivor_developer_api_keys_user_workspace_idx
  on public.cadivor_developer_api_keys (user_id, workspace_id, created_at desc)
  where revoked_at is null;

create table if not exists public.cadivor_monitored_part_allocations (
  workspace_id text primary key,
  paid_by_user uuid not null references auth.users(id) on delete cascade,
  credits bigint not null default 0 check (credits >= 0),
  updated_at timestamptz not null default now()
);

alter table public.cadivor_usage_credit_balances enable row level security;
alter table public.cadivor_usage_credit_grants enable row level security;
alter table public.cadivor_usage_credit_reservations enable row level security;
alter table public.cadivor_professional_api_addons enable row level security;
alter table public.cadivor_developer_api_keys enable row level security;
alter table public.cadivor_api_access_overrides enable row level security;
alter table public.cadivor_monitored_part_allocations enable row level security;
revoke all on public.cadivor_usage_credit_balances from public, anon, authenticated;
revoke all on public.cadivor_usage_credit_grants from public, anon, authenticated;
revoke all on public.cadivor_usage_credit_reservations from public, anon, authenticated;
revoke all on public.cadivor_professional_api_addons from public, anon, authenticated;
revoke all on public.cadivor_developer_api_keys from public, anon, authenticated;
revoke all on public.cadivor_api_access_overrides from public, anon, authenticated;
revoke all on public.cadivor_monitored_part_allocations from public, anon, authenticated;
grant all on public.cadivor_usage_credit_balances to service_role;
grant all on public.cadivor_usage_credit_grants to service_role;
grant all on public.cadivor_usage_credit_reservations to service_role;
grant all on public.cadivor_professional_api_addons to service_role;
grant all on public.cadivor_developer_api_keys to service_role;
grant all on public.cadivor_api_access_overrides to service_role;
grant all on public.cadivor_monitored_part_allocations to service_role;

create or replace function public.cadivor_grant_usage_credits(
  p_checkout_session_id text,
  p_user_id uuid,
  p_payment_intent_id text,
  p_price_id text,
  p_credit_kind text,
  p_credits bigint
) returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  inserted_id text;
begin
  if p_credit_kind not in ('bom_analysis', 'monitored_part')
     or p_credits <= 0
     or length(coalesce(p_checkout_session_id, '')) = 0
     or length(coalesce(p_payment_intent_id, '')) = 0
     or length(coalesce(p_price_id, '')) = 0 then
    raise exception 'invalid usage credit grant';
  end if;

  insert into public.cadivor_usage_credit_grants
    (checkout_session_id, user_id, payment_intent_id, price_id, credit_kind, credits)
  values
    (p_checkout_session_id, p_user_id, p_payment_intent_id, p_price_id, p_credit_kind, p_credits)
  on conflict do nothing
  returning checkout_session_id into inserted_id;

  if inserted_id is null then
    return 'duplicate';
  end if;

  insert into public.cadivor_usage_credit_balances (user_id, credit_kind, credits)
  values (p_user_id, p_credit_kind, p_credits)
  on conflict (user_id, credit_kind) do update
    set credits = public.cadivor_usage_credit_balances.credits + excluded.credits,
        updated_at = now();
  return 'applied';
end;
$$;

create or replace function public.cadivor_reserve_bom_analysis_credit(
  p_user_id uuid,
  p_reservation_id text
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  inserted_id text;
  existing_status text;
begin
  if length(coalesce(p_reservation_id, '')) = 0 or length(p_reservation_id) > 100 then
    raise exception 'invalid credit reservation id';
  end if;

  select status into existing_status
    from public.cadivor_usage_credit_reservations
   where user_id = p_user_id and reservation_id = p_reservation_id;
  if existing_status in ('reserved', 'committed') then
    return true;
  end if;

  insert into public.cadivor_usage_credit_reservations
    (user_id, reservation_id, credit_kind, status)
  values (p_user_id, p_reservation_id, 'bom_analysis', 'reserved')
  on conflict do nothing
  returning reservation_id into inserted_id;
  if inserted_id is null then
    return false;
  end if;

  update public.cadivor_usage_credit_balances
     set credits = credits - 1, updated_at = now()
   where user_id = p_user_id and credit_kind = 'bom_analysis' and credits > 0;
  if not found then
    delete from public.cadivor_usage_credit_reservations
     where user_id = p_user_id and reservation_id = p_reservation_id and status = 'reserved';
    return false;
  end if;
  return true;
end;
$$;

create or replace function public.cadivor_finish_bom_analysis_credit(
  p_user_id uuid,
  p_reservation_id text,
  p_commit boolean
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  did_finish boolean := false;
  existing_status text;
begin
  if p_commit then
    select status into existing_status
      from public.cadivor_usage_credit_reservations
     where user_id = p_user_id and reservation_id = p_reservation_id;
    if existing_status = 'committed' then
      return true;
    end if;
    update public.cadivor_usage_credit_reservations
       set status = 'committed'
     where user_id = p_user_id and reservation_id = p_reservation_id and status = 'reserved';
    return found;
  end if;

  delete from public.cadivor_usage_credit_reservations
   where user_id = p_user_id and reservation_id = p_reservation_id and status = 'reserved';
  did_finish := found;
  if did_finish then
    insert into public.cadivor_usage_credit_balances (user_id, credit_kind, credits)
    values (p_user_id, 'bom_analysis', 1)
    on conflict (user_id, credit_kind) do update
      set credits = public.cadivor_usage_credit_balances.credits + 1,
          updated_at = now();
  end if;
  return did_finish;
end;
$$;

create or replace function public.cadivor_set_professional_api_addon(
  p_user_id uuid,
  p_subscription_id text,
  p_price_id text,
  p_status text
) returns text
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_status in ('active', 'trialing') then
    insert into public.cadivor_professional_api_addons
      (user_id, subscription_id, price_id, status, updated_at)
    values (p_user_id, p_subscription_id, p_price_id, p_status, now())
    on conflict (user_id) do update set
      subscription_id = excluded.subscription_id,
      price_id = excluded.price_id,
      status = excluded.status,
      updated_at = now();
  else
    update public.cadivor_professional_api_addons
       set status = p_status, updated_at = now()
     where user_id = p_user_id and subscription_id = p_subscription_id;
  end if;
  return 'applied';
end;
$$;

create or replace function public.cadivor_allocate_monitored_part_credits(
  p_user_id uuid,
  p_workspace_id text,
  p_required_credits bigint
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  current_credits bigint := 0;
  payer uuid;
  delta bigint;
begin
  if length(coalesce(p_workspace_id, '')) = 0
     or length(p_workspace_id) > 180
     or p_required_credits < 0
     or p_required_credits > 100000 then
    raise exception 'invalid monitored part allocation';
  end if;

  insert into public.cadivor_monitored_part_allocations (workspace_id, paid_by_user, credits)
  values (p_workspace_id, p_user_id, 0)
  on conflict (workspace_id) do nothing;

  select credits, paid_by_user into current_credits, payer
    from public.cadivor_monitored_part_allocations
   where workspace_id = p_workspace_id
   for update;

  if p_required_credits <= current_credits then
    return true;
  end if;

  delta := p_required_credits - current_credits;
  update public.cadivor_usage_credit_balances
     set credits = credits - delta, updated_at = now()
   where user_id = p_user_id and credit_kind = 'monitored_part' and credits >= delta;
  if not found then
    return false;
  end if;

  update public.cadivor_monitored_part_allocations
     set credits = p_required_credits,
         paid_by_user = case when current_credits = 0 then p_user_id else payer end,
         updated_at = now()
   where workspace_id = p_workspace_id;
  return true;
end;
$$;

revoke all on function public.cadivor_grant_usage_credits(text, uuid, text, text, text, bigint) from public, anon, authenticated;
revoke all on function public.cadivor_reserve_bom_analysis_credit(uuid, text) from public, anon, authenticated;
revoke all on function public.cadivor_finish_bom_analysis_credit(uuid, text, boolean) from public, anon, authenticated;
revoke all on function public.cadivor_set_professional_api_addon(uuid, text, text, text) from public, anon, authenticated;
revoke all on function public.cadivor_allocate_monitored_part_credits(uuid, text, bigint) from public, anon, authenticated;
grant execute on function public.cadivor_grant_usage_credits(text, uuid, text, text, text, bigint) to service_role;
grant execute on function public.cadivor_reserve_bom_analysis_credit(uuid, text) to service_role;
grant execute on function public.cadivor_finish_bom_analysis_credit(uuid, text, boolean) to service_role;
grant execute on function public.cadivor_set_professional_api_addon(uuid, text, text, text) to service_role;
grant execute on function public.cadivor_allocate_monitored_part_credits(uuid, text, bigint) to service_role;
