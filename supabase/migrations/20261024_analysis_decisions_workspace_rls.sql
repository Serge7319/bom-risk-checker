-- Make Alternative Finder approvals reproducible and writable by the
-- authenticated owner within an active workspace.
create table if not exists public.analysis_decisions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id text,
    analysis_id text,
    context_key text not null default 'standalone',
    project_name text not null default '',
    engineer_name text not null default '',
    original_part text not null,
    alternative_part text not null,
    decision text not null default 'Approved',
    engineering_note text not null default '',
    recommendation_score integer not null default 0,
    recommendation_rating text not null default '',
    compatibility_confidence integer not null default 0,
    compatibility_rating text not null default '',
    lifecycle text not null default '',
    risk text not null default '',
    supplier text not null default '',
    stock integer not null default 0,
    unit_price numeric not null default 0,
    package text not null default '',
    stock_delta text not null default '',
    price_delta text not null default '',
    source_snapshot jsonb not null default '{}'::jsonb,
    comparison_snapshot jsonb not null default '{}'::jsonb,
    archived_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Older manually provisioned decision tables may not have carried the workspace
-- scope even though the application writes it. Keep that scope as text, like the
-- analysis identifiers used by existing BOM routes.
alter table public.analysis_decisions
    add column if not exists workspace_id text,
    add column if not exists analysis_id text;

create index if not exists analysis_decisions_owner_scope_lookup_idx
    on public.analysis_decisions (user_id, workspace_id, context_key, original_part, alternative_part);

revoke all on table public.analysis_decisions from anon;
grant select, insert, update on table public.analysis_decisions to authenticated;
alter table public.analysis_decisions enable row level security;

drop policy if exists analysis_decisions_authenticated_select
    on public.analysis_decisions;
create policy analysis_decisions_authenticated_select
    on public.analysis_decisions
    for select to authenticated
    using (
        auth.uid() is not null
        and user_id::text = auth.uid()::text
        and (
            workspace_id is null
            or exists (
                select 1
                from public.workspace_members as wm
                where wm.workspace_id::text = analysis_decisions.workspace_id::text
                  and wm.user_id::text = auth.uid()::text
                  and wm.status = 'active'
            )
        )
    );

drop policy if exists analysis_decisions_authenticated_insert
    on public.analysis_decisions;
create policy analysis_decisions_authenticated_insert
    on public.analysis_decisions
    for insert to authenticated
    with check (
        auth.uid() is not null
        and user_id::text = auth.uid()::text
        and (
            workspace_id is null
            or exists (
                select 1
                from public.workspace_members as wm
                where wm.workspace_id::text = analysis_decisions.workspace_id::text
                  and wm.user_id::text = auth.uid()::text
                  and wm.status = 'active'
            )
        )
    );

drop policy if exists analysis_decisions_authenticated_update
    on public.analysis_decisions;
create policy analysis_decisions_authenticated_update
    on public.analysis_decisions
    for update to authenticated
    using (
        auth.uid() is not null
        and user_id::text = auth.uid()::text
        and (
            workspace_id is null
            or exists (
                select 1
                from public.workspace_members as wm
                where wm.workspace_id::text = analysis_decisions.workspace_id::text
                  and wm.user_id::text = auth.uid()::text
                  and wm.status = 'active'
            )
        )
    )
    with check (
        auth.uid() is not null
        and user_id::text = auth.uid()::text
        and (
            workspace_id is null
            or exists (
                select 1
                from public.workspace_members as wm
                where wm.workspace_id::text = analysis_decisions.workspace_id::text
                  and wm.user_id::text = auth.uid()::text
                  and wm.status = 'active'
            )
        )
    );

comment on table public.analysis_decisions is
    'Authenticated, workspace-scoped engineering decisions for Alternative Finder approvals.';
