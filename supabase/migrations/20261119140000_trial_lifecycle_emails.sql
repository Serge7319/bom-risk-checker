-- Idempotent delivery ledger for the trial onboarding sequence.
-- The sender uses service-role access only; end users cannot inspect or mutate it.
create table if not exists public.cadivor_trial_lifecycle_email_sends (
  user_id uuid not null references auth.users(id) on delete cascade,
  milestone text not null check (milestone in ('day_0', 'day_2', 'day_7', 'day_12')),
  status text not null default 'sending' check (status in ('sending', 'sent', 'failed')),
  attempted_at timestamptz not null default now(),
  sent_at timestamptz,
  last_error text,
  primary key (user_id, milestone)
);

create index if not exists cadivor_trial_lifecycle_email_sends_pending_idx
  on public.cadivor_trial_lifecycle_email_sends (attempted_at)
  where status <> 'sent';

alter table public.cadivor_trial_lifecycle_email_sends enable row level security;
revoke all on public.cadivor_trial_lifecycle_email_sends from public, anon, authenticated;
grant all on public.cadivor_trial_lifecycle_email_sends to service_role;

create or replace function public.cadivor_claim_trial_lifecycle_email(
  p_user_id uuid,
  p_milestone text,
  p_lease_seconds integer default 900
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  claimed boolean := false;
begin
  if p_milestone not in ('day_0', 'day_2', 'day_7', 'day_12') then
    raise exception 'invalid trial email milestone';
  end if;

  insert into public.cadivor_trial_lifecycle_email_sends
    (user_id, milestone, status, attempted_at, sent_at, last_error)
  values (p_user_id, p_milestone, 'sending', now(), null, null)
  on conflict (user_id, milestone) do update
    set status = 'sending', attempted_at = now(), sent_at = null, last_error = null
    where public.cadivor_trial_lifecycle_email_sends.status <> 'sent'
      and public.cadivor_trial_lifecycle_email_sends.attempted_at
        < now() - make_interval(secs => greatest(60, least(p_lease_seconds, 3600)))
  returning true into claimed;

  return coalesce(claimed, false);
end;
$$;

create or replace function public.cadivor_finish_trial_lifecycle_email(
  p_user_id uuid,
  p_milestone text,
  p_delivered boolean,
  p_error text default null
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.cadivor_trial_lifecycle_email_sends
     set status = case when p_delivered then 'sent' else 'failed' end,
         sent_at = case when p_delivered then now() else null end,
         last_error = case when p_delivered then null else left(coalesce(p_error, 'delivery_failed'), 240) end
   where user_id = p_user_id and milestone = p_milestone and status = 'sending';
  return found;
end;
$$;

revoke all on function public.cadivor_claim_trial_lifecycle_email(uuid, text, integer) from public, anon, authenticated;
revoke all on function public.cadivor_finish_trial_lifecycle_email(uuid, text, boolean, text) from public, anon, authenticated;
grant execute on function public.cadivor_claim_trial_lifecycle_email(uuid, text, integer) to service_role;
grant execute on function public.cadivor_finish_trial_lifecycle_email(uuid, text, boolean, text) to service_role;
