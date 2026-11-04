# Cadivor north-star capability map (migration branch)

Branch: `migrate/nextjs-shell-bom-flow` · Production `app.cadivor.com` untouched.

Business north star: **continuous engineering workflow** (persistent projects, roll-up risk, ongoing monitoring, self-serve adoption) — not a page-by-page visual port. ARR targets are outcomes of product adoption, not guarantees of this migration slice.

## Goals vs current state

| Goal | Status on this branch | Notes |
| --- | --- | --- |
| Persistent project / BOM / revision / analysis workflows | **Proven on sandbox Postgres** | `CADIVOR_MIGRATION_DATABASE_URL` on `cadivor-next-api` (sandbox only). Analyses survive API redeploy. Production Supabase unused. |
| Multi-level BOMs + risk roll-up + drill-down | **Proven** | Nested fixture on sandbox; hierarchy + top rolled risk retrieved after redeploy. |
| Home / dashboard from saved data | **Proven workspace-scoped** | `GET /workspace/home` filtered by verified smoke workspace. |
| Workspace / tenant isolation | **Proven (live sandbox + pytest)** | Membership-derived `ws-sandbox-a` / `ws-sandbox-b`; cross-workspace list/get/update/delete → 404; client workspace_id ignored. |
| Survive sandbox API redeploy | **Proven** | Flat + nested IDs created on deploy `9c201e7c`, retrieved after redeploys `82109a4c` and `4829a93d`. |
| Proactive monitoring + email alerts | **Staged / preview-only** | Preview monitoring derives signals from analysis only. No scheduled supplier refresh, no email. |
| Self-serve onboarding | **Sandbox JWT only** | Server-verified sandbox JWTs + membership workspaces; production Auth / trial onboarding not migrated. Smoke login removed (410). |
| Usage-based subscription tiers (active BOMs / tracked parts) | **Staged** | Plan field is smoke label; metering not enforced. |
| PLM / ERP / CAD integrations | **Staged** | No connectors; do not present as live. |
| Compliance evidence packs | **Staged** | Report evidence is synthetic-preview labeled; not a compliance export. |
| Tool pages (compare, QA, procurement, …) | **Preview-only** | APIs exist for sandbox smoke; gaps labeled; secondary to persistent workflow. |

## What checks prove (2026-11-04)

| Check | Result |
| --- | --- |
| Sandbox Postgres attached (dedicated, non-prod) | **PASS** — Railway `Postgres` in env `sandbox` |
| Health `backend=postgres`, `durable_across_redeploy=true` | **PASS** |
| Create → redeploy → retrieve same analysis IDs | **PASS** |
| Live cross-workspace list/get/update/delete isolation | **PASS** |
| Local workspace-isolation pytest | **PASS** (9) |
| No localhost API fallback | **PASS** |
| Production / production Supabase changed | **No** |

Evidence (local/sandbox, not all committed): sandbox health postgres; `apps/MIGRATION_TEST_RESULTS.txt`; `apps/MIGRATION_SANDBOX_VERIFY.json`.

Auth / stubs: see `apps/AUTH_AND_STUB_AUDIT.md`.  
Production data plan: see `apps/PRODUCTION_DATA_MIGRATION_PLAN.md` (not executed).

## Explicit non-claims

Do **not** present as production-live until: real Auth (not smoke); production onboarding; monitoring email; plan limits; PLM/ERP/CAD; compliance packs; production cutover (not done). Stub/partial pages remain labeled.
