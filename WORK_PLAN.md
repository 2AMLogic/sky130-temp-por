# Work Plan

Current roadmap derived from GitHub label state. The region below is maintained by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#192**: fix(pdk): re-pin open_pdks to f6eeac7 via ciel and refuse a mismatched tree

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#188**: Re-pin the sky130 PDK to open_pdks f6eeac7 (ciel 2.6.1) so testbenches name an installable revision (T1 item 9)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#192**: fix(pdk): re-pin open_pdks to f6eeac7 via ciel and refuse a mismatched tree

## Proposed

Issues carrying `loom:curated`.

- **#97**: Lay out por_output_chain as the next DRC/LVS-verified POR leaf *(curated)*
- **#153**: brownout-top: re-grade NONPHYSICAL brown-out points with a tightened-solver fleet re-run *(curated)*
- **#181**: glitch-top: re-run failed vdd_level request vdd_slew_v1.2_h0.0002_s200000 (45 ERROR points) *(curated)*
- **#188**: Re-pin the sky130 PDK to open_pdks f6eeac7 (ciel 2.6.1) so testbenches name an installable revision (T1 item 9) *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)*
- **#193**: Replace raw xschem call in design/netlist.py with klt netlist (drop hand-rolled PDK lookup, no timeout) *(hermit)*
- **#203**: Consolidate duplicated .end-stripping idiom into sim_common (10 copies) *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 4 |
| Architect / Hermit proposals | 3 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
