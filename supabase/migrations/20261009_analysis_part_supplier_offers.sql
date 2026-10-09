-- Store every priced distributor offer returned for a saved BOM line.
-- Existing rows stay valid and have no offer list until the BOM is analyzed again.
alter table public.analysis_parts
    add column if not exists supplier_offers jsonb;
