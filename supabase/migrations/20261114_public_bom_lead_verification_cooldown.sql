-- Durable verification-email claim for the anonymous public BOM audit.
-- verification_sent_at is set before OTP send so repeat POSTs are idempotent.
alter table public.cadivor_public_bom_leads
    add column if not exists verification_sent_at timestamptz;

comment on column public.cadivor_public_bom_leads.verification_sent_at is
    'Set when a verification email send slot is claimed; used for resend cooldown.';

-- Atomic claim: only one concurrent request for a report/email wins during cooldown.
create or replace function public.cadivor_claim_public_bom_verification(
    p_report_id uuid,
    p_work_email text,
    p_cooldown_seconds integer default 900
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    claimed boolean := false;
    normalized_email text := lower(btrim(coalesce(p_work_email, '')));
    cooldown integer := greatest(coalesce(p_cooldown_seconds, 900), 0);
begin
    if p_report_id is null or normalized_email = '' then
        return false;
    end if;

    -- Serialize concurrent claims for the same report/email pair.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_report_id::text || '|' || normalized_email, 0)
    );

    update public.cadivor_public_bom_leads
    set verification_sent_at = pg_catalog.now()
    where report_id = p_report_id
      and work_email = normalized_email
      and (
          verification_sent_at is null
          or verification_sent_at
             <= pg_catalog.now() - make_interval(secs => cooldown)
      );

    get diagnostics claimed = row_count;
    return claimed;
end;
$$;

revoke all on function public.cadivor_claim_public_bom_verification(uuid, text, integer)
    from public, anon, authenticated;
grant execute on function public.cadivor_claim_public_bom_verification(uuid, text, integer)
    to service_role;
