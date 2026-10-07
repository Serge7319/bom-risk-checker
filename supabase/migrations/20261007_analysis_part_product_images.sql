-- Store authorized distributor product photos with saved BOM components.
-- Existing rows remain valid and simply have no image until re-analyzed.
alter table public.analysis_parts
    add column if not exists image_url text;
