-- Persist manufacturer datasheet links alongside supplier product links.
-- Existing saved analyses are left unchanged; new analyses and reanalyses
-- populate this optional evidence field.
alter table public.analysis_parts
    add column if not exists datasheet_url text;

comment on column public.analysis_parts.datasheet_url is
    'Manufacturer or distributor datasheet URL returned for this exact BOM part.';

-- Monitoring snapshots and alerts retain the exact supplier links that support
-- a lifecycle, stock, or price event so reviewers can inspect its source.
alter table if exists public.part_monitor_history
    add column if not exists product_url text,
    add column if not exists datasheet_url text;

alter table if exists public.monitor_alerts
    add column if not exists supplier text,
    add column if not exists product_url text,
    add column if not exists datasheet_url text;
