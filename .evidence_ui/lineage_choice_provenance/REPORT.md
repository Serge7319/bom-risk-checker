# Lineage choice provenance wording

Base: `388e4de` (main after #611)

## Change

Route-derived identity choices (`lineage_identity_choices`) now state they are **historical brands in the trusted MPN lineage** and require confirmation against an **authorized source**.

`Supplier records list …` wording is reserved for choices built from supplier/observed labels (`note_source="supplier"`).

## Tests

| Suite | Result |
| --- | --- |
| Focused identity + threaded aggregator + Newark + AltFinder regression | **437 OK** |
| `apps/web` lint | OK |
| `apps/web` build | OK |

Leave PR open for review — no merge/deploy from this agent.
