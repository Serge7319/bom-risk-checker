-- Store the supplier product page returned with the saved offer.
-- Existing rows stay valid and have no link until the BOM is analyzed again.
alter table public.analysis_parts
    add column if not exists product_url text;
