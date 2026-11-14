-- Abuse protections for the anonymous public BOM audit:
-- preview-only enrichment budget, post-confirm full-enrichment email quota,
-- and QA-mode reserve that skips the IP 2/24h gate (service_role only).

alter table public.cadivor_public_bom_stress_tests
    add column if not exists full_enriched_at timestamptz,
    add column if not exists full_enrichment_started_at timestamptz,
    add column if not exists full_enrichment_lease_expires_at timestamptz,
    add column if not exists qa_mode boolean not null default false,
    add column if not exists preview_enriched_count integer not null default 0;

comment on column public.cadivor_public_bom_stress_tests.full_enriched_at is
    'Set when remaining rows finish supplier enrichment after email confirmation.';
comment on column public.cadivor_public_bom_stress_tests.full_enrichment_started_at is
    'When the current full-enrichment lease was taken (or last refreshed).';
comment on column public.cadivor_public_bom_stress_tests.full_enrichment_lease_expires_at is
    'Active lease end; stale leases do not consume the email quota and may be reclaimed.';
comment on column public.cadivor_public_bom_stress_tests.qa_mode is
    'True when reserved via server-verified QA allowlist; exclude from conversion metrics.';
comment on column public.cadivor_public_bom_stress_tests.preview_enriched_count is
    'How many rows received supplier lookups during the anonymous preview.';

create table if not exists public.cadivor_public_bom_enrichment_budget (
    day date primary key,
    enriched_rows integer not null default 0
        check (enriched_rows >= 0)
);
alter table public.cadivor_public_bom_enrichment_budget enable row level security;
revoke all on public.cadivor_public_bom_enrichment_budget from public, anon, authenticated;
grant all on public.cadivor_public_bom_enrichment_budget to service_role;

-- Atomic UTC-day claim for supplier-enriched row budget (preview + complete).
create or replace function public.cadivor_claim_public_bom_enrichment_budget(
    p_rows integer,
    p_limit integer,
    p_day date default (timezone('utc', now()))::date
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    rows_needed integer := greatest(coalesce(p_rows, 0), 0);
    row_limit integer := greatest(coalesce(p_limit, 0), 0);
    current_rows integer := 0;
begin
    if rows_needed = 0 then
        return true;
    end if;
    if row_limit <= 0 then
        return false;
    end if;

    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('public_bom_enrichment_budget|' || p_day::text, 0)
    );

    insert into public.cadivor_public_bom_enrichment_budget(day, enriched_rows)
    values (p_day, 0)
    on conflict (day) do nothing;

    select enriched_rows into current_rows
    from public.cadivor_public_bom_enrichment_budget
    where day = p_day
    for update;

    if current_rows + rows_needed > row_limit then
        return false;
    end if;

    update public.cadivor_public_bom_enrichment_budget
    set enriched_rows = current_rows + rows_needed
    where day = p_day;

    return true;
end;
$$;

revoke all on function public.cadivor_claim_public_bom_enrichment_budget(integer, integer, date)
    from public, anon, authenticated;
grant execute on function public.cadivor_claim_public_bom_enrichment_budget(integer, integer, date)
    to service_role;

-- One full supplier-backed free audit per confirmed email / rolling window.
-- Counts both completed audits and active (non-stale) in-progress leases.
-- Returns: claimed | already_complete | in_progress | quota_exceeded | not_found
create or replace function public.cadivor_claim_public_bom_full_enrichment(
    p_work_email text,
    p_report_id uuid,
    p_window_days integer default 30,
    p_bypass_email_quota boolean default false,
    p_lease_seconds integer default 900
) returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_email text := lower(btrim(coalesce(p_work_email, '')));
    window_days integer := greatest(coalesce(p_window_days, 30), 1);
    lease_seconds integer := greatest(coalesce(p_lease_seconds, 900), 60);
    report_row public.cadivor_public_bom_stress_tests%rowtype;
    other_count integer := 0;
    lease_active boolean := false;
    lease_until timestamptz;
begin
    if p_report_id is null or normalized_email = '' then
        return 'not_found';
    end if;

    -- Serialize all claim decisions for this email (completed + in-progress).
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('public_bom_full_enrich|' || normalized_email, 0)
    );

    select * into report_row
    from public.cadivor_public_bom_stress_tests
    where id = p_report_id
    for update;

    if not found then
        return 'not_found';
    end if;

    if report_row.work_email is distinct from normalized_email then
        return 'not_found';
    end if;

    if report_row.full_enriched_at is not null then
        return 'already_complete';
    end if;

    lease_active := (
        report_row.full_enrichment_lease_expires_at is not null
        and report_row.full_enrichment_lease_expires_at > now()
    );

    -- Same report with an active lease: idempotent in-progress (do not start
    -- duplicate supplier work). Caller reloads results / waits.
    if lease_active then
        return 'in_progress';
    end if;

    if not coalesce(p_bypass_email_quota, false)
       and not coalesce(report_row.qa_mode, false) then
        select count(*) into other_count
        from public.cadivor_public_bom_stress_tests
        where work_email = normalized_email
          and id <> p_report_id
          and coalesce(qa_mode, false) = false
          and (
              (
                  full_enriched_at is not null
                  and full_enriched_at
                      > now() - make_interval(days => window_days)
              )
              or (
                  full_enriched_at is null
                  and full_enrichment_lease_expires_at is not null
                  and full_enrichment_lease_expires_at > now()
              )
          );
        if other_count > 0 then
            return 'quota_exceeded';
        end if;
    end if;

    -- Clear stale lease metadata, then take a fresh lease on this report.
    lease_until := now() + make_interval(secs => lease_seconds);
    update public.cadivor_public_bom_stress_tests
    set full_enrichment_started_at = now(),
        full_enrichment_lease_expires_at = lease_until
    where id = p_report_id
      and full_enriched_at is null;

    return 'claimed';
end;
$$;

revoke all on function public.cadivor_claim_public_bom_full_enrichment(text, uuid, integer, boolean, integer)
    from public, anon, authenticated;
grant execute on function public.cadivor_claim_public_bom_full_enrichment(text, uuid, integer, boolean, integer)
    to service_role;

-- Drop the previous 4-arg signature if present so callers cannot bypass the lease arg.
drop function if exists public.cadivor_claim_public_bom_full_enrichment(text, uuid, integer, boolean);

-- QA reserve: inserts qa_mode=true without the IP 2/24h count gate.
create or replace function public.cadivor_reserve_public_bom_stress_test_qa(
    p_ip_hash text
) returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    reserved_id uuid;
begin
    if length(p_ip_hash) <> 64 or p_ip_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'Invalid visitor key';
    end if;
    insert into public.cadivor_public_bom_stress_tests(ip_hash, qa_mode)
    values (p_ip_hash, true)
    returning id into reserved_id;
    return reserved_id;
end;
$$;

revoke all on function public.cadivor_reserve_public_bom_stress_test_qa(text)
    from public, anon, authenticated;
grant execute on function public.cadivor_reserve_public_bom_stress_test_qa(text)
    to service_role;
