# Target specification — ratified rows

This file holds the target-specification rows that are **ratified**. It is
hash-pinned by item 10's repo-hygiene inventory
(`manifests/inventories/item-10.json`), so an edit to a ratified value turns the
`signoff` gate red. It exists so that those rows do not live in `README.md`,
which prose-maintenance roles may edit
([DR-008](decision-records/DR-008-relocate-ratified-target-spec-rows.md)).

Both rows were ratified by
[DR-003](decision-records/DR-003-ratify-target-spec-recommendation.md) through
the two-key path (issue #78, operator ruling of 2026-10-02 on issue #31). Their
values and status are carried over unchanged from `README.md`. The supply value
follows [DR-001](decision-records/DR-001-supply-flavor.md), which is itself still
`proposed`; DR-003 is what ratifies the supply row.

Every other target row is an explicit placeholder (`[TBD-n]`) and stays in the
"Target specification" table in [`README.md`](../README.md); no T1 tier is
awarded and no draft number there is a ratified target.

| Parameter | Target | Stretch | Status |
|---|---|---|---|
| Operating temperature | −40…+125 °C | — | ratified (DR-003) |
| Supply | 2.97–3.63 V (3.3 V ±10 %) | — | ratified (DR-003) |
