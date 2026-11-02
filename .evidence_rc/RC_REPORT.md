# Release candidate report

**Branch:** `release/rc-layout-datasheet-compare`  
**Worktree:** `/Users/sergekashambala/Documents/Businesses/bom-risk-checker-rc-integration`  
**Base:** `cc90d69` (= `origin/main`)  
**Commit/push:** not done (review in GitHub Desktop)

## Source worktrees (preserved)

| Path | Branch | HEAD | Dirty |
|------|--------|------|-------|
| `bom-risk-checker-main-current` | `fix/layout-followup` | cc90d69 | 15 files (untouched) |
| `bom-risk-checker-datasheet-compare` | `fix/datasheet-first-part-compare` | cc90d69 | 10 files (untouched) |

## Included files

### From `fix/layout-followup`
- `src/assets/css/monitoring_home_alignment.css`
- `src/assets/css/monitoring_table_final.css`
- `src/authenticated_runtime.py`
- `src/bom_upload_flow.py`
- `src/ui/ei_bom_report.py`
- `src/ui/main_transition.py`
- `src/ui/navigation.py`
- `src/ui/unified_shell.py`
- `tests/test_approved_page_visual_contracts.py`
- `tests/test_bom_workspace_layout.py`
- `tests/test_browser_route_state.py`
- `tests/test_main_transition_slow_route_contract.py`
- `tests/test_navigation_scroll_reset.py`
- `tests/test_workspace_evidence_contract.py`

### From `fix/datasheet-first-part-compare`
- `src/compatibility_gate.py`
- `src/component_family_profiles.py`
- `src/datasheet_comparison.py`
- `src/pages/compare_parts.py`
- `src/parts_compare.py`
- `src/compare_evidence_search.py` (new)
- `tests/test_compare_parts.py`
- `tests/test_rheostat_evidence_comparison.py` (new)

### Merged
- `src/ui/approved_pages.py` — 3-way merge; 2 conflicts in `_render_bom_replacement_approvals` resolved by taking datasheet (`pin_count_applicable` / rheostat interface) side

## Excluded
- `.evidence/` probe artifacts, PDFs, HTML dumps, prior screenshots from datasheet WT (not product code)
- Duplicate leftover WT `bom-risk-checker-rc-candidate` / branch `release/rc-layout-datasheet-candidate` (created during recovery; unused for the candidate — safe to remove later)
- No customer BOMs
- Secrets never printed or copied

## DigiKey integration

BOM Analysis and Compare Parts **share** the same server-side client:

- Client: `integrations/digikey_client.py` → `search_digikey_by_part_number`
- Wiring: `integrations/supplier_aggregator._supplier_lookup_callable("DigiKey")`
- Compare Parts evidence: `src/compare_evidence_search._try_digikey_api_exact_mpn` calls that same callable

**No duplicate DigiKey credentials are required.**

| Secret | Status |
|--------|--------|
| `DIGIKEY_CLIENT_ID` | **missing** |
| `DIGIKEY_CLIENT_SECRET` | **missing** |

## Real-source RES10K

**Did not succeed.** DigiKey API not configured. Authorized HTML probes fail closed (Arrow timeout; Galco/RS Group HTTP 403). Search snippets not used. No blocked bodies used.

## Fixture / synthetic RES10K vs RES10KE

**Kind:** fixture only (Arrow-shaped HTML + Ohmite RES10KE product fields) — **not** live evidence.

| Check | Result |
|-------|--------|
| Ohmite + exact MPN identity | verified both sides |
| KPI == visible rows | 4+0+13 = 17 |
| Citations on populated cells | 12/12 |
| RMS invented | no |

## Focused tests

`62` tests, **EXIT 0** (rheostat evidence, compare upload wiring, BOM layout, nav/scroll, main transition, browser route, workspace evidence, approved visual contracts).

## Layout / workflow coverage

Covered by the focused contract tests above (Home/Monitoring CSS, BOM upload flow, navigation/loading, Procurement/EI report, Compare Parts upload/evidence). New browser screenshots were not captured in this session (no live Streamlit UI run). Prior compare screenshots remain only in the datasheet WT `.evidence/` (excluded from this RC tree).

## Preview / sandbox path (do not deploy production)

Per `docs/RAILWAY_DEPLOYMENT.md`, isolated verification uses **Railway** with the generated `https://<service>.up.railway.app` URL — **not** `app.cadivor.com` until verified.

**Your step after GitHub Desktop push of this branch:**

1. In Railway, open/create a **non-production** service for branch `release/rc-layout-datasheet-compare` (or open an existing preview service and select this branch).
2. Confirm `railway.toml` / `scripts/railway_start.sh` start command.
3. Set `CADIVOR_APP_ORIGIN` to the Railway `.up.railway.app` URL (not production).
4. Ensure DigiKey secrets are present in that Railway service env if you want a real RES10K API compare.
5. Open the Railway URL and exercise Compare Parts + layout flows with synthetic MPNs only.

Do **not** merge to `main` or point DNS/`app.cadivor.com` at this candidate until you sign off.
