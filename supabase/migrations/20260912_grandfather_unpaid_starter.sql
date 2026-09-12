-- Proposed only. Do not apply until approved.
--
-- Marks existing unpaid Starter/free beta accounts as Grandfathered beta.
-- Does not touch rows that already have a Stripe customer, subscription,
-- price, or subscription status. The existing canceled Starter record has a
-- recorded subscription status, so it is excluded and remains Subscription
-- inactive. Idempotent: a second run changes nothing.
-- Reversible from plan_grandfather_source, which is written only by this
-- migration.
--
-- Production users_plan_check rejected Grandfathered beta, so the plan
-- update did not run. plan_grandfather_source may already exist from that
-- attempt. This script adds the column only if missing, then replaces the
-- check before writing Grandfathered beta. The replacement keeps every
-- value the current constraint already allows, and also allows NULL, legacy
-- Free, Trial expired, Grandfathered beta, and Subscription inactive.
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
  'Durable beta-eligibility marker. Written only for unpaid starter/free rows this migration grandfathered. Null means not grandfathered. Later paid purchases must retain it; do not infer beta from users.plan or Stripe ids.';

-- Replace users_plan_check before any Grandfathered beta write.
-- Drop and add stay in this block so a failed add does not leave the table
-- without its check. A second run sees the expanded constraint and skips.
do $$
declare
  v_def text;
  v_body text;
  v_allowed text := quote_literal('Free') || ', '
    || quote_literal('Student') || ', '
    || quote_literal('Trial') || ', '
    || quote_literal('Trial expired') || ', '
    || quote_literal('Starter') || ', '
    || quote_literal('Professional') || ', '
    || quote_literal('Business') || ', '
    || quote_literal('Enterprise') || ', '
    || quote_literal('Grandfathered beta') || ', '
    || quote_literal('Subscription inactive');
begin
  select pg_get_constraintdef(constraint_row.oid)
    into v_def
  from pg_constraint constraint_row
  where constraint_row.conrelid = 'public.users'::regclass
    and constraint_row.conname = 'users_plan_check'
    and constraint_row.contype = 'c';

  if v_def is not null
     and v_def like '%Grandfathered beta%'
     and v_def like '%Trial expired%'
     and v_def like '%Subscription inactive%'
     and v_def like '%Free%'
     and v_def ilike '%null%' then
    return;
  end if;

  if v_def is not null then
    v_body := substring(v_def from '^\s*CHECK\s*\((.*)\)\s*$');
  end if;

  alter table public.users drop constraint if exists users_plan_check;

  if v_body is null or btrim(v_body) = '' then
    execute format(
      'alter table public.users add constraint users_plan_check check (plan is null or plan in (%s))',
      v_allowed
    );
  else
    execute format(
      'alter table public.users add constraint users_plan_check check ((%s) or plan is null or plan in (%s))',
      v_body,
      v_allowed
    );
  end if;
end $$;

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
