# Production database / data migration & rollback plan

**Status:** Planning document only. **Do not execute** against production or
`app.cadivor.com` until product + eng sign-off. Sandbox Postgres credentials
must **never** be copied to production.

## Current state

| Surface | Persistence |
| --- | --- |
| Production Streamlit (`app.cadivor.com`) | Existing Cadivor **Supabase** (analyses, parts, workspaces, auth, billing) |
| Next migration API (sandbox) | Dedicated Railway **Postgres** via `CADIVOR_MIGRATION_DATABASE_URL` + `migration_*` tables |
| Sandbox sibling Streamlit | Separate service; its `SUPABASE_*` is **not** the migration store |

Sandbox schema lives in `apps/api/schema/sandbox_workspace.sql` (`migration_projects`,
`migration_boms`, `migration_revisions`, `migration_analyses`, `migration_reports`).
It is a **preview model**, not a drop-in replacement for production tables.

## Goals for a future production cutover

1. Real Supabase Auth (or equivalent) → verified `user_id` / `workspace_id`
2. Durable analyses readable by the Next app **without** dual-write corruption
3. Instant rollback to Streamlit-only if Next fails health/SLO checks
4. Zero reuse of sandbox DB URLs or smoke tokens in production

## Recommended approach (phased)

### Phase 0 — Preconditions (blockers today)

- [ ] Replace smoke login with production Auth JWT verification
- [ ] Derive `workspace_id` from membership tables / RLS, not smoke maps
- [ ] Decide **single source of truth**: keep writing to existing Supabase
      `analyses` / `analysis_parts` (preferred) vs migrate rows into a new schema
- [ ] Feature flags: `CADIVOR_NEXT_SHELL_ENABLED`, read-only vs write paths
- [ ] Separate production Railway env/services; **new** production DB URL secrets
      (never promote sandbox `CADIVOR_MIGRATION_DATABASE_URL`)

### Phase 1 — Read path (low risk)

1. Deploy Next web + API behind a non-customer hostname or % canary.
2. API verifies Supabase JWT; resolves workspace; **reads** existing Supabase
   analyses for that workspace (adapter, not sandbox `migration_*` tables).
3. Streamlit remains primary writer and DNS for `app.cadivor.com`.
4. Rollback: disable canary / Next hostname; Streamlit unchanged.

### Phase 2 — Dual-write (optional, short)

1. New analyses from Next also insert into production Supabase with the same
   contracts Streamlit uses (`user_id`, `workspace_id`, parts rows).
2. Keep Streamlit writes as today.
3. Monitor row counts, RLS denials, and orphan parts.
4. Rollback: turn off Next writes; leave Supabase data (idempotent cleanup of
   Next-only test rows if any).

### Phase 3 — Cutover DNS / primary UX

1. Point `app.cadivor.com` (or authenticated app host) to Next only after:
   - Auth + workspace isolation e2e on production data
   - Parity gate for BOM analyze / reports / home
   - Stub pages either shipped or removed from nav
2. Keep Streamlit service warm for emergency rollback (freeze deploys).
3. Rollback: revert DNS / Railway public domain to Streamlit; keep Supabase as SoT.

### Phase 4 — Decommission preview store

1. Sandbox `migration_*` Postgres remains sandbox-only forever (or destroy after
   cutover confidence).
2. Do not merge sandbox data into production.

## If choosing to migrate historical rows into a new schema

Only if Phase 1–2 cannot use existing tables:

1. **Export** production analyses for a pilot workspace (read-only dump).
2. **Transform** into the target schema offline; validate counts / hashes.
3. **Import** into a **new** production database (not sandbox).
4. **Shadow read** Next against import while Streamlit still serves customers.
5. **Cutover** after checksum + sample UX review.
6. **Rollback:** abandon new DB; Streamlit + original Supabase unchanged.

Prefer **not** doing a big-bang copy; prefer adapters over the live Supabase schema.

## Rollback summary

| Failure mode | Action |
| --- | --- |
| Next auth/workspace bug | Disable Next flag / revert DNS to Streamlit |
| Bad writes to Supabase | Disable Next write flag; repair via known Streamlit/admin paths |
| New DB import wrong | Do not cut DNS; drop/ignore new DB; original Supabase untouched |
| Sandbox creds leaked to prod config | Rotate immediately; never use sandbox URL in prod |

## Explicit non-actions (this PR / this milestone)

- No production deploy
- No changes to `app.cadivor.com`
- No copying sandbox Postgres URL into production
- No production Supabase schema apply from `sandbox_workspace.sql`
