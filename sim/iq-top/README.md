# sim/iq-top -- assembled temp_por_top Iq (issue #107)

Evidence for DR-003 row 7 `[TBD-4]` por-iq, `[TBD-5]` temp-iq, `[TBD-6]` iq-total,
measured on the assembled, as-drawn `design/netlist/temp_por_top.spice`.
**Evidence only: no numeric ceiling is proposed here**; a follow-on decision
record would use the records. No change to `design/` or `spec/`.

## States

`temp_por_top` has no sensor-enable pin (`temp_core.EN` is driven internally by
`RESETn`), so the states are defined by `RESETn`:

| state | how it is produced | measured |
|---|---|---|
| por-iq | RESETn asserted (low), forced by a 0 V source `VRST` on `RESETn` in the **testbench** (DUT netlist untouched) | directly |
| iq-total | natural released state, temp_core enabled by RESETn | directly, own simulation (never a sum) |
| temp-iq | `iq-total - por-iq` per corner, labelled **incremental** | derived |

`RESETn` is a DUT output that releases on its own above VPOR-rise, so holding it
low at a valid VDD needs a force. `VRST`'s own current is not in the VDD
measurement; the output stage's contention against it (MOP pushing RESETn high)
flows VDD -> MOP -> RESETn -> VRST, **is** inside `-i(BVDD)`, and is reported
separately as `i(VRST)` (por-iq is also given less that contention).

## Measurement

Transient from a physical 0 V start (the branch-selecting method used by
`sim/supply-ramp-top` and `sim/temp-core-startup`), fast ramp then constant VDD
to 30 ms; `I = -i(BVDD)` averaged over the trailing 25-30 ms window. Settling is
**checked, not assumed**: the trailing mean must be within 1 % of the 20-25 ms
window mean, the trailing pk-pk within 2 %, VDD on target, and the intended
state holding; otherwise the point is `unsettled`. Thresholds are exploratory
measurement definitions in `experiment.json`, not spec limits.

Per-point status is one of `ok`, `non-physical-branch` (the issue #19/#22/#86
signature in `design/temp_core.md`), `unsettled`, `nonconverged`. All 45 points
per state appear in every record; statistics are given for `ok` points and for
all points that produced a value (flagged ones included).

Per-sub-cell attribution uses four 0 V ammeters inserted by the driver in series
with each sub-cell's VDD pin in the generated deck (electrically ideal, same deck
for both states). Attribution is never summed into iq-total; the direct vs
attribution-sum discrepancy is reported (it checks the instrumentation, KCL).

## Files

| file | role |
|---|---|
| `experiment.json` | claim, grid, state definitions, measurement/settling/physicality definitions |
| `testbench/tb_temp_por_iq_{por,total}.sch` | the two testbenches |
| `run_iq_campaign.py` | `run` (batch fleet), `crosscheck` (one local corner), `record`, `selftest` |
| `iq_checker.py` | settling/physicality grading + synthetic selftest cases |
| `run_iq_sensitivity.py`, `test_solver_sensitivity.py` | issue #160 iq-total solver-sensitivity replicate (`run`, `record`) and its stdlib unit tests |
| `selftest/` | committed synthetic settled / drifting waveforms |
| `records/`, `corners/`, `netlist-snapshots/` | append-only evidence; a correction is a new record with `Supersedes` |

## Running

```
python3 sim/iq-top/run_iq_campaign.py selftest
python3 sim/iq-top/run_iq_campaign.py run                     # 2 klt sim requests x 45 corners, --backend batch
python3 sim/iq-top/run_iq_campaign.py run --run-id ID --retry-failed --capacity-wait 1800
python3 sim/iq-top/run_iq_campaign.py crosscheck --run-id ID  # single local corner tt/27C/3.30V
python3 sim/iq-top/run_iq_campaign.py record --run-id ID
```

The grid is never run locally. A fleet refusal is recorded verbatim in the
record and the issue stays open.

## Solver-sensitivity replicate (issue #160)

DR-006 requires a solver-sensitivity replicate of the natural-release `iq-total`
state before the 17 non-physical points can support an Iq recommendation.
`run_iq_sensitivity.py` re-runs the **whole** 45-point `iq-total` grid (not only
the 17 exclusions: a solver change can move the failure set) as one fleet
request per variant: `baseline` (the unchanged control deck), `trtol7` and
`reltol2e-4` (the #86/#142 discriminators). Only the testbench `.options` line
differs; the DUT, analysis card, windows, guards and grading code are shared.
The comparison criterion (agreement within 1 %) and the classification of the 17
exclusions are predeclared in `experiment.json` `solver_sensitivity`. If one
45-corner job exceeds the fleet's per-job wall-clock ceiling, `--split-process`
resubmits it as one fleet request per MOS corner; timeouts stay explicit
unknowns and nothing is ever run locally.

```
python3 -I sim/iq-top/test_solver_sensitivity.py
python3 sim/iq-top/run_iq_sensitivity.py run --run-id ID [--capacity-wait 1800]
python3 sim/iq-top/run_iq_sensitivity.py run --run-id ID --retry-failed --variant trtol7 --split-process
python3 sim/iq-top/run_iq_sensitivity.py record --run-id ID
```
