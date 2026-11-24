-- Admin-issued invoices for customers paying by Stripe, cash, or check.
-- A row grants access only after the signed Stripe invoice.paid event is applied.

create table if not exists public.cadivor_manual_plan_invoices (
  id uuid primary key,
  user_id uuid references public.users(id) on delete set null,
  customer_email_snapshot text,
  plan text not null check (plan in ('Starter', 'Professional', 'Business')),
  billing_interval text not null check (billing_interval in ('month', 'year')),
  price_id text not null,
  amount_minor integer not null check (amount_minor > 0),
  currency text not null check (currency = 'usd'),
  due_days smallint not null check (due_days between 1 and 90),
  stripe_customer_id text,
  stripe_invoice_id text unique,
  hosted_invoice_url text,
  invoice_pdf text,
  invoice_sent_at timestamptz,
  due_at timestamptz,
  status text not null default 'creating'
    check (status in ('creating', 'open', 'payment_recorded', 'paid', 'void')),
  payment_method text
    check (payment_method is null or payment_method in ('stripe', 'cash', 'check', 'offline_unclassified')),
  payment_reference text check (payment_reference is null or length(payment_reference) <= 120),
  payment_recorded_by uuid references auth.users(id) on delete set null,
  payment_recorded_at timestamptz,
  paid_at timestamptz,
  grant_starts_at timestamptz,
  grant_ends_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  stripe_paid_event_id text unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint cadivor_manual_plan_invoice_paid_term_check check (
    (status <> 'paid') or (paid_at is not null)
  ),
  constraint cadivor_manual_plan_invoice_grant_term_check check (
    (grant_starts_at is null and grant_ends_at is null) or
    (grant_starts_at is not null and grant_ends_at > grant_starts_at)
  )
);

create index if not exists cadivor_manual_plan_invoices_user_created_idx
  on public.cadivor_manual_plan_invoices(user_id, created_at desc);
create index if not exists cadivor_manual_plan_invoices_user_active_grant_idx
  on public.cadivor_manual_plan_invoices(user_id, grant_ends_at desc)
  where status = 'paid' and user_id is not null;
create unique index if not exists cadivor_manual_plan_invoices_one_open_per_user_idx
  on public.cadivor_manual_plan_invoices(user_id)
  where user_id is not null and status in ('creating', 'open', 'payment_recorded');

alter table public.cadivor_manual_plan_invoices enable row level security;
revoke all on public.cadivor_manual_plan_invoices from public, anon, authenticated;
grant all on public.cadivor_manual_plan_invoices to service_role;

create or replace function public.cadivor_admin_reserve_manual_plan_invoice(
  p_invoice_id uuid,
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_customer_email text,
  p_plan text,
  p_billing_interval text,
  p_price_id text,
  p_amount_minor integer,
  p_currency text,
  p_due_days integer,
  p_stripe_customer_id text
)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  actor_ok boolean;
  target public.users%rowtype;
  control_status text;
  existing public.cadivor_manual_plan_invoices%rowtype;
  expected_monthly integer;
