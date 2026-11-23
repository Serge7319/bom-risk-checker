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

-- One row per (user, workspace). Membership here is the authoritative access
-- source for the Next app, including memberships created by invitations.
CREATE TABLE IF NOT EXISTS migration_workspace_members (
  user_id TEXT NOT NULL REFERENCES migration_users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  workspace_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'owner',
  trial_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  trial_ends_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '14 days'),
  subscription_status TEXT NOT NULL DEFAULT 'trialing',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, workspace_id)
);

ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ NOT NULL
  DEFAULT (NOW() + INTERVAL '14 days');
ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'trialing';
ALTER TABLE migration_workspace_members
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';

-- Upgrade legacy single-workspace-per-user primary keys in place.
DO $$
DECLARE
  pk_name text;
  pk_cols int;
BEGIN
  SELECT conname, array_length(conkey, 1) INTO pk_name, pk_cols
    FROM pg_constraint
   WHERE conrelid = 'migration_workspace_members'::regclass
     AND contype = 'p';
  IF pk_name IS NOT NULL AND pk_cols = 1 THEN
    EXECUTE 'ALTER TABLE migration_workspace_members DROP CONSTRAINT '
      || quote_ident(pk_name);
    ALTER TABLE migration_workspace_members
      ADD PRIMARY KEY (user_id, workspace_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS migration_ws_members_ws_idx
  ON migration_workspace_members (workspace_id);

CREATE TABLE IF NOT EXISTS migration_user_active_workspace (
  user_id TEXT PRIMARY KEY REFERENCES migration_users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

-- A random bearer token is returned once; only its SHA-256 hash is stored.
-- Shares are read-only and expire automatically after the configured period.
CREATE TABLE IF NOT EXISTS migration_decision_record_shares (
  token_hash TEXT PRIMARY KEY CHECK (length(token_hash) = 64 AND token_hash ~ '^[0-9a-f]{64}$'),
  workspace_id TEXT NOT NULL,
  decision_record_id TEXT NOT NULL REFERENCES migration_decision_records(id) ON DELETE CASCADE,
  created_by TEXT REFERENCES migration_users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS migration_decision_record_shares_expiry_idx
  ON migration_decision_record_shares (expires_at);

-- An approver invitation is scoped to one decision only. The raw bearer token
-- is emailed once and never stored; acceptance writes an append-only response
-- record without granting workspace access.
CREATE TABLE IF NOT EXISTS migration_decision_record_approvers (
  token_hash TEXT PRIMARY KEY CHECK (length(token_hash) = 64 AND token_hash ~ '^[0-9a-f]{64}$'),
  workspace_id TEXT NOT NULL,
  decision_record_id TEXT NOT NULL REFERENCES migration_decision_records(id) ON DELETE CASCADE,
  created_by TEXT REFERENCES migration_users(id) ON DELETE SET NULL,
  email TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'revoked')),
  response_rationale TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  responded_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS migration_decision_record_approvers_expiry_idx
  ON migration_decision_record_approvers (expires_at);


-- Existing installations originally cascaded shared links when their creator
-- account was removed. Keep the workspace record and clear only its creator.
ALTER TABLE migration_decision_record_shares ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE migration_decision_record_shares
  DROP CONSTRAINT IF EXISTS migration_decision_record_shares_created_by_fkey;
ALTER TABLE migration_decision_record_shares
  ADD CONSTRAINT migration_decision_record_shares_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES migration_users(id) ON DELETE SET NULL;
ALTER TABLE migration_decision_record_approvers ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE migration_decision_record_approvers
  DROP CONSTRAINT IF EXISTS migration_decision_record_approvers_created_by_fkey;
ALTER TABLE migration_decision_record_approvers
  ADD CONSTRAINT migration_decision_record_approvers_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES migration_users(id) ON DELETE SET NULL;

-- Workspace-scoped outbound developer webhooks. Endpoint URLs and signing
-- secrets are encrypted by the API before insertion. Delivery payloads are
-- retained only as long as needed for bounded retries and status history.
CREATE TABLE IF NOT EXISTS migration_developer_webhooks (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,
  endpoint_ciphertext TEXT NOT NULL,
  signing_secret_ciphertext TEXT NOT NULL,
  event_types JSONB NOT NULL DEFAULT '[]'::jsonb,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS migration_developer_webhooks_workspace_active_idx
  ON migration_developer_webhooks (workspace_id, active, created_at DESC);

CREATE TABLE IF NOT EXISTS migration_developer_webhook_deliveries (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  webhook_id TEXT NOT NULL REFERENCES migration_developer_webhooks(id) ON DELETE CASCADE,
  event_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'delivered', 'failed')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  response_status INTEGER,
  failure_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  delivered_at TIMESTAMPTZ,
  UNIQUE (webhook_id, event_id)
);

CREATE INDEX IF NOT EXISTS migration_developer_webhook_deliveries_due_idx
  ON migration_developer_webhook_deliveries (status, next_attempt_at, created_at);

CREATE INDEX IF NOT EXISTS migration_developer_webhook_deliveries_workspace_idx
  ON migration_developer_webhook_deliveries (workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS migration_account_entitlement_overrides (
  user_id TEXT PRIMARY KEY,
  feature_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_by TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable supplier quote snapshots tied to the exact saved BOM analysis.
CREATE TABLE IF NOT EXISTS migration_procurement_quotes (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  analysis_id TEXT NOT NULL,
  requested_mpn TEXT NOT NULL,
  requested_manufacturer TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  payload JSONB NOT NULL,
  FOREIGN KEY (analysis_id) REFERENCES migration_reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS migration_procurement_quotes_ws_analysis_part_idx
  ON migration_procurement_quotes
    (workspace_id, analysis_id, LOWER(requested_mpn), LOWER(requested_manufacturer), created_at DESC);


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
  weekly_digest BOOLEAN NOT NULL DEFAULT FALSE,
  slack_alerts BOOLEAN NOT NULL DEFAULT FALSE,
  slack_webhook_ciphertext TEXT,
  lifecycle BOOLEAN NOT NULL DEFAULT TRUE,
  availability BOOLEAN NOT NULL DEFAULT TRUE,
  risk BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE migration_notification_preferences
  ADD COLUMN IF NOT EXISTS weekly_digest BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE migration_notification_preferences
  ADD COLUMN IF NOT EXISTS slack_alerts BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE migration_notification_preferences
  ADD COLUMN IF NOT EXISTS slack_webhook_ciphertext TEXT;

CREATE TABLE IF NOT EXISTS migration_workspace_monitoring_capacity (
  workspace_id TEXT PRIMARY KEY,
  max_parts INTEGER,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (max_parts IS NULL OR max_parts >= 0)
);

-- Member-level opt-in: emails always go to the verified account address
-- established by the authenticated API, never a browser-supplied recipient.
CREATE TABLE IF NOT EXISTS migration_monitoring_member_preferences (
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES migration_users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  email_alerts BOOLEAN NOT NULL DEFAULT FALSE,
  weekly_digest BOOLEAN NOT NULL DEFAULT FALSE,
  supplier_checks BOOLEAN NOT NULL DEFAULT FALSE,
  lifecycle BOOLEAN NOT NULL DEFAULT TRUE,
  availability BOOLEAN NOT NULL DEFAULT TRUE,
  risk BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);
ALTER TABLE migration_monitoring_member_preferences
  ADD COLUMN IF NOT EXISTS weekly_digest BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS migration_monitoring_member_preferences_schedule_idx
  ON migration_monitoring_member_preferences (workspace_id, supplier_checks, email_alerts);

-- Most recent identity-matched live supplier evidence for each monitored part.
CREATE TABLE IF NOT EXISTS migration_monitoring_snapshots (
  workspace_id TEXT NOT NULL,
  analysis_id TEXT NOT NULL,
  part_number TEXT NOT NULL,
  payload JSONB NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, analysis_id, part_number)
);

CREATE INDEX IF NOT EXISTS migration_monitoring_snapshots_ws_retrieved_idx
  ON migration_monitoring_snapshots (workspace_id, retrieved_at DESC);

-- Claims and receipts prevent overlapping scheduled cycles from emailing the
-- same active alert repeatedly. Resolved alerts clear receipts and may notify
-- again if the same condition becomes active later.
CREATE TABLE IF NOT EXISTS migration_monitoring_email_deliveries (
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES migration_users(id) ON DELETE CASCADE,
  alert_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('sending', 'sent')),
  lease_until TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id, alert_id)
);

CREATE INDEX IF NOT EXISTS migration_monitoring_email_deliveries_lease_idx
  ON migration_monitoring_email_deliveries (status, lease_until);

-- Workspace-level Slack sends use short leases and retry after transient
-- delivery failures without posting the same active alert repeatedly.
CREATE TABLE IF NOT EXISTS migration_monitoring_slack_deliveries (
  workspace_id TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'sending'
    CHECK (status IN ('sending', 'sent')),
  lease_until TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, alert_id)
);

CREATE INDEX IF NOT EXISTS migration_monitoring_slack_deliveries_pending_idx
  ON migration_monitoring_slack_deliveries (updated_at)
  WHERE status <> 'sent';

-- Per-member claim/receipt for weekly monitoring summaries. The scheduler may
-- run several times a day, but a successful member digest is sent at most once
-- every seven days.
CREATE TABLE IF NOT EXISTS migration_monitoring_digest_deliveries (
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES migration_users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('sending', 'sent', 'failed')),
  lease_until TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS migration_monitoring_digest_deliveries_lease_idx
  ON migration_monitoring_digest_deliveries (status, lease_until, sent_at);

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

-- Durable status for long-running six-hour supplier polling cycles. The cron
-- caller receives a run ID quickly and polls this row until the worker ends.
CREATE TABLE IF NOT EXISTS migration_monitoring_scheduled_runs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'completed_with_failures', 'failed')),
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS migration_monitoring_scheduled_runs_one_active_uidx
  ON migration_monitoring_scheduled_runs (status)
  WHERE status = 'running';

CREATE INDEX IF NOT EXISTS migration_monitoring_scheduled_runs_updated_idx
  ON migration_monitoring_scheduled_runs (updated_at DESC);

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
