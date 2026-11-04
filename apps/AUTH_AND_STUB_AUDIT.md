# Auth & stub audit — Next.js migration (sandbox)

Branch: `migrate/nextjs-shell-bom-flow` · Environment audited: Railway **sandbox** `cadivor-next-api`  
Production `app.cadivor.com` / production Supabase: **not used by this API**.

## 1) Authentication: smoke login only (not real identities)

| Question | Finding |
| --- | --- |
| Does the API use real authenticated identities? | **No.** Only hardcoded smoke accounts in `apps/api/main.py` (`SMOKE_ACCOUNTS`). |
| Login path | `POST /auth/smoke-login` with fixed email/password pairs. |
| Web login | `apps/web/src/app/login/page.tsx` → `smokeLogin()`; session stored in `localStorage`. |
| Bearer tokens | Static strings (`cadivor-nextjs-smoke-token`, `…-token-b`), not JWTs from Supabase Auth. |
| Production Supabase Auth | **Not wired** on `cadivor-next-api` (`SUPABASE_*` absent). |

**Production blocker:** Replace smoke auth with verified Supabase (or equivalent) sessions before any production cutover. Do not ship smoke tokens to production.

## 2) Workspace identity derivation

| Question | Finding |
| --- | --- |
| Is workspace identity derived from verified credentials? | **Only within the smoke model.** `_auth_context()` maps a valid smoke bearer token → fixed `workspace_id` (`ws-smoke-a` / `ws-smoke-b`). Callers cannot supply an arbitrary workspace id. |
| Client-supplied workspace_id trusted? | **No.** Routes ignore body/query workspace claims; store calls use `ctx["workspace_id"]` from the token map. |
| Cross-tenant enforcement | Store + API raise/404 on foreign ids (proven by pytest + live sandbox). |

**Production blocker:** Map verified user → membership → `workspace_id` from the production identity/workspace tables (Streamlit path already uses Supabase RLS/workspace scope). Smoke map is not a substitute.

## 3) Product pages — live preview vs stub / staged

Classification for the Next shell (`apps/web`):

| Route | Status | Notes |
| --- | --- | --- |
| `/login` | Smoke-only | Migration preview credentials |
| `/` (Home) | **Preview live** | Reads `/workspace/home` from sandbox Postgres; staged items labeled |
| `/bom-analyzer` | **Preview live** | Upload → synthetic analyze → persist |
| `/reports`, `/reports/[id]` | **Preview live** | Workspace-scoped list/detail; synthetic evidence labeled |
| `/monitoring` | Preview API + gap banner | No scheduled refresh / email |
| `/compare-parts` | Preview API + gap banner | Offline/synthetic compare path |
| `/datasheet-qa` | Preview API + gap banner | Upload Q&A preview |
| `/procurement` | Preview API + gap banner | Synthetic prices |
| `/design-impact` | Preview API + gap banner | Analysis-derived |
| `/cost-optimization` | Preview API + gap banner | Synthetic unit prices |
| `/supply-risk` | Preview API + gap banner | Scenario model on saved analysis |
| `/portfolio-intelligence` | Preview API + gap banner | Aggregates preview analyses |
| `/detailed-risk-report` | Preview API + gap banner | Part-level synthetic risk |
| `/engineering-decisions` | **Partial / browser-local** | Uses last analysis in localStorage; not full Streamlit decision workflow |
| `/engineering-intelligence` | **Partial stub** | Mirrors last synthetic analysis; no Streamlit EI parity |
| `/find-replacement` | **Stub** | `ToolPage` + `CapabilityStub` only |
| `/settings` | **Stub / read-only** | Smoke session fields; nothing persisted |

Suppliers, Stripe, and email remain **disabled** on the migration API (`/health`).

## 4) What this does *not* claim

- Not production auth
- Not production customer data
- Not feature parity with Streamlit for stub/partial pages
- Not a green light to point `app.cadivor.com` at this stack