begin
  select exists (
    select 1 from public.users actor
    left join public.admin_user_controls controls on controls.user_id = actor.id
    where actor.id = p_actor_user_id
      and lower(coalesce(actor.role, '')) = 'admin'
      and coalesce(controls.account_status, 'active') = 'active'
      and not exists (select 1 from public.admin_account_deletion_pending pending where pending.user_id = actor.id)
      and exists (select 1 from auth.users auth_actor where auth_actor.id = actor.id)
  ) into actor_ok;
  if not actor_ok then
    return jsonb_build_object('ok', false, 'code', 'admin_required');
  end if;
  if p_invoice_id is null or p_target_user_id is null or p_actor_user_id = p_target_user_id then
    return jsonb_build_object('ok', false, 'code', 'invalid_target');
  end if;

  select * into target from public.users where id = p_target_user_id for update;
  if not found or not exists (select 1 from auth.users auth_target where auth_target.id = p_target_user_id) then
    return jsonb_build_object('ok', false, 'code', 'account_not_found');
  end if;
  if lower(coalesce(target.role, 'user')) = 'admin' then
    return jsonb_build_object('ok', false, 'code', 'admin_target');
  end if;
  select coalesce(account_status, 'active') into control_status
    from public.admin_user_controls where user_id = p_target_user_id;
  if coalesce(control_status, 'active') <> 'active'
     or exists (select 1 from public.admin_account_deletion_pending where user_id = p_target_user_id) then
    return jsonb_build_object('ok', false, 'code', 'account_unavailable');
  end if;
  if lower(coalesce(target.stripe_subscription_status, '')) in ('active', 'trialing')
     and (target.stripe_current_period_end is null or target.stripe_current_period_end > now()) then
    return jsonb_build_object('ok', false, 'code', 'stripe_subscription_active');
  end if;

  expected_monthly := case p_plan
    when 'Starter' then 2900
    when 'Professional' then 9900
    when 'Business' then 29900
    else null
  end;
  if expected_monthly is null or p_billing_interval not in ('month', 'year')
     or p_price_id is null or length(btrim(p_price_id)) < 8
     or p_currency <> 'usd' or p_due_days < 1 or p_due_days > 90
     or p_amount_minor is null or p_amount_minor <= 0
     or (p_billing_interval = 'month' and p_amount_minor <> expected_monthly)
     or (p_billing_interval = 'year' and p_amount_minor >= expected_monthly * 12)
     or p_stripe_customer_id is null or p_customer_email is null then
    return jsonb_build_object('ok', false, 'code', 'invalid_price_configuration');
  end if;

  perform pg_advisory_xact_lock(hashtextextended('cadivor.manual-plan-invoice:' || p_target_user_id::text, 0));
  select * into existing from public.cadivor_manual_plan_invoices
   where user_id = p_target_user_id and status in ('creating', 'open', 'payment_recorded')
   order by created_at desc limit 1 for update;
  if found then
    if existing.status = 'creating'
       and existing.plan = p_plan
       and existing.billing_interval = p_billing_interval
       and existing.price_id = p_price_id
       and existing.amount_minor = p_amount_minor
       and existing.stripe_customer_id = p_stripe_customer_id then
      return jsonb_build_object('ok', true, 'resumed', true, 'invoice', to_jsonb(existing));
    end if;
    return jsonb_build_object('ok', false, 'code', 'invoice_pending');
  end if;

  insert into public.cadivor_manual_plan_invoices (
    id, user_id, customer_email_snapshot, plan, billing_interval, price_id,
    amount_minor, currency, due_days, stripe_customer_id, created_by
  ) values (
    p_invoice_id, p_target_user_id, lower(btrim(p_customer_email)), p_plan,
    p_billing_interval, p_price_id, p_amount_minor, lower(p_currency),
    p_due_days, p_stripe_customer_id, p_actor_user_id
  ) returning * into existing;
  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (
    p_actor_user_id,
    'manual_plan_invoice_created',
    p_target_user_id,
    jsonb_build_object(
      'invoice_id', existing.id,
      'plan', existing.plan,
      'billing_interval', existing.billing_interval,
      'amount_minor', existing.amount_minor,
      'currency', existing.currency,
      'due_days', existing.due_days
    )
  );
  return jsonb_build_object('ok', true, 'resumed', false, 'invoice', to_jsonb(existing));
exception
  when unique_violation then
    return jsonb_build_object('ok', false, 'code', 'invoice_pending');
end;
$$;

