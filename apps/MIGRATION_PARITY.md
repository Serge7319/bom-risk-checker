# Next.js route and capability status

**Updated:** November 5, 2026

The Next.js app now serves https://app.cadivor.com. The old Streamlit Railway services have been removed. Next.js uses Supabase Auth and its dedicated Railway Postgres workspace store. Existing Supabase saved-BOM records have not been imported, and the analysis engine currently labels supplier and price values as synthetic.

| Route | Current status | Data source and remaining gap |
| --- | --- | --- |
| /login | Available | Supabase Auth; hosted login/logout lifecycle still needs a second-account end-to-end check |
| /signup | Gated off | API signup flag remains closed pending email, redirect, abuse-control, and leaked-password checks |
| / Home | Working | Saved analyses in the Next workspace; previous app history is not imported |
| /bom-analyzer | Working for synthetic BOMs | CSV upload, analysis, and persistence in Railway Postgres; live supplier evidence is disabled |
| /reports | Working | Workspace-scoped saved report list; production backup/recovery drill remains open |
| /reports/[id] | Working | Saved report and evidence envelopes; evidence remains synthetic unless a live source is enabled |
| /engineering-decisions | Partial | Shows saved-analysis risk counts; decision and approval history is not separately persisted |
| /engineering-intelligence | Partial | Reads the latest saved report; multi-BOM decision history is incomplete |
| /monitoring | Partial | Durable alerts and preferences from saved analyses; no scheduled refresh or real email |
| /compare-parts | Preview | Saved fields and clearly labeled synthetic values; live supplier lookup is disabled |
| /datasheet-qa | Preview | Answers are grounded in uploaded datasheet text; no full document-management workflow |
| /procurement | Preview | Analysis parts only; no live distributor offer feed |
| /design-impact | Preview | Uses Next workspace analyses; previous app catalog/history is not imported |
| /cost-optimization | Preview | Synthetic unit-price estimates; no live quotes or contract pricing |
| /supply-risk | Preview | Explicit scenario assumptions and saved fields; no live disruption feed |
| /portfolio-intelligence | Partial | Reads Next workspace analyses; previous app portfolio history is not imported |
| /detailed-risk-report | Preview | Saved analysis rows; live distributor refresh and complete export workflow remain open |
| /find-replacement | Limited | Live alternate search and fit scoring are not implemented |
| /settings | Limited | Plan usage and billing status are visible; workspace administration and checkout are not implemented |

## Production readiness gates

1. **Onboarding:** signup remains closed until email confirmation and delivery, HTTPS redirects, abuse controls, and leaked-password protection are verified. Complete the second-account hosted E2E after those checks.
2. **Evidence:** supplier lookup remains mocked; live calls need migration-owned provider credentials and an authorized transport.
3. **Monitoring:** alert history and preferences persist, but there is no scheduler or real email transport.
4. **Commercial:** plan limits are enforced; checkout preparation does not create a Stripe session and no charge is possible.
5. **Integrations:** generic CSV import is available; vendor-specific connectors require customer discovery and sandbox credentials.
6. **Compliance:** packs preserve evidence provenance and missing-evidence labels; no live compliance declarations are enabled.
7. **Post-cutover recovery:** the domain is on Next.js and Streamlit services are removed. Production database recovery and hosted cross-workspace checks remain open.

## Data and evidence rules

| Surface | Current data | Do not imply |
| --- | --- | --- |
| Monitoring | Saved-analysis-derived signals and durable history | Live stock or price changes, scheduled refresh, or sent alerts |
| Compare Parts | Saved fields and synthetic supplier values | A live supplier lookup when disabled |
| Datasheet Q&A | Text extracted from the uploaded document | Specifications absent from the source document |
| Procurement and Cost | Saved prices or synthetic estimates | Distributor quotes or contract pricing |
| Design and Portfolio | Next workspace analyses | Imported historical records |
| Supply Risk | Explicit scenario assumptions | Live disruption monitoring |
| Detailed Risk | Saved analysis rows | Live distributor refresh |
| Compliance | Evidence-linked records | RoHS, REACH, or CMRT compliance without sourced declarations |
| Billing | Plan catalog and test-mode readiness | Completed charges or active checkout |

The production UI labels synthetic evidence and disconnected integrations. Do not label mock data as verified supplier evidence or claim full product readiness from the successful deployment alone.
