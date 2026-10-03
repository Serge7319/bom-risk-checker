-- Public BOM audit storage is never exposed to anon/authenticated PostgREST.
-- Only the server's service role can reserve and read reports. Run this before
-- enabling CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED in the app.
create table if not exists public.cadivor_public_bom_stress_tests (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    ip_hash text not null,
    filename text,
    row_count integer not null default 0,
    results jsonb not null default '[]'::jsonb,
    work_email text,
    status text not null default 'reserved'
        check (status in ('reserved', 'ready', 'lead_captured'))
);
create index if not exists cadivor_public_bom_stress_ip_time
    on public.cadivor_public_bom_stress_tests (ip_hash, created_at desc);
create index if not exists cadivor_public_bom_stress_email_time
    on public.cadivor_public_bom_stress_tests (work_email, created_at desc);
alter table public.cadivor_public_bom_stress_tests enable row level security;
revoke all on public.cadivor_public_bom_stress_tests from public, anon, authenticated;
grant all on public.cadivor_public_bom_stress_tests to service_role;

create table if not exists public.cadivor_public_bom_leads (
    report_id uuid primary key,
    created_at timestamptz not null default now(),
    work_email text not null,
    row_count integer not null,
    high_risk_count integer not null default 0,
    unverified_count integer not null default 0,
    source text not null default 'homepage_stress_test'
);
alter table public.cadivor_public_bom_leads enable row level security;
revoke all on public.cadivor_public_bom_leads from public, anon, authenticated;
grant all on public.cadivor_public_bom_leads to service_role;

create or replace function public.cadivor_reserve_public_bom_stress_test(p_ip_hash text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare reserved_id uuid;
begin
    if length(p_ip_hash) <> 64 or p_ip_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Invalid visitor key';
    end if;
    -- A per-IP transactional lock prevents two concurrent requests each seeing
    -- one remaining slot. The window is rolling 24 hours, not calendar-day based.
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_ip_hash, 0));
    if (select count(*) from public.cadivor_public_bom_stress_tests
        where ip_hash = p_ip_hash and created_at > now() - interval '24 hours') >= 2 then
        raise exception 'PUBLIC_BOM_DAILY_LIMIT';
    end if;
    insert into public.cadivor_public_bom_stress_tests(ip_hash)
    values(p_ip_hash) returning id into reserved_id;
    return reserved_id;
end;
$$;
revoke all on function public.cadivor_reserve_public_bom_stress_test(text) from public, anon, authenticated;
grant execute on function public.cadivor_reserve_public_bom_stress_test(text) to service_role;

-- Schedule this through Supabase cron (or an existing operations scheduler):
-- delete from public.cadivor_public_bom_stress_tests where created_at < now() - interval '7 days';
-- The minimal lead table remains for sales after the BOM evidence expires.