create or replace function public.cadivor_admin_record_manual_plan_payment(
  p_actor_user_id uuid,
  p_invoice_id uuid,
  p_payment_method text,
  p_payment_reference text
)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  invoice_row public.cadivor_manual_plan_invoices%rowtype;
begin
  if not exists (
    select 1 from public.users actor
    left join public.admin_user_controls controls on controls.user_id = actor.id
    where actor.id = p_actor_user_id
      and lower(coalesce(actor.role, '')) = 'admin'
      and coalesce(controls.account_status, 'active') = 'active'
      and not exists (select 1 from public.admin_account_deletion_pending pending where pending.user_id = actor.id)
      and exists (select 1 from auth.users auth_actor where auth_actor.id = actor.id)
  ) then
    return jsonb_build_object('ok', false, 'code', 'admin_required');
  end if;
  if p_payment_method not in ('cash', 'check')
     or coalesce(length(p_payment_reference), 0) > 120 then
    return jsonb_build_object('ok', false, 'code', 'invalid_payment_details');
  end if;
  select * into invoice_row from public.cadivor_manual_plan_invoices
   where id = p_invoice_id for update;
  if not found or invoice_row.user_id is null then
    return jsonb_build_object('ok', false, 'code', 'invoice_not_found');
  end if;
  if invoice_row.status = 'paid' then
    return jsonb_build_object('ok', false, 'code', 'invoice_already_paid');
  end if;
  if invoice_row.status = 'payment_recorded' then
    if invoice_row.payment_method = p_payment_method
       and invoice_row.payment_reference is not distinct from nullif(btrim(p_payment_reference), '') then
      return jsonb_build_object('ok', true, 'already_recorded', true, 'invoice', to_jsonb(invoice_row));
    end if;
    return jsonb_build_object('ok', false, 'code', 'payment_already_recorded');
  end if;
  if invoice_row.status <> 'open' then
    return jsonb_build_object('ok', false, 'code', 'invoice_not_open');
  end if;
  update public.cadivor_manual_plan_invoices
     set status = 'payment_recorded',
         payment_method = p_payment_method,
         payment_reference = nullif(btrim(p_payment_reference), ''),
         payment_recorded_by = p_actor_user_id,
         payment_recorded_at = now(),
         updated_at = now()
   where id = p_invoice_id returning * into invoice_row;
  return jsonb_build_object('ok', true, 'already_recorded', false, 'invoice', to_jsonb(invoice_row));
end;
$$;

create or replace function public.cadivor_apply_manual_plan_invoice_paid(
  p_invoice_id uuid,
  p_stripe_invoice_id text,
  p_stripe_event_id text,
  p_amount_paid integer,
  p_currency text,
  p_paid_at timestamptz,
  p_paid_out_of_band boolean
)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  invoice_row public.cadivor_manual_plan_invoices%rowtype;
  account_profile public.users%rowtype;
  grant_start timestamptz;
  grant_end timestamptz;
  grant_anchor timestamptz;
  next_method text;
  audit_actor_id uuid;
