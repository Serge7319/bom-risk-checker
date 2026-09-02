-- Cadivor Priority Actions: responsibility roles are separate from access roles.
-- Apply through Supabase migration tooling before enabling the multi-role view.

alter table public.workspace_members
  add column if not exists functional_roles text[] not null default '{}'::text[];

alter table public.workspace_members
  drop constraint if exists workspace_members_functional_roles_valid;

alter table public.workspace_members
  add constraint workspace_members_functional_roles_valid
  check (
    functional_roles <@ array[
      'Supply Chain Manager',
      'Electrical Engineer',
      'Procurement Specialist',
      'Component Engineer'
    ]::text[]
  );

comment on column public.workspace_members.functional_roles is
  'One or more responsibility roles used to match Cadivor Priority Actions. Access remains governed by workspace_members.role.';

create or replace function public.cadivor_set_my_workspace_functional_roles(
  target_workspace_id uuid,
  next_roles text[]
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if coalesce(next_roles, '{}'::text[]) <@ array[
    'Supply Chain Manager',
    'Electrical Engineer',
    'Procurement Specialist',
    'Component Engineer'
  ]::text[] is not true then
    raise exception 'Unsupported responsibility role.';
  end if;

  update public.workspace_members
  set functional_roles = coalesce(next_roles, '{}'::text[]), updated_at = now()
  where workspace_id = target_workspace_id
    and user_id = auth.uid()
    and status = 'active';

  if not found then
    raise exception 'Active workspace membership is required.';
  end if;
end;
$$;

revoke all on function public.cadivor_set_my_workspace_functional_roles(uuid, text[]) from public;
grant execute on function public.cadivor_set_my_workspace_functional_roles(uuid, text[]) to authenticated;
