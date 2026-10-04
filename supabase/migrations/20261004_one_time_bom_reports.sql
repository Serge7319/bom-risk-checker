-- One paid full BOM analysis per verified Cadivor account and Stripe payment.
-- These orders are private to the server and the Stripe webhook. Apply before
-- enabling CADIVOR_ONE_TIME_BOM_REPORT_ENABLED in Railway.
create table if not exists public.cadivor_one_time_bom_orders (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id),
    price_id text not null,
    stripe_session_id text unique,
    payment_intent_id text unique,
    status text not null default 'pending'
        check (status in ('pending', 'paid', 'reserved', 'consumed', 'expired', 'refunded')),
    analysis_id uuid,
    created_at timestamptz not null default now(),
    paid_at timestamptz,
    reserved_at timestamptz,
    consumed_at timestamptz
);
create index if not exists cadivor_one_time_bom_user_status
    on public.cadivor_one_time_bom_orders (user_id, status, created_at);
alter table public.cadivor_one_time_bom_orders enable row level security;
revoke all on public.cadivor_one_time_bom_orders from public, anon, authenticated;
grant all on public.cadivor_one_time_bom_orders to service_role;

create or replace function public.cadivor_fulfill_one_time_bom_order(
    p_order_id uuid,
    p_user_id uuid,
    p_session_id text,
    p_price_id text,
    p_payment_intent_id text
) returns text
language plpgsql security definer set search_path = ''
as $$
declare v_order public.cadivor_one_time_bom_orders%rowtype;
begin
    select * into v_order from public.cadivor_one_time_bom_orders
    where id = p_order_id for update;
    if not found then return 'not_found'; end if;
    if v_order.user_id is distinct from p_user_id
       or v_order.stripe_session_id is distinct from p_session_id
       or v_order.price_id is distinct from p_price_id
       or p_payment_intent_id is null or p_payment_intent_id = '' then
        raise exception 'One-time BOM order does not match Stripe payment';
    end if;
    if v_order.status in ('paid', 'reserved', 'consumed') then
        if v_order.payment_intent_id is distinct from p_payment_intent_id then
            raise exception 'One-time BOM payment intent mismatch';
        end if;
        return 'already_paid';
    end if;
    if v_order.status <> 'pending' then
        raise exception 'One-time BOM order is not pending';
    end if;
    update public.cadivor_one_time_bom_orders
    set status = 'paid', payment_intent_id = p_payment_intent_id, paid_at = now()
    where id = p_order_id;
    return 'applied';
end;
$$;

create or replace function public.cadivor_reserve_one_time_bom_order(p_user_id uuid)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare v_id uuid;
begin
    -- A crashed Streamlit session cannot strand a paid analysis indefinitely.
    update public.cadivor_one_time_bom_orders as o
    set status = 'paid', reserved_at = null, analysis_id = null
    where o.user_id = p_user_id and o.status = 'reserved'
      and o.reserved_at < now() - interval '4 hours'
      and (o.analysis_id is null or not exists (
          select 1 from public.analyses a where a.id = o.analysis_id
      ));
    select id into v_id from public.cadivor_one_time_bom_orders
    where user_id = p_user_id and status = 'paid'
    order by paid_at, created_at for update skip locked limit 1;
    if v_id is null then return null; end if;
    update public.cadivor_one_time_bom_orders
    set status = 'reserved', reserved_at = now() where id = v_id;
    return v_id;
end;
$$;

create or replace function public.cadivor_attach_one_time_bom_analysis(
    p_user_id uuid, p_order_id uuid, p_analysis_id uuid
) returns boolean
language plpgsql security definer set search_path = ''
as $$
begin
    -- Record the intended saved analysis before the summary insert. If a later
    -- reconciliation fails, the reservation cannot be recycled over that BOM.
    update public.cadivor_one_time_bom_orders
    set analysis_id = p_analysis_id
    where id = p_order_id and user_id = p_user_id and status = 'reserved'
      and analysis_id is null;
    if found then return true; end if;
    return exists (select 1 from public.cadivor_one_time_bom_orders
                   where id = p_order_id and user_id = p_user_id
                     and status = 'reserved' and analysis_id = p_analysis_id);
end;
$$;

create or replace function public.cadivor_release_one_time_bom_order(
    p_user_id uuid, p_order_id uuid
) returns boolean
language plpgsql security definer set search_path = ''
as $$
begin
    update public.cadivor_one_time_bom_orders as o
    set status = 'paid', reserved_at = null, analysis_id = null
    where o.id = p_order_id and o.user_id = p_user_id and o.status = 'reserved'
      and (o.analysis_id is null or not exists (
          select 1 from public.analyses a where a.id = o.analysis_id
      ));
    return found;
end;
$$;

create or replace function public.cadivor_consume_one_time_bom_order(
    p_user_id uuid, p_order_id uuid, p_analysis_id uuid
) returns boolean
language plpgsql security definer set search_path = ''
as $$
begin
    -- The saved analysis must belong to this verified user. Replays with the
    -- same analysis are safe; another analysis cannot consume this purchase.
    if not exists (select 1 from public.analyses
                   where id = p_analysis_id and user_id = p_user_id) then
        raise exception 'Saved analysis does not belong to purchaser';
    end if;
    update public.cadivor_one_time_bom_orders
    set status = 'consumed', analysis_id = p_analysis_id, consumed_at = now()
    where id = p_order_id and user_id = p_user_id and status = 'reserved'
      and analysis_id = p_analysis_id;
    if found then return true; end if;
    return exists (select 1 from public.cadivor_one_time_bom_orders
                   where id = p_order_id and user_id = p_user_id
                     and status = 'consumed' and analysis_id = p_analysis_id);
end;
$$;

create or replace function public.cadivor_close_one_time_bom_checkout(
    p_order_id uuid, p_session_id text
) returns text
language plpgsql security definer set search_path = ''
as $$
declare v_status text;
begin
    select status into v_status from public.cadivor_one_time_bom_orders
    where id = p_order_id and stripe_session_id = p_session_id for update;
    if not found then return 'not_found'; end if;
    if v_status = 'pending' then
        update public.cadivor_one_time_bom_orders set status = 'expired'
        where id = p_order_id;
        return 'applied';
    end if;
    return 'already_closed';
end;
$$;

revoke all on function public.cadivor_fulfill_one_time_bom_order(uuid, uuid, text, text, text) from public, anon, authenticated;
revoke all on function public.cadivor_reserve_one_time_bom_order(uuid) from public, anon, authenticated;
revoke all on function public.cadivor_attach_one_time_bom_analysis(uuid, uuid, uuid) from public, anon, authenticated;
revoke all on function public.cadivor_release_one_time_bom_order(uuid, uuid) from public, anon, authenticated;
revoke all on function public.cadivor_consume_one_time_bom_order(uuid, uuid, uuid) from public, anon, authenticated;
revoke all on function public.cadivor_close_one_time_bom_checkout(uuid, text) from public, anon, authenticated;
grant execute on function public.cadivor_fulfill_one_time_bom_order(uuid, uuid, text, text, text) to service_role;
grant execute on function public.cadivor_reserve_one_time_bom_order(uuid) to service_role;
grant execute on function public.cadivor_attach_one_time_bom_analysis(uuid, uuid, uuid) to service_role;
grant execute on function public.cadivor_release_one_time_bom_order(uuid, uuid) to service_role;
grant execute on function public.cadivor_consume_one_time_bom_order(uuid, uuid, uuid) to service_role;
grant execute on function public.cadivor_close_one_time_bom_checkout(uuid, text) to service_role;
