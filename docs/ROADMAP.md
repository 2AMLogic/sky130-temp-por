# Roadmap

sky130-temp-por is a temperature sensor + power-on-reset block on sky130, ported
from [gf180-temp-por](https://github.com/2AMLogic/gf180-temp-por) and built with
[klayout-tools](https://github.com/2AMLogic/klayout-tools) (`klt`), xschem and ngspice.

Status as of 2026-11-13, `main` @ `5870ad5c`.

The live queue is [`WORK_PLAN.md`](../WORK_PLAN.md) (generated from labels); the
verdict of record for the T1 checklist is
[`manifests/signoff-report.json`](../manifests/signoff-report.json), not this page.

## Where it stands

The signoff report grades `layout/temp_por_top/` at **7 of 11 T1 items met**.

| Item | Status | Evidence or gap |
|---|---|---|
| 1 Design sources | met | `design/` (four leaf cells and `temp_por_top`), attested in `manifests/attestations/` |
| 2 Layout | met | `layout/temp_por_top/temp_por_top.gds` (#240) |
| 3 DRC clean | met | `layout/temp_por_top/drc.json` |
| 4 LVS clean | met, with an exclusion | `layout/temp_por_top/lvs.json`: 152/152 devices with native-Vt `XMASSIST` excluded (#97) |
| 5 Corner verification vs a ratified spec | unmet | only two of eight spec rows are ratified (DR-003) |
| 6 Monte Carlo for statistical claims | unmet | MC records exist under `sim/` as harness records, not as envelopes the report accepts, and back no ratified row |
| 7 Post-layout verification | unmet | `klt pex` artifacts exist for `por_comparator` only (`layout/por_comparator/pex/`, #124) |
| 8 Characterization report | unmet | `docs/characterization-report.md` exists but records FAILs and gaps, so it is not a passing check |
| 9 Testbenches shipped | met | `manifests/attestations/`, item 9 |
| 10 Repo hygiene | met | `manifests/attestations/`, item 10 |
| 11 Power delivery (structural) | met | `layout/temp_por_top/erc.json` against the block supply spec (#260) |

- **Spec.** DR-003 is ratified for the operating-temperature and supply rows.
  DR-001, DR-002 and DR-004 to DR-007 are `proposed`; six target rows are still
  `[TBD]` and no `spec/target-spec.md` exists.
- **Simulation.** Fourteen experiment directories under `sim/`, summarised with
  their FAILs in `docs/characterization-report.md`. The open evidence gaps are
  listed in that report's section 6: non-physical solver branches in the
  whole-block Iq, brown-out and glitch campaigns; no mismatch Monte Carlo on the
  POR thresholds; no cell-level record for `por_output_chain`.
- **Recent work (PRs #294 to #330).** The sim runners were consolidated onto
  shared `sim/bin/sim_common.py` helpers and the last two local ngspice grid
  launchers now submit through `klt sim` (#330). Records derive their PDK and
  tool versions from the run instead of hardcoding them (#300, #313, #315), and
  attested files are re-hashed in CI (#301, #305).

## Now (can start today; one pull request each)

| What | Done when | Issue |
|---|---|---|
| Count the node-violation phases the glitch checker actually emits in the `NONPHYSICAL breakdown` line | a selftest case that fails on `main` passes, for both glitch classes; existing records untouched | #291 (ready; its labels are inconsistent, see below) |
| Land the evidence-store routing of the six remaining sim runners | PR #336 merged; no new raw corner bytes under `sim/*/corners/` | #325 |
| Land the single fleet-PDK reader in `sim_common` | PR #332 merged; no private copies left in the runners | #328 |
| Compare the recorded runner PDK stamp with the `sim/pdk.json` pin | a record whose stamp differs from the pin is flagged by a test | #333 (awaiting curation) |
| Remove dead boolean scaffolding in the brown-out and glitch synth stand-ins | the selftests pass with the dead branches gone | #334 (proposal) |
| Index DR-004, DR-005 and DR-007 in `spec/README.md` | every file in `spec/decision-records/` is listed with its status | no issue yet |
| Bring `docs/characterization-report.md` up to date: cite the mirror-degeneration record `sim/temp-core-accuracy-mc/records/20261107-235128-679442ca` and stop describing #86 as open | the record has an evidence entry; the coverage check still passes | no issue yet |
| Mismatch Monte Carlo on the `por_comparator` thresholds | a new record under `sim/por-comparator-thresholds/records/` reports VPOR up, VPOR down and hysteresis spread per corner | no issue yet |
| Cell-level testbench and record for `por_output_chain` | `sim/<new experiment>/` with `experiment.json`, a testbench and one full-grid record, cited in the report | no issue yet |

## Next

Unblocked by a named item above or by a ruling listed under "Blocked and waiting".

- **Live check of one store-routed record** (#335): after PR #336 merges, one real
  record from a store-routed runner, per #325's acceptance step 6.
- **Re-qualify cited evidence under the current PDK pin** (#189): every record
  the characterization report cites was taken under the earlier open_pdks pin.
  Done when each cited experiment has a superseding record under `f6eeac7` and
  moved results are listed. Needs the `corner-run.py` batch path to accept the
  four experiments it refuses today (#327), and the netlisting failure recorded
  on #189 (2026-11-04) re-checked.
- **Replace `layout/bin/attest-layout.py` with `klt signoff --attest 2`** (#308):
  after the CI pin moves from klt 0.8.0 to 0.9.0.
- **Ratification pull requests for DR-004 and DR-005** (#137): one per DR,
  flipping status and the README rows it covers. They can be prepared; they
  merge only when both keys are recorded.
- **Items 5 and 6**: once more rows are ratified, cite `klt sim` envelopes for
  those rows in `manifests/sky130-temp-por.json` and re-render the report.

## Later (direction, with the question to answer first)

- **Temperature accuracy (`[TBD-1]`).** DR-007 recommends chopping the
  `temp_core` amplifier and degenerating the mirror legs. *Does the measured
  mirror-term ratio (record `20261107-235128-679442ca`, #284) support DR-007's
  projection, and is the design change ratified?* Then the schematic change and
  a re-run of the accuracy campaign.
- **Iq rows (`[TBD-4..6]`).** DR-006 finds them not recommendable. *What is the
  spec-level por-iq state, and are the 17 non-`ok` iq-total points solver
  artifacts or real states of the design?*
- **Brown-out and glitch envelopes.** *Do the NONPHYSICAL points resolve under a
  tightened solver (#153)?* Only then can an envelope be proposed.
- **Block-level post-layout verification (item 7).** *Can `klt pex` extract
  `temp_por_top` given the pin-order and MOS-flavour limits recorded in
  `layout/por_comparator/pex/README.md`?*
- **Full-block LVS.** *When does klt draw and compare the native-Vt NMOS?* Then
  #97 and an item-4 match with no exclusion.
- **Remaining ladder rungs** from the README: post-layout re-verification,
  shuttle seat, measured silicon (`measurements/` is empty by design).

## Blocked and waiting

- **#137, ratification of DR-004 and DR-005**: waits on the two independent keys
  (triage note of 2026-10-15). DR-006 and DR-007 have no ratification issue.
  This gates items 5 and 6.
- **#97, `por_output_chain` with `XMASSIST`**: waits on
  [klayout-tools#2912](https://github.com/2AMLogic/klayout-tools/issues/2912)
  (native-Vt NMOS generation and LVS), open as read today.
- **#153, tightened-solver brown-out re-run**: four pilots hit the 3600 s job
  limit; waits on a choice among the three options in the issue body.
- **#327, `corner-run.py` batch path**: waits on a ruling on whether to also
  remove the local grid default set by #219. Its "fix the batch path only"
  option is what #189 needs.
- **#308, #314, #321**: cleanup proposals routed for a decision. **#303**: PR #305 merged; the issue stays open until someone runs the
  scratch-commit demonstration with `xschem` absent and posts the result.
- **#291** carries ready, triage and curating labels at once after an
  interrupted curation; it may need a label repair before it is drawn.
- #3 and #89 are standing holds unrelated to the design.

Nothing on the path to the four unmet items is ready to draw except the
evidence-gap work listed under Now; the items themselves wait on ratification.

## Not planned

- Relaxing a spec row or a harness window to make a result pass. A moved
  result becomes an issue; a spec change needs a decision record.
- A plain-NMOS stand-in for `XMASSIST`, or editing the LVS reference to match
  the layout.
- Running SPICE campaigns, layout composition or DRC/LVS in CI
  (`manifests/README.md`, "What CI covers (and does not)").
- Local multi-corner or Monte Carlo grids (those go through `klt sim`), or
  edits to the append-only records under `sim/**/records/`.
