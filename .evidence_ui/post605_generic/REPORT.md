# Post-#605 generic follow-up

Branch: `fix/post-605-generic-followup`  
Base: `main` @ `c7b4478` (PR #605 merged)

## Changes

1. **Compare progress** — Progress copy shows design baseline MPN and the candidate being processed (`design <baseline> vs candidate <mpn>`). Multi-candidate settlement advances completed count per pair; results stay index-mapped to the correct MPNs. 60s per-pair bound + `Promise.allSettled` preserved; timeouts stay Needs verification.
2. **Manufacturer identity (generic)** — Registry + live-hit disambiguation for any MPN. Explicit manufacturer is required when multiple brands are known or observed; official product URLs are shown when registered. Mismatch / unresolved / ambiguous never stamps verified identity and returns no candidates. Concurrent branded DigiKey lookups stay isolated across MPNs.
3. **Compare verdicts** — Parameterized across component classes and source types: numeric Different/Match with unknown class where allowed; unknown/missing → Needs verification; catalog agreement → “Catalog values agree — fit unverified.”; Compatible only with authoritative non-catalog evidence.
4. **Supply Risk scope** — Explicit `analysis_id` scopes and labels that analysis; no id → portfolio-wide label; inherited session/URL scope is labeled; UI offers **Clear analysis scope (portfolio-wide)**.

## Verification

| Check | Result |
|---|---|
| Focused follow-up + parity (`test_post_605_generic_followup`, post-deploy follow-up, threaded mfr, family profiles, two-bom parity) | **67 OK** |
| AF regression suite + new tests | **385 OK** |
| Next migration API / tools / exports / auth pytest | **33 passed** |
| Disposable Postgres migration gates | **14 passed, 1 skipped** |
| Next lint | passed |
| Next build | passed |

Evidence logs: `.evidence_ui/post605_generic/`.

## Remaining

Leave PR open for review — do not merge or deploy from this follow-up.