begin
  select * into invoice_row from public.cadivor_manual_plan_invoices
   where id = p_invoice_id for update;
  if not found or invoice_row.stripe_invoice_id is distinct from p_stripe_invoice_id then
    return jsonb_build_object('ok', false, 'code', 'invoice_not_found');
  end if;
  if invoice_row.status = 'paid' then
    if invoice_row.stripe_paid_event_id is null and coalesce(p_stripe_event_id, '') <> '' then
      update public.cadivor_manual_plan_invoices
         set stripe_paid_event_id = p_stripe_event_id, updated_at = now()
       where id = p_invoice_id;
    end if;
    return jsonb_build_object('ok', true, 'outcome', 'already_paid');
  end if;
  if invoice_row.status = 'void' then
    return jsonb_build_object('ok', false, 'code', 'invoice_void');
  end if;
  if invoice_row.status not in ('creating', 'open', 'payment_recorded')
     or p_amount_paid is null
     or p_amount_paid <> invoice_row.amount_minor
     or p_currency is null
     or lower(p_currency) <> invoice_row.currency
     or p_paid_out_of_band is null
     or p_paid_at is null then
    return jsonb_build_object('ok', false, 'code', 'invoice_payment_mismatch');
  end if;
  if p_paid_out_of_band and
     (invoice_row.status <> 'payment_recorded' or invoice_row.payment_method is null
      or invoice_row.payment_method not in ('cash', 'check')) then
    return jsonb_build_object('ok', false, 'code', 'offline_payment_not_recorded');
  end if;

  next_method := case
    when not p_paid_out_of_band then 'stripe'
    when invoice_row.payment_method in ('cash', 'check') then invoice_row.payment_method
    else 'offline_unclassified'
  end;
  grant_start := p_paid_at;
  if invoice_row.user_id is null then
    update public.cadivor_manual_plan_invoices
       set status = 'paid', payment_method = next_method, paid_at = p_paid_at,
           stripe_paid_event_id = nullif(p_stripe_event_id, ''), updated_at = now()
     where id = p_invoice_id;
    return jsonb_build_object('ok', true, 'outcome', 'account_deleted');
  end if;

  select * into account_profile from public.users where id = invoice_row.user_id for update;
  if not found or not exists (select 1 from auth.users where id = invoice_row.user_id)
     or exists (select 1 from public.admin_account_deletion_pending where user_id = invoice_row.user_id) then
    update public.cadivor_manual_plan_invoices
       set status = 'paid', payment_method = next_method, paid_at = p_paid_at,
           stripe_paid_event_id = nullif(p_stripe_event_id, ''), updated_at = now()
     where id = p_invoice_id;
    return jsonb_build_object('ok', true, 'outcome', 'account_unavailable');
  end if;

  select max(grant_ends_at) into grant_anchor
    from public.cadivor_manual_plan_invoices
   where user_id = invoice_row.user_id and status = 'paid' and id <> p_invoice_id;
  grant_start := greatest(p_paid_at, coalesce(grant_anchor, p_paid_at));
  if lower(coalesce(account_profile.stripe_subscription_status, '')) in ('active', 'trialing')
     and account_profile.stripe_current_period_end > grant_start then
    grant_start := account_profile.stripe_current_period_end;
  end if;
  grant_end := case invoice_row.billing_interval
    when 'year' then grant_start + interval '1 year'
    else grant_start + interval '1 month'
  end;

  update public.cadivor_manual_plan_invoices
     set status = 'paid', payment_method = next_method, paid_at = p_paid_at,
         stripe_paid_event_id = nullif(p_stripe_event_id, ''),
         grant_starts_at = grant_start, grant_ends_at = grant_end,
         updated_at = now()
   where id = p_invoice_id;
  audit_actor_id := coalesce(invoice_row.payment_recorded_by, invoice_row.created_by);
  if audit_actor_id is not null
     and exists (select 1 from auth.users where id = audit_actor_id) then
    insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
    values (
      audit_actor_id,
      'manual_plan_invoice_paid',
      invoice_row.user_id,
      jsonb_build_object(
        'invoice_id', invoice_row.id,
        'plan', invoice_row.plan,
        'billing_interval', invoice_row.billing_interval,
        'payment_method', next_method,
        'amount_minor', invoice_row.amount_minor,
        'grant_starts_at', grant_start,
        'grant_ends_at', grant_end
      )
    );
  end if;
  return jsonb_build_object('ok', true, 'outcome', 'applied', 'grant_starts_at', grant_start, 'grant_ends_at', grant_end);
end;
$$;

