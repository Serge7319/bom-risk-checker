-- Preserve the currency belonging to the selected distributor unit price.
-- Existing analyses remain NULL until they are re-run or contain a matching
-- supplier offer from which the exporter can safely recover the currency.
alter table public.analysis_parts
    add column if not exists unit_price_currency text;

comment on column public.analysis_parts.unit_price_currency is
    'ISO 4217 currency code explicitly associated with the saved selected unit price.';
