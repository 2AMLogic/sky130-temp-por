# Work Plan

Current roadmap derived from GitHub label state. The region below is maintained by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#220**: T1 item 1: run the design-source attestation through klt netlist (#193) and commit the passing envelope

## In Progress

Issues currently being built (`loom:building`).

- **#218**: Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)
- **#219**: corner-run.py: add a klt sim --backend batch path so the six local-grid experiments can be re-run on the fleet (unblocks #189)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#221**: feat(sim): route new corner-run evidence through the fleet artifact store
- **#222**: feat(sim): add --backend batch to corner-run for fleet-routed PVT grids

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#97**: Lay out por_output_chain as the next DRC/LVS-verified POR leaf *(curated)*
- **#153**: brownout-top: re-grade NONPHYSICAL brown-out points with a tightened-solver fleet re-run *(curated)*
- **#181**: glitch-top: re-run failed vdd_level request vdd_slew_v1.2_h0.0002_s200000 (45 ERROR points) *(curated)*
- **#189**: Re-qualify cited sky130 evidence under open_pdks f6eeac7 (split from #188) *(curated)*
- **#218**: Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact) *(curated)*
- **#219**: corner-run.py: add a klt sim --backend batch path so the six local-grid experiments can be re-run on the fleet (unblocks #189) *(curated)*
- **#220**: T1 item 1: run the design-source attestation through klt netlist (#193) and commit the passing envelope *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)*
- **#203**: Consolidate duplicated .end-stripping idiom into sim_common (10 copies) *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 2 |
| Approved PRs awaiting merge | 0 |
| Curated | 7 |
| Architect / Hermit proposals | 2 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
