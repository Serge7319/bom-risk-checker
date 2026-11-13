# Paid-promise follow-up — coverage vs gaps (PR #626 update)

**Branch:** `release/paid-promise-followup-gaps`  
**PR:** https://github.com/Serge7319/bom-risk-checker/pull/626  
**Head:** see `HEAD.txt`  
**Verdict alignment:** matches `ACCEPTANCE_MATRIX.md` — paid workflow **not accepted**.

Legend: **PASS** | **BLOCKED** | **PARTIAL**

| Area | Status | Notes |
|---|---|---|
| DigiKey/Mouser/Newark deterministic matrix | **PASS** | Via roadmap-gates CI hook + intended AF workflow YAML |
| Newark www.newark.com HTTPS-only (reject bare host) | **PASS** | Code + matrix updated |
| 15 live Newark production offers | **BLOCKED** | No API key / live pull |
| Supply Risk complete/partial/absent stock | **PASS** | Gap message + preserve lifecycle/supplier |
| Monitoring Notify idle + refresh/Notify split | **PASS** | In CI hook |
| Datasheet synthetic provenance + citation binding | **PASS** | Fixture not claimed as live TI PDF |
| File-store + Postgres two-user isolation in CI | **PASS** | File-store via roadmap-gates hook; Postgres already in AF workflow |
| Production 2nd-account isolation | **BLOCKED** | Not exercised |
| Offer URL + retrieved_at display | **PASS** | Procurement page + unit contract |
| CI run including new suites on PR head | **PENDING** | See `CI_RUN.md` |

## Follow-up closeout

Paid feature scope remains in the acceptance plan. Production gates (15 Newark offers; 2nd production account) stay **BLOCKED**. Do not mark the paid workflow accepted.

OAuth token lacks `workflow` scope, so `.github/workflows/alternative_finder_tests.yml` could not be pushed. Intended YAML is at `alternative_finder_tests.intended.yml`. Suites still execute on this head through `tests/test_nextjs_roadmap_gates.py::test_paid_promise_followup_pytest_suites_in_existing_ci_gate`.
