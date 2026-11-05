# Next.js migration route parity checklist

`app.cadivor.com` remains on Streamlit. This checklist describes the separate Next.js migration test build on Railway subdomains; it is not a customer-domain cutover record.

| Route | Migration status | Current data source | Remaining gaps |
| --- | --- | --- | --- |
| `/login` | Supabase auth path available on migration API | Supabase Auth; membership derives workspace | Hosted login lifecycle not re-run; signup remains feature-gated; reset/invite not implemented |
| `/` Home | Working | Saved migration workspace records | Existing Streamlit data is not imported |
| `/bom-analyzer` | Working for synthetic test flow | Uploaded CSV → saved migration Postgres record | Live supplier evidence is disabled |
| `/reports` | Working | Workspace-scoped saved report list | Production migration DB redeploy/recovery check outstanding |
| `/reports/[id]` | Working | Workspace-scoped saved report | Supplier evidence remains synthetic in this build |
| `/engineering-decisions` | Partial | Latest saved report risk counts | Decisions/approvals are not independently persisted |
| `/engineering-intelligence` | Partial | Latest saved report | Multi-BOM engineering record/history is not fully mirrored |
| `/monitoring` | Preview | Signals derived from saved BOM analyses | No scheduled refresh, durable alert history, or email delivery |
| `/compare-parts` | Preview | Saved analysis fields or synthetic records | Live supplier lookup is disabled |
| `/datasheet-qa` | Preview | Uploaded datasheet extraction and grounded answer | No full production document-management workflow |
| `/procurement` | Preview | Analysis parts; no live offer feed | Live distributor pricing is disabled |
| `/design-impact` | Preview | Saved migration analyses | Existing Streamlit catalog/history is not imported |
| `/cost-optimization` | Preview | Synthetic unit prices | Not live quotes or contract pricing |
| `/supply-risk` | Preview | Scenario assumptions and saved fields | No live disruption feed |
| `/portfolio-intelligence` | Partial preview | Saved migration workspace analyses | Existing Streamlit portfolio history is not imported |
| `/detailed-risk-report` | Preview | Saved synthetic analysis rows | Live distributor refresh and complete export workflow are outstanding |
| `/find-replacement` | Limited/stub | — | Live alternate search and fit scoring are not implemented here |
| `/settings` | Read-only/limited | Signed-in workspace display fields | Workspace administration and billing are not implemented here |

## Production-readiness gaps

1. Signup/trial code is implemented behind a closed feature gate; configure email verification/delivery, redirect allowlisting, and abuse controls, then verify the hosted end-to-end lifecycle before enabling.
2. Live distributor evidence, including exact-part identity, source URL, retrieval time, and source-label/unit handling.
3. Scheduled monitoring refresh, alert history, notification preferences, and email delivery.
4. Enforced plans/usage metering and billing.
5. Production-service persistence recovery and cross-workspace isolation tests.
6. PLM/ERP/CAD integrations and compliance evidence packs.
7. Cutover and rollback rehearsal before `app.cadivor.com` moves from Streamlit.

## Builder truthfulness rules

| Surface | Allowed data | Never imply |
| --- | --- | --- |
| Monitoring | Saved-analysis-derived signals | Live stock/price changes, scheduled refresh, or sent alerts |
| Compare Parts | Saved fields, uploaded datasheets, clearly marked synthetic fields | Live supplier lookup when disabled |
| Datasheet Q&A | Extracted text from the uploaded datasheet | Specs absent from the document |
| Procurement / Cost | Saved prices or clearly marked synthetic estimates | Distributor quotes or contract prices when offers are unavailable |
| Design / Portfolio | Migration workspace analyses | Imported Streamlit history when none exists |
| Supply Risk | Explicit scenario assumptions and saved fields | Live disruption monitoring |
| Detailed Risk | Saved analysis rows | Live distributor refresh |
