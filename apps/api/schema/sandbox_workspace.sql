-- Cadivor Next.js migration sandbox workspace schema (non-production only).
-- Applied automatically by PostgresWorkspaceStore.ensure_schema().
-- Do NOT point this at production Supabase.

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
