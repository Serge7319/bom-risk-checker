-- Keep monitoring snapshots and alerts attached to the saved BOM and the
-- active workspace. These are text identifiers intentionally: legacy
-- analyses can use non-UUID ids, and access remains enforced by user_id RLS
-- plus the application's verified saved-analysis lookup.
alter table if exists public.part_monitor_history
    add column if not exists analysis_id text,
    add column if not exists workspace_id text;

alter table if exists public.monitor_alerts
    add column if not exists analysis_id text,
    add column if not exists workspace_id text;

comment on column public.part_monitor_history.analysis_id is
    'Saved BOM analysis associated with this supplier snapshot.';
comment on column public.part_monitor_history.workspace_id is
    'Workspace scope associated with this supplier snapshot.';
comment on column public.monitor_alerts.analysis_id is
    'Saved BOM analysis associated with this monitoring alert.';
comment on column public.monitor_alerts.workspace_id is
    'Workspace scope associated with this monitoring alert.';

do $$
begin
    if to_regclass('public.part_monitor_history') is not null then
        execute 'create index if not exists part_monitor_history_scope_created_idx '
             || 'on public.part_monitor_history (user_id, workspace_id, created_at desc)';
    end if;
    if to_regclass('public.monitor_alerts') is not null then
        execute 'create index if not exists monitor_alerts_scope_created_idx '
             || 'on public.monitor_alerts (user_id, workspace_id, created_at desc)';
    end if;
end;
$$;
