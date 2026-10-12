-- Persist the distributor and lifecycle evidence shown in authenticated BOM reports.
-- Existing analyses remain unchanged; rerun an analysis to populate these fields.
alter table public.analysis_parts
    add column if not exists description text,
    add column if not exists category text,
    add column if not exists supplier_data_verified boolean not null default false,
    add column if not exists sourcing_updated_at timestamptz,
    add column if not exists stock_data_sources jsonb not null default '[]'::jsonb,
    add column if not exists stock_data_complete boolean not null default false,
    add column if not exists lifecycle_evidence jsonb not null default '[]'::jsonb,
    add column if not exists lifecycle_conflict boolean not null default false,
    add column if not exists lead_time_source text,
    add column if not exists alternate_search_status text,
    add column if not exists supplier_coverage text;

comment on column public.analysis_parts.stock_data_sources is
    'Distributor sources that explicitly returned an on-hand count for this exact MPN.';
comment on column public.analysis_parts.stock_data_complete is
    'Whether every matched distributor result included a parseable stock count.';
comment on column public.analysis_parts.lifecycle_evidence is
    'Supplier lifecycle status evidence, including source and retrieval time.';
comment on column public.analysis_parts.lifecycle_conflict is
    'True when matched suppliers returned conflicting lifecycle statuses.';
comment on column public.analysis_parts.lead_time_source is
    'Distributor that supplied the lead-time value shown in the analysis.';
comment on column public.analysis_parts.alternate_search_status is
    'Completeness note for the alternate candidate search; candidates are not assumed absent when coverage is incomplete.';
comment on column public.analysis_parts.supplier_coverage is
    'Summary of configured distributor lookup coverage, including unavailable sources.';
