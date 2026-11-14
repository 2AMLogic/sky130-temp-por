# Work Plan

Current roadmap derived from GitHub label state. The region below is maintained by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#333**: Compare the recorded fleet-runner PDK stamp with the sim/pdk.json pin (today it is recorded, never checked)

## Important

`loom:important`; taken before unlabelled work.

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)
- **#333**: Compare the recorded fleet-runner PDK stamp with the sim/pdk.json pin (today it is recorded, never checked)

## In Progress

Issues currently being built (`loom:building`).

- **#325**: Route the six remaining sim runners through evidence_store: they still commit raw corner bytes in-tree (1 MB added since adoption)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(curated)*
- **#97**: Lay out por_output_chain as the next DRC/LVS-verified POR leaf *(curated)*
- **#153**: brownout-top: re-grade NONPHYSICAL brown-out points with a tightened-solver fleet re-run *(curated)*
- **#189**: Re-qualify cited sky130 evidence under open_pdks f6eeac7 (split from #188) *(curated)*
- **#303**: Gate items 1 and 9 with klt's own local_only attestation check instead of the repo's re-hasher *(curated)*
- **#333**: Compare the recorded fleet-runner PDK stamp with the sim/pdk.json pin (today it is recorded, never checked) *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)*
- **#308**: Replace layout/bin/attest-layout.py with klt signoff --attest 2 (native since klt 0.9.0; needs the CI pin bumped from 0.8.0) *(hermit)*
- **#314**: Remove the caller-side fleet concurrency-cap retry (cap_retry): klt has waited this refusal out itself since 0.8.0 *(hermit)*
- **#321**: Remove undeclared descriptor keys from compose-cell.py (lvs.params, lvs.drop_kwargs, blocks[].from_stage): no committed cell recipe uses them *(hermit)*
- **#327**: corner-run.py: finish the batch path (it refuses 4 of 5 experiments) and retire the local ngspice grid loop *(hermit)*
- **#334**: Remove dead boolean scaffolding in the brownout/glitch synth stand-ins (`and False` guard, no-op `pass` branch, subsumed disjunct) *(hermit)*
- **#337**: Consolidate the duplicated record-markdown trailer into sim_common (10 renderers, 4 drifted footer texts) *(hermit)*
- **#338**: Route the last two PDK pin-mismatch messages through cr.pdk_mismatch_message (#292 residue, already drifted to pdk.variant) *(hermit)*
- **#339**: Consolidate the fleet capacity-wait flag: one field, eleven CLI declarations, two names, nine defaulting it off *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 1 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 6 |
| Architect / Hermit proposals | 9 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
