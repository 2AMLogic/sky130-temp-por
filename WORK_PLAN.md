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

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)
- **#458**: Declare the item 5 and item 6 spec-row sets in the manifest and cite klt sim / klt yield envelopes, with unratified rows marked as such

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)
- **#458**: Declare the item 5 and item 6 spec-row sets in the manifest and cite klt sim / klt yield envelopes, with unratified rows marked as such
- **#461**: temp_core: build DR-007 chopped-amplifier + degenerated-mirror sim variant and measure chopper residual offset (part a of #456)

## In Progress

Issues currently being built (`loom:building`).

- **#454**: T1 item 7: diagnose missing RESETn crossings in the temp_por_top post-layout grid

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(curated)*
- **#153**: brownout-top: re-grade NONPHYSICAL brown-out points with a tightened-solver fleet re-run *(curated)*
- **#189**: Re-qualify cited sky130 evidence under open_pdks f6eeac7 (split from #188) *(curated)*
- **#303**: Gate items 1 and 9 with klt's own local_only attestation check instead of the repo's re-hasher *(curated)*
- **#376**: Self-check: assert every spec/decision-records/DR-*.md is indexed in spec/README.md with its own status *(curated)*
- **#454**: T1 item 7: diagnose missing RESETn crossings in the temp_por_top post-layout grid *(curated)*
- **#461**: temp_core: build DR-007 chopped-amplifier + degenerated-mirror sim variant and measure chopper residual offset (part a of #456) *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)*
- **#499**: Remove the installed klt and broker prerequisites from the deck-transport tripwire test *(hermit)*
- **#504**: Simplify design/netlist.py normalize(): use klt netlist --relative-paths/--no-provenance-header *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 3 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 7 |
| Architect / Hermit proposals | 3 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
