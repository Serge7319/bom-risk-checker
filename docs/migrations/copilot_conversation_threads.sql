-- Sprint 72.4 — Ask Cadivor conversation persistence
-- One durable thread per authorized user + saved analysis.
--
-- Authorization model:
--   Cadivor server-side Streamlit uses SUPABASE_KEY (service role) and scopes every
--   query in application code with the authenticated user's id (see
--   copilot_conversation_store.py). RLS below is defense-in-depth for direct
--   PostgREST/anon access and matches Supabase user-owned row conventions.

CREATE TABLE IF NOT EXISTS copilot_conversation_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    workspace_id UUID,
    analysis_id TEXT NOT NULL,
    thread JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(thread) = 'array'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, analysis_id)
);

CREATE INDEX IF NOT EXISTS copilot_conversation_threads_analysis_idx
    ON copilot_conversation_threads (analysis_id);

CREATE INDEX IF NOT EXISTS copilot_conversation_threads_workspace_idx
    ON copilot_conversation_threads (workspace_id);

ALTER TABLE copilot_conversation_threads ENABLE ROW LEVEL SECURITY;

CREATE POLICY copilot_conversation_threads_select_own
    ON copilot_conversation_threads
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY copilot_conversation_threads_insert_own
    ON copilot_conversation_threads
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY copilot_conversation_threads_update_own
    ON copilot_conversation_threads
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY copilot_conversation_threads_delete_own
    ON copilot_conversation_threads
    FOR DELETE
    USING (auth.uid() = user_id);
