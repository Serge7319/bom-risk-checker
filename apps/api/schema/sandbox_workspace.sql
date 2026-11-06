-- Cadivor Next.js migration workspace schema.
-- Applied automatically by PostgresWorkspaceStore.ensure_schema(). Use only
-- with the dedicated migration Postgres database, never the existing
-- Streamlit/Supabase saved-BOM data store.

CREATE TABLE IF NOT EXISTS migration_users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'Trial',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS migration_workspace_members (
  user_id TEXT PRIMARY KEY REFERENCES migration_users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  workspace_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'owner',
  trial_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  trial_ends_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '14 days'),
  subscription_status TEXT NOT NULL DEFAULT 'trialing',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ NOT NULL
  DEFAULT (NOW() + INTERVAL '14 days');
ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'trialing';

CREATE INDEX IF NOT EXISTS migration_ws_members_ws_idx
  ON migration_workspace_members (workspace_id);

CREATE TABLE IF NOT EXISTS migration_revoked_tokens (
  jti TEXT PRIMARY KEY,
  exp BIGINT NOT NULL,
  revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS migration_projects (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS migration_projects_ws_name_uidx
  ON migration_projects (workspace_id, name);

CREATE INDEX IF NOT EXISTS migration_projects_ws_idx
  ON migration_projects (workspace_id);

CREATE TABLE IF NOT EXISTS migration_boms (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES migration_projects(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,
  filename TEXT,
  latest_analysis_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS migration_boms_ws_project_name_uidx
  ON migration_boms (workspace_id, project_id, name);

CREATE INDEX IF NOT EXISTS migration_boms_ws_idx
  ON migration_boms (workspace_id);

CREATE TABLE IF NOT EXISTS migration_revisions (
  id TEXT PRIMARY KEY,
  bom_id TEXT NOT NULL REFERENCES migration_boms(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  revision TEXT NOT NULL,
  latest_analysis_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS migration_revisions_ws_bom_rev_uidx
  ON migration_revisions (workspace_id, bom_id, revision);

CREATE INDEX IF NOT EXISTS migration_revisions_ws_idx
  ON migration_revisions (workspace_id);

CREATE TABLE IF NOT EXISTS migration_analyses (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES migration_projects(id) ON DELETE CASCADE,
  bom_id TEXT NOT NULL REFERENCES migration_boms(id) ON DELETE CASCADE,
  revision_id TEXT NOT NULL REFERENCES migration_revisions(id) ON DELETE CASCADE,
  project_name TEXT,
  bom_name TEXT,
  revision TEXT,
  filename TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  health_score DOUBLE PRECISION,
  health_status TEXT,
  high_risk_count INTEGER,
  medium_risk_count INTEGER,
  low_risk_count INTEGER,
  total_parts INTEGER,
  mode TEXT,
  has_hierarchy BOOLEAN DEFAULT FALSE,
  top_rolled_risk TEXT
);

CREATE INDEX IF NOT EXISTS migration_analyses_ws_idx
  ON migration_analyses (workspace_id);

CREATE INDEX IF NOT EXISTS migration_analyses_ws_created_idx
  ON migration_analyses (workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS migration_reports (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS migration_reports_ws_idx
  ON migration_reports (workspace_id);

-- Human-authored, tenant-scoped decisions from the Next.js workspace.
-- The payload retains the comparison evidence as it appeared when recorded.
CREATE TABLE IF NOT EXISTS migration_decision_records (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  analysis_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS migration_decision_records_ws_created_idx
  ON migration_decision_records (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS migration_decision_records_ws_analysis_idx
  ON migration_decision_records (workspace_id, analysis_id, created_at DESC);


-- Monitoring durability (tenant-scoped). Alert email delivery remains gated.
CREATE TABLE IF NOT EXISTS migration_monitoring_alerts (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  analysis_id TEXT,
  part_number TEXT,
  alert_type TEXT,
  severity TEXT,
  message TEXT,
  acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS migration_monitoring_alerts_ws_idx
  ON migration_monitoring_alerts (workspace_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS migration_monitoring_alerts_dedupe_uidx
  ON migration_monitoring_alerts (workspace_id, analysis_id, part_number, alert_type);

CREATE TABLE IF NOT EXISTS migration_notification_preferences (
  workspace_id TEXT PRIMARY KEY,
  email_alerts BOOLEAN NOT NULL DEFAULT FALSE,
  lifecycle BOOLEAN NOT NULL DEFAULT TRUE,
  availability BOOLEAN NOT NULL DEFAULT TRUE,
  risk BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS migration_monitoring_refresh_history (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  analysis_id TEXT,
  alert_count INTEGER NOT NULL DEFAULT 0,
  mode TEXT,
  ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS migration_monitoring_refresh_ws_idx
  ON migration_monitoring_refresh_history (workspace_id, ran_at DESC);

CREATE TABLE IF NOT EXISTS migration_usage_events (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS migration_usage_events_ws_month_idx
  ON migration_usage_events (workspace_id, created_at DESC);
