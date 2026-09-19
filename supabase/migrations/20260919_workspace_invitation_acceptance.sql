-- Secure, email-matched workspace invitation acceptance.
-- Apply before enabling invitation email delivery in production.

do $$
begin
  if to_regclass('public.workspace_invites') is null
     or to_regclass('public.workspace_members') is null
     or to_regclass('public.workspaces') is null then
    raise exception 'Cadivor workspace tables must exist before invitation acceptance is installed.';
  end if;
end $$;

alter table public.workspace_invites
  add column if not exists accepted_at timestamptz;

create or replace function public.cadivor_accept_my_workspace_invitations()
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  current_user_id uuid := auth.uid();
  current_email text := lower(coalesce(auth.jwt() ->> 'email', ''));
  invite_row record;
  workspace_title text;
  accepted jsonb := '[]'::jsonb;
begin
  if current_user_id is null or current_email = '' then
    raise exception 'Authentication with an email address is required.';
  end if;

  for invite_row in
    select invitation.id, invitation.workspace_id, invitation.role
      from public.workspace_invites invitation
     where lower(invitation.email) = current_email
       and invitation.status = 'pending'
       and (invitation.expires_at is null or invitation.expires_at > now())
     order by invitation.created_at
     for update
  loop
    if exists (
      select 1
        from public.workspace_members member
       where member.workspace_id = invite_row.workspace_id
         and member.user_id = current_user_id
    ) then
      update public.workspace_members
         set status = 'active'
       where workspace_id = invite_row.workspace_id
         and user_id = current_user_id;
    else
      insert into public.workspace_members (
        workspace_id,
        user_id,
        email,
        display_name,
        role,
        status,
        joined_at
      ) values (
        invite_row.workspace_id,
        current_user_id,
        current_email,
        initcap(replace(split_part(current_email, '@', 1), '.', ' ')),
        case
          when lower(coalesce(invite_row.role, '')) in ('admin', 'engineer', 'viewer')
            then lower(invite_row.role)
          else 'viewer'
        end,
        'active',
        now()
      );
    end if;

    update public.workspace_invites
       set status = 'accepted',
           accepted_at = now(),
           updated_at = now()
     where id = invite_row.id;

    select workspace.name
      into workspace_title
      from public.workspaces workspace
     where workspace.id = invite_row.workspace_id;

    accepted := accepted || jsonb_build_array(
      jsonb_build_object(
        'workspace_id', invite_row.workspace_id,
        'workspace_name', coalesce(workspace_title, 'Cadivor Workspace')
      )
    );
  end loop;

  return accepted;
end;
$$;

revoke all on function public.cadivor_accept_my_workspace_invitations()
  from public, anon;
grant execute on function public.cadivor_accept_my_workspace_invitations()
  to authenticated;
