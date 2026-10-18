-- Store independent notification choices used by the Settings dashboard.
alter table if exists public.user_preferences
    add column if not exists notification_preferences jsonb not null default '{}'::jsonb;

update public.user_preferences
set notification_preferences = jsonb_build_object(
    'project_activity', coalesce(workspace_notifications, true),
    'simulation_results', coalesce(report_notifications, true),
    'team_activity', coalesce(workspace_notifications, true),
    'product_updates', coalesce(email_notifications, true),
    'marketing_emails', false
)
where notification_preferences = '{}'::jsonb;

comment on column public.user_preferences.notification_preferences is
    'Independent project, simulation, team, product, and marketing notification preferences.';
