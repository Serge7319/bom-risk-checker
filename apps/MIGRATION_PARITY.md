# Next.js migration route parity checklist

Branch: `migrate/nextjs-shell-bom-flow` · Production `app.cadivor.com` untouched.

| Route | Streamlit / product reference | Migration status | Data source | Explicit gaps |
| --- | --- | --- | --- | --- |
| `/login` | Smoke / auth gate | Working (sandbox smoke only) | `POST /auth/smoke-login` | Production auth (Supabase) not migrated |
| `/` Home | Home workspace / portfolio overview | Working | Latest in-memory analysis summary | No durable portfolio history |
| `/bom-analyzer` | BOM Analyzer | Working | `POST /boms/analyze` | Distributors disabled |
| `/reports` | Reports index | Working (browser + API list) | `GET /reports` + localStorage | Durable report-history persistence gap |
| `/reports/[id]` | Engineering Intelligence report | Working | `GET /reports/{id}` | — |
| `/engineering-decisions` | Decision queue | Working (analysis-derived) | Latest analysis risk counts | No saved decision DB |
| `/engineering-intelligence` | EI landing | Working (links to report) | Latest analysis | Multi-BOM EI packs not mirrored |
| `/monitoring` | Monitoring Center / monitoring_engine | Working (preview) | Alerts derived from analysis parts via `build_alert_record` | No Supabase `monitor_alerts` / scheduled refresh |
| `/compare-parts` | Compare Parts / `parts_compare` | Working (preview) | `build_parts_comparison` on analysis or synthetic records | Live supplier lookup disabled |
| `/datasheet-qa` | Datasheet Q&A | Working | Upload PDF → `extract_uploaded_datasheet` + `answer_datasheet_question` | Cloud AI optional; local grounded answers |
| `/procurement` | Procurement Advisor | Working (preview) | Analysis parts; supplier offers empty when disabled | Live distributor pricing disabled |
| `/design-impact` | Design Impact Analyzer | Working (preview) | `build_design_impact` on in-memory analyses/parts | Needs ≥1 analyzed BOM |
| `/cost-optimization` | Cost Optimization | Working (preview) | `build_cost_optimization` on synthetic unit prices | Prices are synthetic-preview, not live quotes |
| `/supply-risk` | Supply Risk Scenario | Working (preview) | `build_supply_scenario` on analysis stock fields | Scenario uses synthetic stock evidence |
| `/portfolio-intelligence` | Portfolio Intelligence | Working (preview) | `build_portfolio_intelligence` on in-memory reports | No Streamlit saved-BOM mirror |
| `/detailed-risk-report` | Detailed Risk Report / `component_rows` | Working (preview) | `component_rows` + `report_exposure_summary` | Export bytes optional later |
| `/find-replacement` | Alternative Finder | Stub / limited | — | Live alternate search not in sandbox scope this slice |
| `/settings` | Settings | Read-only smoke session | Smoke session fields | Workspace admin not migrated |

## Tracked migration gaps (do not claim complete)

1. **Report-history persistence** — in-memory API store + browser localStorage only; lost on container recycle.
2. **Production authentication** — smoke login is sandbox-only; Supabase production auth not wired.
3. **Live supplier / Stripe / email** — intentionally disabled in sandbox.
4. **Supabase monitoring tables** — alerts are analysis-derived, not durable monitor history.


## Builder reuse (sandbox-safe)

| Surface | Primary builders | Must not invent |
| --- | --- | --- |
| Monitoring | `build_alert_record` / analysis-derived queue | Live stock/price deltas, scheduled refresh |
| Compare Parts | `build_parts_comparison` on analysis/synthetic part dicts | Parametric matches without evidence; live lookup |
| Datasheet Q&A | `extract_uploaded_datasheet` + `answer_datasheet_question` (local-excerpts) | Specs absent from PDF |
| Procurement | `build_procurement_advisor` on saved/synthetic parts | Distributor prices when offers empty |
| Design Impact | `build_design_impact` | Multi-BOM history beyond in-memory reports |
| Cost Optimization | `build_cost_optimization` on recorded unit_price | Live quotes |
| Supply Risk | `build_supply_scenario` | Live disruption feed |
| Portfolio | `build_portfolio_intelligence` | Durable saved-BOM mirror |
| Detailed Risk | `component_rows` + `report_exposure_summary` | Live distributor refresh |
