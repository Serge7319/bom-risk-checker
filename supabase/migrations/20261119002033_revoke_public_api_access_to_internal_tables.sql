begin;

-- These tables are backend/admin internals with RLS intentionally denying
-- direct client access. Revoke unnecessary Data API privileges as defense in
-- depth; service_role and postgres retain their grants.
revoke all privileges on table
  public.admin_audit_events,
  public.admin_platform_settings,
  public.admin_support_activity_events,
  public.admin_user_activity,
  public.admin_user_controls,
  public.cadivor_one_time_bom_orders,
  public.cadivor_public_bom_enrichment_budget,
  public.cadivor_public_bom_leads,
  public.cadivor_public_bom_stress_tests,
  public.stripe_webhook_events
from anon, authenticated;

commit;
