-- Persist component metadata and user-maintained sourcing evidence separately
-- from the original BOM analysis snapshot.
alter table public.analysis_parts
    add column if not exists description text,
    add column if not exists category text,
    add column if not exists supplier_data_verified boolean,
    add column if not exists sourcing_override jsonb not null default '{}'::jsonb,
    add column if not exists sourcing_updated_at timestamptz;

comment on column public.analysis_parts.sourcing_override is
    'Current user-maintained sourcing fields; original analysis columns remain unchanged.';
comment on column public.analysis_parts.sourcing_updated_at is
    'Timestamp of the last manual sourcing evidence update for this component.';
