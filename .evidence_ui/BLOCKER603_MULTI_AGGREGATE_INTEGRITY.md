# #603 multi-candidate aggregate integrity

## Gap
Verifying each candidate HMAC was not enough: a client could keep valid
`candidate_snapshots` tokens and still forge `multi_matrix`,
`multi_source_records`, and top-level evidence (`rows`, `source_*`,
`datasheet_identity`).

## Fix
`materialize_snapshot_for_reuse` rebuilds the multi assembly exclusively from
verified pairwise candidate payloads (`rebuild_multi_snapshot_from_candidates`).
Client aggregate / top-level evidence fields are discarded on reuse.
Pairwise reuse copies only HMAC-bound content keys (unsigned `multi_*`
fields are stripped so they cannot be smuggled beside a valid pairwise token).
`/decision-records` persists only the rebuilt/stripped snapshot and derives
`verified_primary_evidence` from that server-trusted payload.

## Regression
`MultiCandidateSnapshotTrustTests.test_forged_multi_candidate_rows_force_recompute`
keeps candidate tokens valid while tampering aggregate matrix + top-level
identity/source/rows. Asserts:

- no forced pairwise recompute when tokens remain valid
- saved `multi_matrix` / `source_*` / `rows` / identity exclude forged values
- `snapshot_aggregate_rebuilt` is true
- `verified_primary_evidence` stays false

## Local verify
```
CADIVOR_ALLOW_EPHEMERAL_FILE_STORE=1 CADIVOR_ANALYSIS_MODE=synthetic-preview \
python3.12 -m unittest \
  tests.test_nov10_prod_smoke_followup.MultiCandidateSnapshotTrustTests \
  tests.test_two_bom_smoke_parity.DesignImpactAndDecisionTests -v
```
Result: OK (6 tests).

Deploy: not requested; do not merge until CI + review pass.
