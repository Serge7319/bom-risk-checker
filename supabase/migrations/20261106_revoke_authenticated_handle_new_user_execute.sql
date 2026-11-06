-- `handle_new_user` is attached only to the auth.users insert trigger.
-- It is SECURITY DEFINER and must not be callable as an authenticated RPC.
-- Keep the trigger itself intact; only remove direct API execution grants.

begin;

revoke all on function public.handle_new_user()
  from public, anon, authenticated;

commit;
