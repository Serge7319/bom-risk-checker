-- Admin Console v2.1 follow-up: deduplicate rapid session-start events.
-- Apply manually after the corresponding application deployment is live.

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

  if normalized_type = 'session_started' and exists (
    select 1
    from public.admin_support_activity_events
    where user_id = auth.uid()
      and event_type = 'session_started'
      and created_at >= now() - interval '10 minutes'
  ) then
    return;
  end if;

  insert into public.admin_support_activity_events (user_id, event_type, metadata)
  values (auth.uid(), normalized_type, coalesce(event_metadata, '{}'::jsonb));
end;
$$;
