# Historical data disposition plan

**Updated:** November 5, 2026

## Current state

The Next.js app now serves app.cadivor.com. The previous Streamlit Railway services have been removed. Next.js uses Supabase Auth and a dedicated Railway Postgres store for projects, BOMs, revisions, analyses, and reports.

The existing Supabase project and previous app tables remain intact. No saved-BOM records were imported into the new workspace store. The product owner has stated there are no real users yet; still preserve both stores until deciding whether any historical test or demo records are needed.

| Surface | Current storage |
| --- | --- |
| Next.js sign-in | Supabase Auth |
| Next.js workspace and report records | Production Railway Postgres service Postgres-FGtQ |
| Previous app records | Existing Supabase tables; retained but not shown in the Next.js app |
| Disposable recovery drills | Embedded test Postgres only; never the live databases |

## Current product decision

The domain cutover is complete, but historical record migration is not. No bulk import is required to serve the initial app because there are no real users. Do not delete or overwrite the existing Supabase tables as part of this cutover.

If historical test or demo records become useful, migrate only through a reviewed, reversible process:

1. Take a read-only export of selected records from the existing Supabase tables.
2. Transform records offline to the Next.js workspace schema.
3. Validate row counts, ownership mapping, report links, and hashes before import.
4. Import into a separate target or reviewed production tables only after an isolated rehearsal.
5. Record the source, date, counts, and any records intentionally excluded.
6. Keep the original Supabase data unchanged until the imported records have been checked in the app.

## Recovery guidance

The Streamlit Railway service is no longer available for instant rollback. Recover the last known-good Next.js deployment first. Recreating the old application would require a new Railway service and deliberate domain reassignment.

Do not restore a dump over the production Railway Postgres or existing Supabase database. Run any recovery rehearsal against a separate disposable target and keep the two stores isolated.
