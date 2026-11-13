# Acceptance D — fresh-user BOM journey, exports, isolation (disposable only)

All runs use disposable sandbox JWT auth and a throwaway file store or an embedded
throwaway Postgres. No production account was created, no verification email was sent,
no supplier/email transport was configured. Paths/tokens are sanitized.

| Item | Evidence file | Result |
|---|---|---|
| D1 repeat-upload journey (upload→map→validate→analyze→save→navigate away→repeat upload→reload→reopen) | `repeat_upload_journey.json.txt`, `pytest_journey_and_migration_api.txt` | 29 passed |
| D1 existing first-BOM harness unchanged | `harness_first_bom_journey_default.json.txt` | same output shape, exit 0 |
| D1 supabase-auth trial analyze path (mocked Supabase) | `pytest_supabase_auth_trial_analyze.txt` | 18 passed |
| D2 PDF/Excel/CSV parity vs saved BOM | `pytest_exports_parity.txt` | 10 passed, 1 strict xfail (known PDF CJK glyph gap) |
| D3 two-user matrix, file store | `pytest_two_user_isolation_file_store.txt` | 5 passed |
| D3 two-user matrix, disposable Postgres | `pytest_two_user_cutover_disposable_postgres.txt` | 8 passed |
| D4 production second-user check (Finding 5) | — | **BLOCKED** — manual verification by the user; not claimed as passed |

Disposable Postgres note: `embedded_postgres` was not installed in the shared env (the module
otherwise `importorskip`s -> skipped). It was installed to an isolated `--target` dir and used via
`PYTHONPATH`; the shared Python env was not modified.
