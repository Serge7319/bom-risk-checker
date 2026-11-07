-- Persist Terms of Service / Privacy Policy acceptance at account creation.
-- Not exposed via Supabase Data API: RLS enabled with no anon/authenticated policies;
-- privileges revoked from anon, authenticated, and PUBLIC. Service-role / migration
-- API writes only (server-side).

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

CREATE INDEX IF NOT EXISTS migration_legal_acceptances_user_id_idx
  ON migration_legal_acceptances (user_id)
  WHERE user_id IS NOT NULL;

ALTER TABLE migration_legal_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE migration_legal_acceptances FORCE ROW LEVEL SECURITY;

-- No policies for anon/authenticated: deny by default under RLS.
REVOKE ALL ON TABLE migration_legal_acceptances FROM anon;
REVOKE ALL ON TABLE migration_legal_acceptances FROM authenticated;
REVOKE ALL ON TABLE migration_legal_acceptances FROM PUBLIC;

COMMENT ON TABLE migration_legal_acceptances IS
  'Server-only legal acceptance audit. Not readable/writable via Supabase Data API (RLS + revoked grants). user_id is set when known; otherwise email is the audit identity.';
