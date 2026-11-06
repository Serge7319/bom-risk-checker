# Feature parity matrix — production baseline `d0b955a` (PR #567)

Surfaces compared: marketing site (`marketing-web`), Streamlit app (`src/`), Next.js API (`apps/api`), Next.js web (`apps/web`).

| Capability | Marketing / advertised | Streamlit | API | Next.js before follow-up | Next.js after follow-up | External config needed |
| --- | --- | --- | --- | --- | --- | --- |
| BOM upload / validation / risk roll-up | Yes (`#/analyze`, release-readiness) | Full | `POST /boms/analyze` | Working (`/bom-analyzer`, hierarchy) | Working | Workspace DB; live suppliers optional |
| Ask Cadivor | Yes (product narrative) | Full assistant | Was missing route | Report detail had no Ask panel | `POST /tools/ask-cadivor` + report panel (grounded fallback without OpenAI) | `OPENAI_API_KEY` optional; works offline via local grounding |
| Part comparison | Yes | Full + datasheets | `POST /tools/compare-parts` | Working but thin synthetic → “Needs data” for LM358 vs NE555 | Catalog-enriched synthetic compare; family mismatch when evidence supports | Live suppliers / datasheets for production evidence |
| Find a replacement | Yes | Full Alternative Finder | Was stub only | `/find-replacement` CapabilityStub | Standalone search + optional BOM prefill; clear unable-to-confirm | Live DigiKey/Mouser/Newark for live candidates |
| Supplier lookup / procurement | Advertised | Full | `supplier-lookup`, `procurement` | Procurement page live; lookup unused in UI | Lookup used by replacement + procurement | Provider credentials + transport flags |
| Datasheet Q&A | Yes | Full | `POST /tools/datasheet-qa` | Working | Working | None for local PDF grounding |
| Engineering decisions / approvals | Yes | Full durable queue | Derived from latest report | Partial UI | Reachable; durable independent store still partial | Decision storage migration (Streamlit path) |
| Monitoring | Yes | Full + email | Preferences/alerts/refresh | Working synthetic | Working; email remains mock | Real email sink; scheduled refresh |
| Reports / exports | Yes | Full | Reports CRUD + detailed-risk | Working | Working; detailed risk + Ask on detail | None for synthetic |
| Portfolio intelligence | Yes | Full | `GET /tools/portfolio` | Working | Working | None for synthetic |
| Design impact | Yes | Full | `GET /tools/design-impact` | Working | Working | None for synthetic |
| Cost optimization | Yes | Full | `GET /tools/cost-optimization` | Working | Working | Live quotes for real prices |
| Supply risk | Yes | Full | `POST /tools/supply-risk` | Working | Working | Live disruption feed (not connected) |
| Compliance packs | Implied | Partial | `GET /compliance/{pack}` | API only | Settings surfaces status | Evidence-linked compliance sources |
| Connectors | Implied | Limited | connectors get/sync | API only | Settings surfaces registry | Vendor credentials after customer discovery |
| Billing / plan usage | Yes | Full Stripe | `/billing/*`, `/plan/usage` | Settings stub | Settings shows status; checkout not live | Stripe test keys; live keys blocked |

## Differentiator chain (must stay connected)

`evidence (analysis/parts)` → `engineering review (report + Ask Cadivor + compare/replacement)` → `qualified action / decision record` → `monitoring`

## Truthfulness rules (unchanged)

Do not imply live supplier stock/price, real alert email, or completed Stripe charges when those integrations are disconnected. Label synthetic evidence clearly.
