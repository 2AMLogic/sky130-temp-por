# Work Plan

Current roadmap derived from GitHub label state. The region below is maintained by the Loom Guide role.

<!-- guide:plan-body:start -->
_Generated: 2026-11-21T07:25:20Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)
- **#455**: bias_core OK-detector: BIAS_OK never asserts in 38 of 120 mismatch samples, so reset never releases; find the device and fix the design
- **#458**: Declare the item 5 and item 6 spec-row sets in the manifest and cite klt sim / klt yield envelopes, with unratified rows marked as such

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#291**: glitch-top: NONPHYSICAL breakdown line counts 0 node violations while rows tag them (pre-dip/post-dip not counted)
- **#458**: Declare the item 5 and item 6 spec-row sets in the manifest and cite klt sim / klt yield envelopes, with unratified rows marked as such

## In Progress

Issues currently being built (`loom:building`).

- **#455**: bias_core OK-detector: BIAS_OK never asserts in 38 of 120 mismatch samples, so reset never releases; find the device and fix the design
- **#457**: Scope the supply-ramp cross-check to its variant so the next record cannot inherit it
- **#461**: temp_core: build DR-007 chopped-amplifier + degenerated-mirror sim variant and measure chopper residual offset (part a of #456)
- **#463**: Replace run_solver_sweep.interp with sim_common.interp_at (#170 residue)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#465**: fix: reset the supply-ramp cross-check for each variant
- **#466**: refactor(sim): drop run_solver_sweep's interp() duplicate of sim_common.interp_at

## Proposed

Issues carrying `loom:curated`.

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(curated)* *(held)*
- **#153**: brownout-top: re-grade NONPHYSICAL brown-out points with a tightened-solver fleet re-run *(curated)* *(held)*
- **#189**: Re-qualify cited sky130 evidence under open_pdks f6eeac7 (split from #188) *(curated)* *(held)*
- **#303**: Gate items 1 and 9 with klt's own local_only attestation check instead of the repo's re-hasher *(curated)* *(held)*
- **#376**: Self-check: assert every spec/decision-records/DR-*.md is indexed in spec/README.md with its own status *(curated)* *(held)*
- **#454**: T1 item 7: produce a graded klt pex report (por_comparator re-run and re-render first, then block-level temp_por_top) *(curated)*
- **#455**: bias_core OK-detector: BIAS_OK never asserts in 38 of 120 mismatch samples, so reset never releases; find the device and fix the design *(curated)*
- **#461**: temp_core: build DR-007 chopped-amplifier + degenerated-mirror sim variant and measure chopper residual offset (part a of #456) *(curated)*
- **#470**: Three cell READMEs still call klayout-tools#6025 open (outside #454's AC-6 scope) *(curated)*

## Proposed (Architect / Hermit)

- **#137**: Run the two-key ratification ceremony on DR-004 and DR-005 *(architect)* *(held)*
- **#321**: Remove undeclared descriptor keys from compose-cell.py (lvs.params, lvs.drop_kwargs, blocks[].from_stage): no committed cell recipe uses them *(hermit)* *(held)*
- **#327**: corner-run.py: finish the batch path (it refuses 4 of 5 experiments) and retire the local ngspice grid loop *(hermit)* *(held)*
- **#353**: Collapse the four `supersedes` encodings into one: the display placeholder `(none)` is load-bearing machine state in two runners *(hermit)* *(held)*

## Epics

- **#4**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(held)*

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 3 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 2 |
| In Progress (`loom:building`) | 4 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 9 |
| Architect / Hermit proposals | 4 |
| Active epics | 1 |
<!-- guide:plan-body:end -->
