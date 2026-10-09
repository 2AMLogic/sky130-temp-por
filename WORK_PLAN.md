# Work Plan

Current roadmap derived from GitHub label state. The region below is maintained by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

_None._

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#101**: por_output_chain: XMN1 (L=25) has no valid model bin in the pinned PDK, so as-drawn temp_por_top cannot be simulated
- **#107**: Block-assembly Iq characterization: por-iq, temp-iq, iq-total (DR-003 TBD-4/5/6)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#97**: Lay out por_output_chain as the next DRC/LVS-verified POR leaf *(curated)*

## Proposed (Architect / Hermit)

- **#105**: Full-signal-path mismatch Monte Carlo for temp_core accuracy (DR-003 TBD-1, T1 item 6) *(architect)*
- **#106**: Brown-out and glitch-immunity matrix for assembled temp_por_top (porting-plan §3.4/§3.5) *(architect)*
- **#107**: Block-assembly Iq characterization: por-iq, temp-iq, iq-total (DR-003 TBD-4/5/6) *(architect)*
- **#110**: Remove unused LVS dependency-variant support from compose-cell.py *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 1 |
| Architect / Hermit proposals | 4 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
