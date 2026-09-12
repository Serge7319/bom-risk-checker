-- Proposed only. Do not apply until approved.
--
-- Marks existing unpaid Starter/free beta accounts as Grandfathered beta.
-- Does not touch rows that already have a Stripe customer, subscription,
-- price, or subscription status. Idempotent: a second run changes nothing.
-- Reversible from plan_grandfather_source, which is written only by this
-- migration.
--
-- Prerequisite columns on public.users:
--   plan text
--   stripe_customer_id text
--   stripe_subscription_id text
--   stripe_price_id text
--   stripe_subscription_status text
-- If a Stripe column is absent, stop and confirm the live schema before
-- editing this file. Do not apply a weaker predicate that ignores billing
-- records.

alter table public.users
  add column if not exists plan_grandfather_source text;

comment on column public.users.plan_grandfather_source is
  'Prior users.plan captured when an unpaid Starter/free row was marked Grandfathered beta. Null means this migration did not change the row.';

update public.users
set
  plan_grandfather_source = plan,
  plan = 'Grandfathered beta'
where lower(btrim(coalesce(plan, ''))) in ('starter', 'free')
  and plan_grandfather_source is null
  and coalesce(btrim(stripe_customer_id), '') = ''
  and coalesce(btrim(stripe_subscription_id), '') = ''
  and coalesce(btrim(stripe_price_id), '') = ''
  and coalesce(btrim(stripe_subscription_status), '') = '';

-- Reverse, only for rows this migration recorded:
-- update public.users
-- set
--   plan = plan_grandfather_source,
--   plan_grandfather_source = null
-- where plan = 'Grandfathered beta'
--   and plan_grandfather_source is not null;
