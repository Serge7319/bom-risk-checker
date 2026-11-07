-- Persist Terms of Service / Privacy Policy acceptance at account creation.
CREATE TABLE IF NOT EXISTS migration_legal_acceptances (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  user_id TEXT,
  workspace_name TEXT,
  source TEXT NOT NULL,
  terms_version TEXT NOT NULL,
  privacy_version TEXT NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS migration_legal_acceptances_email_idx
  ON migration_legal_acceptances (lower(email), accepted_at DESC);
