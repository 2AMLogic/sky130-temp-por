# Roadmap

sky130-temp-por is a temperature sensor + power-on-reset block on sky130, ported
from [gf180-temp-por](https://github.com/2AMLogic/gf180-temp-por) and built with
[klayout-tools](https://github.com/2AMLogic/klayout-tools) (`klt`), xschem and ngspice.

Status as of 2026-11-15, `main` @ `98a0d49c`. This page is hand-written and
re-anchored only when a roadmap pass runs — no cadence is promised between
passes, so it is expected to lag the tracker in between; the live queue is
[`WORK_PLAN.md`](../WORK_PLAN.md) (generated from labels), and the
verdict of record for the T1 checklist is
[`manifests/signoff-report.json`](../manifests/signoff-report.json), not this page.

## Where it stands

The signoff report grades `layout/temp_por_top/` at **7 of 11 T1 items met**.

| Item | Status | Evidence or gap |
|---|---|---|
| 1 Design sources | met | `design/` (four leaf cells and `temp_por_top`), attested in `manifests/attestations/` |
| 2 Layout | met | `layout/temp_por_top/temp_por_top.gds` (#240) |
| 3 DRC clean | met | `layout/temp_por_top/drc.json` |
| 4 LVS clean | met, with an exclusion | `layout/temp_por_top/lvs.json`: 152/152 devices with native-Vt `XMASSIST` excluded (#97) — pending re-render of `temp_por_top`, not a tool limit (the leaf draws it at klt `0.9.2`, PR #419) |
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
- **Recent work (PRs #294 to #383).** The sim runners were consolidated onto
  shared `sim/bin/sim_common.py` helpers: one fleet-PDK reader whose stamp is
  checked against the `sim/pdk.json` pin in every record (#332, #343), the
  remaining runners routed through the shared evidence store (#336, #372), one
  append-only-trailer renderer for every record (#366), and the dead boolean
  scaffolding left over from that consolidation removed (#373). The last two
  local ngspice grid launchers now submit through `klt sim` (#330). Records
  derive their PDK and tool versions from the run instead of hardcoding them
  (#300, #313, #315), and attested files are re-hashed in CI (#301, #305). The
  docs caught up too: `spec/README.md` now indexes all seven decision records
  with a per-DR status table (#375), and the characterization report cites the
  mirror-degeneration record and no longer describes #86 as open (#370).

## Now (can start today; one pull request each)

| What | Done when | Issue |
|---|---|---|
| Count the node-violation phases the glitch checker actually emits in the `NONPHYSICAL breakdown` line | a selftest case that fails on `main` passes, for both glitch classes; existing records untouched | #291 (ready; its labels are inconsistent, see below) |
| Mismatch Monte Carlo on the `por_comparator` thresholds | a new record under `sim/por-comparator-thresholds/records/` reports VPOR up, VPOR down and hysteresis spread per corner | #348 (in flight, `loom:building`) |
| Cell-level testbench and record for `por_output_chain` | `sim/<new experiment>/` with `experiment.json`, a testbench and one full-grid record, cited in the report | #349 (in flight, `loom:building`; PR #374 open) |

## Next

Unblocked by a named item above or by a ruling listed under "Blocked and waiting".

- **Live check of one store-routed record** (#335, curated): PR #336 has
  merged, so what remains is one real record from a store-routed runner, per
  #325's acceptance step 6.
- **Re-qualify cited evidence under the current PDK pin** (#189): every record
  the characterization report cites was taken under the earlier open_pdks pin.
  Done when each cited experiment has a superseding record under `f6eeac7` and
  moved results are listed. Needs the `corner-run.py` batch path to accept the
  four experiments it refuses today (#327), and the netlisting failure recorded
  on #189 (2026-11-04) re-checked.
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
- **Full-block LVS.** The question is answered — klt draws and compares the
  native-Vt NMOS at the klt `0.9.2` pin (#97, closed) — so the path to an
  item-4 match with no exclusion is the `temp_por_top` re-render.
- **Remaining ladder rungs** from the README: post-layout re-verification,
  shuttle seat, measured silicon (`measurements/` is empty by design).

## Blocked and waiting

- **#137, ratification of DR-004 and DR-005**: waits on the two independent keys
  (triage note of 2026-10-15). DR-006 and DR-007 have no ratification issue.
  This gates items 5 and 6.
- **#97 follow-on, `temp_por_top` re-render with `XMASSIST`**: #97 itself is
  closed completed — no longer tool-blocked
  ([klayout-tools#2912](https://github.com/2AMLogic/klayout-tools/issues/2912)
  closed; the leaf draws and compares the device at the klt `0.9.2` pin,
  PR #419, merged). What remains: the `temp_por_top` re-render that retires
  the block-level LVS exclusion, and the flavour-blind compare limit —
  drawing the 5V devices' own `hvi` marker is blocked by
  [klayout-tools#6025](https://github.com/2AMLogic/klayout-tools/issues/6025).
- **#153, tightened-solver brown-out re-run**: four pilots hit the 3600 s job
  limit; waits on a choice among the three options in the issue body.
- **#327, `corner-run.py` batch path**: waits on a ruling on whether to also
  remove the local grid default set by #219. Its "fix the batch path only"
  option is what #189 needs.
- **#321**: the only cleanup proposal still awaiting a decision (#308 declined, closed not planned 2026-11-18, see "Not planned"; #314 closed completed 2026-11-18). **#303**: PR #305 merged; the issue stays open until someone runs the
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
- Replacing `layout/bin/attest-layout.py` with `klt signoff --attest 2` (#308,
  closed not planned, 2026-11-18). Revisit only if klayout-tools gains
  recipe-file binding or caller-summary carrying. The recipe-file request,
  klayout-tools#6744, was itself declined (closed not planned, 2026-11-18); the
  caller-summary request, klayout-tools#5573, is still open.
