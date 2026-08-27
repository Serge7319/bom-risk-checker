-- Admin Console v2.1: support activity timeline.
-- REVIEW ONLY: do not apply until this pull request has been approved.

create table if not exists public.admin_support_activity_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null check (event_type in ('session_started', 'page_viewed')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint admin_support_activity_metadata_size check (pg_column_size(metadata) <= 2048)
);

create index if not exists admin_support_activity_events_created_at_idx
  on public.admin_support_activity_events (created_at desc);
create index if not exists admin_support_activity_events_user_id_created_at_idx
  on public.admin_support_activity_events (user_id, created_at desc);

alter table public.admin_support_activity_events enable row level security;

create or replace function public.cadivor_record_support_activity(
  event_type text, event_metadata jsonb default '{}'::jsonb
)
returns void language plpgsql security definer set search_path = public as $$
declare
  normalized_type text := lower(trim(coalesce(event_type, '')));
begin
  if auth.uid() is null then
    raise exception 'Authenticated access is required';
  end if;
  if normalized_type not in ('session_started', 'page_viewed') then
    raise exception 'Unsupported support activity event';
  end if;
  insert into public.admin_support_activity_events (user_id, event_type, metadata)
  values (auth.uid(), normalized_type, coalesce(event_metadata, '{}'::jsonb));
end;
$$;

create or replace function public.cadivor_admin_support_activity_events()
returns table (id uuid, user_id uuid, email text, full_name text, event_type text, metadata jsonb, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select event.id, event.user_id, to_jsonb(user_profile) ->> 'email',
         to_jsonb(user_profile) ->> 'full_name', event.event_type, event.metadata, event.created_at
  from public.admin_support_activity_events event
  join public.users user_profile on user_profile.id = event.user_id
  where public.cadivor_is_admin()
  order by event.created_at desc
  limit 250;
$$;

revoke all on function public.cadivor_record_support_activity(text, jsonb) from public;
revoke all on function public.cadivor_admin_support_activity_events() from public;
grant execute on function public.cadivor_record_support_activity(text, jsonb) to authenticated;
grant execute on function public.cadivor_admin_support_activity_events() to authenticated;
