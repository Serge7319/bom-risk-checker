-- Harden SECURITY DEFINER execute privileges for the shared Cadivor Supabase project.
--
-- Context: live advisor/report found anon EXECUTE on SECURITY DEFINER functions.
-- Trigger-only helpers such as cadivor_write_audit_event(...) and
-- cadivor_audit_engineering_record(...) must not be callable by anon or
-- authenticated (they accept caller-supplied audit fields / are trigger-only).
--
-- This migration:
-- 1) Revokes anon (and public) EXECUTE from every public SECURITY DEFINER function.
-- 2) Explicitly revokes anon + authenticated from known trigger-only helpers.
-- 3) Re-grants authenticated EXECUTE only to Streamlit/app RPCs that the
--    repository already calls with the user JWT.
-- 4) Leaves service_role grants alone.
--
-- Safe to re-run. Skips missing functions/signatures so it can be applied even
-- when live-only helpers are absent from a disposable database.

begin;

-- ---------------------------------------------------------------------------
-- 1. Revoke anon/public from all public SECURITY DEFINER routines.
-- ---------------------------------------------------------------------------
do $$
declare
  r record;
begin
  for r in
    select n.nspname as schema_name,
           p.proname as func_name,
           pg_get_function_identity_arguments(p.oid) as identity_args
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.prosecdef is true
  loop
    execute format(
      'revoke all on function %I.%I(%s) from public, anon',
      r.schema_name,
      r.func_name,
      r.identity_args
    );
  end loop;
end
$$;

-- ---------------------------------------------------------------------------
-- 2. Trigger-only helpers: no direct RPC from anon or authenticated.
--    These names are live-project helpers; revoke every overloaded signature.
-- ---------------------------------------------------------------------------
do $$
declare
  r record;
  trigger_helpers text[] := array[
    'cadivor_write_audit_event',
    'cadivor_audit_engineering_record'
  ];
  helper text;
begin
  foreach helper in array trigger_helpers loop
    for r in
      select n.nspname as schema_name,
             p.proname as func_name,
             pg_get_function_identity_arguments(p.oid) as identity_args
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
        and p.proname = helper
    loop
      execute format(
        'revoke all on function %I.%I(%s) from public, anon, authenticated',
        r.schema_name,
        r.func_name,
        r.identity_args
      );
    end loop;
  end loop;
end
$$;

-- ---------------------------------------------------------------------------
-- 3. Preserve authenticated grants required by Streamlit / user-JWT RPCs.
--    Match by name across overloads present in the target database.
-- ---------------------------------------------------------------------------
do $$
declare
  r record;
  allowed text[] := array[
    'cadivor_is_admin',
    'cadivor_admin_list_users',
    'cadivor_admin_list_users_v2',
    'cadivor_admin_audit_events',
    'cadivor_admin_runtime_access',
    'cadivor_admin_overview',
    'cadivor_admin_set_account_status',
    'cadivor_admin_set_role',
    'cadivor_admin_set_maintenance',
    'cadivor_admin_support_activity_events',
    'cadivor_record_user_activity',
    'cadivor_record_support_activity',
    'cadivor_accept_my_workspace_invitations',
    'cadivor_set_my_workspace_functional_roles'
  ];
  fname text;
begin
  foreach fname in array allowed loop
    for r in
      select n.nspname as schema_name,
             p.proname as func_name,
             pg_get_function_identity_arguments(p.oid) as identity_args
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
        and p.proname = fname
    loop
      execute format(
        'grant execute on function %I.%I(%s) to authenticated',
        r.schema_name,
        r.func_name,
        r.identity_args
      );
      -- Defense in depth: keep anon revoked even for allowed authenticated RPCs.
      execute format(
        'revoke all on function %I.%I(%s) from public, anon',
        r.schema_name,
        r.func_name,
        r.identity_args
      );
    end loop;
  end loop;
end
$$;

-- Service-role-only helpers stay service_role (already revoked from anon/authenticated
-- in prior migrations). Re-assert anon/authenticated revoke for known names.
do $$
declare
  r record;
  service_only text[] := array[
    'cadivor_claim_stripe_webhook_event',
    'cadivor_complete_stripe_webhook_event',
    'cadivor_release_stripe_webhook_event',
    'cadivor_apply_stripe_billing_snapshot',
    'cadivor_fulfill_one_time_bom_order',
    'cadivor_reserve_one_time_bom_order',
    'cadivor_attach_one_time_bom_analysis',
    'cadivor_release_one_time_bom_order',
    'cadivor_consume_one_time_bom_order',
    'cadivor_close_one_time_bom_checkout',
    'cadivor_reserve_public_bom_stress_test'
  ];
  fname text;
begin
  foreach fname in array service_only loop
    for r in
      select n.nspname as schema_name,
             p.proname as func_name,
             pg_get_function_identity_arguments(p.oid) as identity_args
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
        and p.proname = fname
    loop
      execute format(
        'revoke all on function %I.%I(%s) from public, anon, authenticated',
        r.schema_name,
        r.func_name,
        r.identity_args
      );
    end loop;
  end loop;
end
$$;

commit;
