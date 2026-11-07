-- Reserve one-time credits without checking the legacy Streamlit analyses
-- table. The Next workspace reports are stored in Railway Postgres.
create or replace function public.cadivor_reserve_one_time_bom_order_v2(p_user_id uuid)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_id uuid;
begin
    -- A reservation that never reached the analysis-id attachment is safe to
    -- return to the paid pool after a crash. Once attached, keep it reserved:
    -- the Next API must reconcile it against its own report store.
    update public.cadivor_one_time_bom_orders as o
    set status = 'paid', reserved_at = null
    where o.user_id = p_user_id
      and o.status = 'reserved'
      and o.analysis_id is null
      and o.reserved_at < now() - interval '4 hours';

    select o.id into v_id
    from public.cadivor_one_time_bom_orders as o
    where o.user_id = p_user_id and o.status = 'paid'
    order by o.paid_at, o.created_at
    for update skip locked
    limit 1;

    if v_id is null then
        return null;
    end if;

    update public.cadivor_one_time_bom_orders
    set status = 'reserved', reserved_at = now()
    where id = v_id;
    return v_id;
end;
$$;

revoke all on function public.cadivor_reserve_one_time_bom_order_v2(uuid)
    from public, anon, authenticated;
grant execute on function public.cadivor_reserve_one_time_bom_order_v2(uuid)
    to service_role;

comment on function public.cadivor_reserve_one_time_bom_order_v2(uuid) is
    'Reserve a paid one-time BOM credit for the Next API without consulting the legacy Streamlit analysis store.';
