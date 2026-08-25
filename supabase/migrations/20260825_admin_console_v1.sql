-- Admin Console v1: controlled, read-only operational visibility.
-- Apply through Supabase migration tooling only after review.

create table if not exists public.admin_audit_events (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid not null references auth.users(id),
  action text not null,
  target_user_id uuid references auth.users(id),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.admin_audit_events enable row level security;

create or replace function public.cadivor_is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.users where id = auth.uid() and lower(coalesce(role, '')) = 'admin');
$$;

create or replace function public.cadivor_admin_list_users()
returns table (
  id uuid, email text, full_name text, company_name text, role text, plan text,
  trial_ends_at timestamptz, signup_at timestamptz, last_sign_in_at timestamptz
)
language sql stable security definer set search_path = public, auth as $$
  -- `public.users` has evolved over time. The stable identity columns are
  -- required, while profile fields are read defensively so this read-only
  -- console remains compatible with older customer rows and schema versions.
  select u.id,
         to_jsonb(u) ->> 'email',
         to_jsonb(u) ->> 'full_name',
         to_jsonb(u) ->> 'company_name',
         to_jsonb(u) ->> 'role',
         to_jsonb(u) ->> 'plan',
         nullif(to_jsonb(u) ->> 'trial_ends_at', '')::timestamptz,
         a.created_at,
         a.last_sign_in_at
  from public.users u join auth.users a on a.id = u.id
  where public.cadivor_is_admin()
  order by a.created_at desc;
$$;

create or replace function public.cadivor_admin_audit_events()
returns table (id uuid, actor_id uuid, action text, target_user_id uuid, metadata jsonb, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select id, actor_id, action, target_user_id, metadata, created_at
  from public.admin_audit_events where public.cadivor_is_admin() order by created_at desc limit 100;
$$;

revoke all on function public.cadivor_admin_list_users() from public;
revoke all on function public.cadivor_admin_audit_events() from public;
revoke all on function public.cadivor_is_admin() from public;
grant execute on function public.cadivor_admin_list_users() to authenticated;
grant execute on function public.cadivor_admin_audit_events() to authenticated;
grant execute on function public.cadivor_is_admin() to authenticated;
