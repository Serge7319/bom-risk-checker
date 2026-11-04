-- Cadivor Next.js migration sandbox workspace schema (non-production only).
-- Applied automatically by PostgresWorkspaceStore.ensure_schema() and
-- sandbox_auth Postgres backend. Do NOT point this at production Supabase.

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
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
