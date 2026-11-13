# Paid-promise follow-up — coverage vs gaps (PR #626 update)

**Branch:** `release/paid-promise-followup-gaps`  
**PR:** https://github.com/Serge7319/bom-risk-checker/pull/626  
**Head:** see `HEAD.txt` (full SHA after push)  
**Verdict alignment:** matches `ACCEPTANCE_MATRIX.md` — paid workflow **not accepted**.

Legend: **PASS** | **BLOCKED** | **PARTIAL**

| Area | Status | Notes |
|---|---|---|
| DigiKey/Mouser/Newark deterministic matrix | **PASS** | In AF workflow |
| Newark `www.newark.com` HTTPS-only (reject bare host) | **PASS** | Code + matrix updated |
| 15 live Newark production offers | **BLOCKED** | No API key / live pull |
| Supply Risk complete/partial/absent stock | **PASS** | Gap message + preserve lifecycle/supplier |
| Monitoring Notify idle + refresh/Notify split | **PASS** | In AF workflow |
| Datasheet synthetic provenance + citation binding | **PASS** | Fixture not claimed as live TI PDF |
| File-store + Postgres two-user isolation in CI | **PASS** | Workflow steps added |
| Production 2nd-account isolation | **BLOCKED** | Not exercised |
| Offer URL + retrieved_at display | **PASS** | Procurement page + unit contract |
| CI run including new suites on PR head | **PENDING** | Record in `CI_RUN.md` after green |

## Follow-up closeout

Paid feature scope remains in the acceptance plan. Production gates #3 and #11 stay **BLOCKED**. Do not mark the paid workflow accepted.
