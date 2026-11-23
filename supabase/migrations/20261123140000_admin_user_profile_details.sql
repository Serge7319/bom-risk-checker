-- Let platform administrators view one user's read-only profile details.
-- Authentication secrets and billing identifiers are intentionally excluded.
create or replace function public.cadivor_admin_get_user_profile_v1(target_user_id uuid)
returns jsonb
language sql stable security definer set search_path = public, auth as $$
  select case when public.cadivor_is_admin() then (
    select jsonb_build_object(
      'id', user_profile.id,
      'email', user_profile.email,
      'full_name', user_profile.full_name,
      'role_title', user_profile.role_title,
      'company_name', user_profile.company_name,
      'profile_image_url', user_profile.profile_image_url,
      'role', user_profile.role,
      'plan', user_profile.plan,
      'account_status', case when pending.user_id is not null then 'suspended'
                             else coalesce(controls.account_status, 'active') end,
      'suspended_reason', case when pending.user_id is not null then 'Account deletion pending'
                               else controls.suspended_reason end,
      'trial_started_at', user_profile.trial_started_at,
      'trial_ends_at', user_profile.trial_ends_at,
      'plan_changed_at', user_profile.plan_changed_at,
      'signup_at', auth_user.created_at,
      'last_sign_in_at', auth_user.last_sign_in_at,
      'last_active_at', activity.last_seen_at,
      'activity_status', case
        when activity.last_seen_at >= now() - interval '2 minutes' then 'active'
        when activity.last_seen_at >= now() - interval '15 minutes' then 'idle'
        else 'offline'
      end
    )
      from public.users user_profile
      left join auth.users auth_user on auth_user.id = user_profile.id
      left join public.admin_user_controls controls on controls.user_id = user_profile.id
      left join public.admin_user_activity activity on activity.user_id = user_profile.id
      left join public.admin_account_deletion_pending pending on pending.user_id = user_profile.id
     where user_profile.id = target_user_id
       and (auth_user.id is not null or pending.user_id is not null)
  ) else null end;
$$;

revoke all on function public.cadivor_admin_get_user_profile_v1(uuid) from public, anon;
grant execute on function public.cadivor_admin_get_user_profile_v1(uuid) to authenticated;
