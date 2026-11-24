-- Recreated functions inherit Supabase's default anon EXECUTE grants unless
-- they are explicitly removed; platform maintenance RPCs are auth-only.

revoke all on function public.cadivor_admin_runtime_access()
  from public, anon, authenticated;
revoke all on function public.cadivor_admin_get_planned_maintenance()
  from public, anon, authenticated;
revoke all on function public.cadivor_admin_set_planned_maintenance(text, timestamptz, timestamptz)
  from public, anon, authenticated;

grant execute on function public.cadivor_admin_runtime_access() to authenticated;
grant execute on function public.cadivor_admin_get_planned_maintenance() to authenticated;
grant execute on function public.cadivor_admin_set_planned_maintenance(text, timestamptz, timestamptz) to authenticated;

notify pgrst, 'reload schema';
