-- Purge public free-audit BOM/result rows after 30 days and minimal lead
-- records after 180 days. Public share links cascade with their report rows.
-- This is separate from the six-hour monitoring schedule.
create or replace function public.cadivor_cleanup_public_bom_audit_data()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    deleted_reports bigint := 0;
    deleted_leads bigint := 0;
begin
    delete from public.cadivor_public_bom_stress_tests
    where created_at < now() - interval '30 days';
    get diagnostics deleted_reports = row_count;

    delete from public.cadivor_public_bom_leads
    where created_at < now() - interval '180 days';
    get diagnostics deleted_leads = row_count;

    return jsonb_build_object(
        'deleted_reports', deleted_reports,
        'deleted_leads', deleted_leads
    );
end;
$$;
revoke all on function public.cadivor_cleanup_public_bom_audit_data() from public, anon, authenticated;
grant execute on function public.cadivor_cleanup_public_bom_audit_data() to service_role;

do $$
begin
    if exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then
        execute $schedule$
            select cron.schedule(
                'cadivor-public-bom-audit-retention',
                '15 3 * * *',
                'select public.cadivor_cleanup_public_bom_audit_data();'
            )
        $schedule$;
    else
        raise notice 'pg_cron is not enabled; public audit cleanup must be scheduled separately.';
    end if;
end;
$$;