create or replace function public.cadivor_admin_void_manual_plan_invoice(
  p_actor_user_id uuid,
  p_invoice_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  invoice_row public.cadivor_manual_plan_invoices%rowtype;
begin
  if not exists (
    select 1 from public.users actor
    left join public.admin_user_controls controls on controls.user_id = actor.id
    where actor.id = p_actor_user_id
      and lower(coalesce(actor.role, '')) = 'admin'
      and coalesce(controls.account_status, 'active') = 'active'
      and not exists (select 1 from public.admin_account_deletion_pending pending where pending.user_id = actor.id)
      and exists (select 1 from auth.users auth_actor where auth_actor.id = actor.id)
  ) then
    return jsonb_build_object('ok', false, 'code', 'admin_required');
  end if;
  select * into invoice_row from public.cadivor_manual_plan_invoices
   where id = p_invoice_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'invoice_not_found'); end if;
  if invoice_row.status = 'void' then
    return jsonb_build_object('ok', true, 'already_void', true);
  end if;
  if invoice_row.status <> 'open' then
    return jsonb_build_object('ok', false, 'code', 'invoice_cannot_be_voided');
  end if;
  update public.cadivor_manual_plan_invoices
     set status = 'void', hosted_invoice_url = null, invoice_pdf = null, updated_at = now()
   where id = p_invoice_id;
  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (p_actor_user_id, 'manual_plan_invoice_voided', invoice_row.user_id,
          jsonb_build_object('invoice_id', invoice_row.id, 'stripe_invoice_id', invoice_row.stripe_invoice_id));
  return jsonb_build_object('ok', true, 'already_void', false);
end;
$$;

revoke all on function public.cadivor_admin_reserve_manual_plan_invoice(uuid, uuid, uuid, text, text, text, text, integer, text, integer, text) from public, anon, authenticated;
revoke all on function public.cadivor_admin_record_manual_plan_payment(uuid, uuid, text, text) from public, anon, authenticated;
revoke all on function public.cadivor_apply_manual_plan_invoice_paid(uuid, text, text, integer, text, timestamptz, boolean) from public, anon, authenticated;
revoke all on function public.cadivor_admin_void_manual_plan_invoice(uuid, uuid) from public, anon, authenticated;
grant execute on function public.cadivor_admin_reserve_manual_plan_invoice(uuid, uuid, uuid, text, text, text, text, integer, text, integer, text) to service_role;
grant execute on function public.cadivor_admin_record_manual_plan_payment(uuid, uuid, text, text) to service_role;
grant execute on function public.cadivor_apply_manual_plan_invoice_paid(uuid, text, text, integer, text, timestamptz, boolean) to service_role;
grant execute on function public.cadivor_admin_void_manual_plan_invoice(uuid, uuid) to service_role;

-- Preserve paid financial history while removing account identifiers and links.
create or replace function public.cadivor_admin_finalize_account_deletion(
  p_target_user_id uuid,
  p_actor_user_id uuid
)
returns jsonb
language plpgsql security definer
set search_path = public, auth
as $$
begin
  if p_actor_user_id is null or p_target_user_id is null
     or p_actor_user_id = p_target_user_id then
    raise exception 'An administrator and target account are required';
  end if;
  if not exists (
    select 1 from public.users actor
    where actor.id = p_actor_user_id and lower(coalesce(actor.role, '')) = 'admin'
  ) then
    raise exception 'Cadivor administrator access is required';
  end if;
  if exists (select 1 from auth.users where id = p_target_user_id) then
    raise exception 'The Auth account must be deleted before profile cleanup';
  end if;

  update public.cadivor_manual_plan_invoices
     set user_id = null,
         customer_email_snapshot = null,
         stripe_customer_id = null,
         stripe_invoice_id = null,
         stripe_paid_event_id = null,
         hosted_invoice_url = null,
         invoice_pdf = null,
         payment_reference = null,
         updated_at = now()
   where user_id = p_target_user_id;

  delete from public.users where id = p_target_user_id;
  delete from public.admin_account_deletion_pending where user_id = p_target_user_id;
  insert into public.admin_audit_events (actor_id, action, target_user_id, metadata)
  values (p_actor_user_id, 'account_deleted', null, '{"target_anonymized": true}'::jsonb);
  return jsonb_build_object('deleted', true);
end;
$$;

revoke all on function public.cadivor_admin_finalize_account_deletion(uuid, uuid) from public, anon, authenticated;
grant execute on function public.cadivor_admin_finalize_account_deletion(uuid, uuid) to service_role;
