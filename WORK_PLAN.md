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

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)
- **#386**: characterization-report/README: the '18 mV corner envelope' compared against the mismatch sigmas is the ideal-bias span, not real-bias-core's

## In Progress

Issues currently being built (`loom:building`).

- **#401**: por_comparator: 38 of 120 local-mismatch realisations never release POR_RAW, and the count is not the upper tail of the releasing distribution

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#422**: feat(sim): keep the enable/clamp-path MC diagnostics; POR non-release mechanism established — bias_core BIAS_OK never asserts
- **#423**: chore(loom): resync installed Loom to v0.19.1306

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
- **#386**: characterization-report/README: the '18 mV corner envelope' compared against the mismatch sigmas is the ideal-bias span, not real-bias-core's *(curated)*
- **#401**: por_comparator: 38 of 120 local-mismatch realisations never release POR_RAW, and the count is not the upper tail of the releasing distribution *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)*
- **#308**: Replace layout/bin/attest-layout.py with klt signoff --attest 2 (native since klt 0.9.0; needs the CI pin bumped from 0.8.0) *(hermit)*
- **#314**: Remove the caller-side fleet concurrency-cap retry (cap_retry): klt has waited this refusal out itself since 0.8.0 *(hermit)*
- **#321**: Remove undeclared descriptor keys from compose-cell.py (lvs.params, lvs.drop_kwargs, blocks[].from_stage): no committed cell recipe uses them *(hermit)*
- **#327**: corner-run.py: finish the batch path (it refuses 4 of 5 experiments) and retire the local ngspice grid loop *(hermit)*
- **#353**: Collapse the four `supersedes` encodings into one: the display placeholder `(none)` is load-bearing machine state in two runners *(hermit)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 2 |
| Approved PRs awaiting merge | 0 |
| Curated | 7 |
| Architect / Hermit proposals | 6 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
