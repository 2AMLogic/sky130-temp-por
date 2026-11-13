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

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)

## In Progress

Issues currently being built (`loom:building`).

- **#307**: Share the campaign cmd_run bootstrap in sim_common (9 copies; 3 runners submit from a dirty tree, 1 bypasses submit_prepared)
- **#312**: run_accuracy_mc.py writes a hardcoded open_pdks commit and a '?' ngspice fallback into its record header
- **#318**: accuracy-MC `none` control: a process section with no report is absent from the corner count and cannot make the control NOT VERIFIED

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#315**: fix(sim): derive accuracy-MC record PDK and fleet engine from the run

## Proposed

Issues carrying `loom:curated`.

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(curated)*
- **#97**: Lay out por_output_chain as the next DRC/LVS-verified POR leaf *(curated)*
- **#153**: brownout-top: re-grade NONPHYSICAL brown-out points with a tightened-solver fleet re-run *(curated)*
- **#189**: Re-qualify cited sky130 evidence under open_pdks f6eeac7 (split from #188) *(curated)*
- **#303**: Gate items 1 and 9 with klt's own local_only attestation check instead of the repo's re-hasher *(curated)*
- **#312**: run_accuracy_mc.py writes a hardcoded open_pdks commit and a '?' ngspice fallback into its record header *(curated)*
- **#318**: accuracy-MC `none` control: a process section with no report is absent from the corner count and cannot make the control NOT VERIFIED *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)*
- **#308**: Replace layout/bin/attest-layout.py with klt signoff --attest 2 (native since klt 0.9.0; needs the CI pin bumped from 0.8.0) *(hermit)*
- **#314**: Remove the caller-side fleet concurrency-cap retry (cap_retry): klt has waited this refusal out itself since 0.8.0 *(hermit)*
- **#319**: Remove the local ngspice grid launchers from run_op_branch.py and run_pnp_mismatch.py: submit through klt sim like the other runners *(hermit)*
- **#321**: Remove undeclared descriptor keys from compose-cell.py (lvs.params, lvs.drop_kwargs, blocks[].from_stage): no committed cell recipe uses them *(hermit)*
- **#322**: Share the per-request report triage in sim_common (6 hand copies; 2 drop client_klt_version, 3 wordings for one failure) *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 7 |
| Architect / Hermit proposals | 6 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
