-- Time-limited, read-only aggregate shares for anonymous free BOM previews.
-- Raw bearer tokens are never stored; public and authenticated roles cannot
-- query this table. The API uses the service role after verifying ownership.
create table if not exists public.cadivor_public_bom_audit_shares (
    token_hash text primary key
        check (length(token_hash) = 64 and token_hash ~ '^[0-9a-f]{64}$'),
    report_id uuid not null
        references public.cadivor_public_bom_stress_tests(id) on delete cascade,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    revoked_at timestamptz
);
create index if not exists cadivor_public_bom_audit_shares_report_idx
    on public.cadivor_public_bom_audit_shares (report_id, created_at desc);
create index if not exists cadivor_public_bom_audit_shares_expiry_idx
    on public.cadivor_public_bom_audit_shares (expires_at);
alter table public.cadivor_public_bom_audit_shares enable row level security;
revoke all on public.cadivor_public_bom_audit_shares from public, anon, authenticated;
grant all on public.cadivor_public_bom_audit_shares to service_role;
