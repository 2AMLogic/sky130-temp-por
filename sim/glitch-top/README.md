# sim/glitch-top — glitch immunity of the assembled block, two separate classes (issue #117)

Completes `spec/porting-plan.md` §3.5 next to `sim/brownout-top/` (#116). Two
**structurally different** disturbances are stimulated, graded and recorded
**separately** (separate record files, summaries, tables), because a deglitch
dwell can only filter what is presented at `POR_RAW`; it cannot reject a rail
disturbance, and a VDD result says nothing about the dwell in isolation.

This is **not a spec claim**: no numeric glitch envelope is ratified (DR-003 §8)
and no gf180mcu number is used. Every threshold below is an exploratory
measurement definition (`experiment.json` `grading`).

| Class | Stimulus | Evidence kind |
|---|---|---|
| `por_raw_inject` (A) | clean power-up ramp; a pulse is injected into the `POR_RAW` node through a finite resistor | **INSTRUMENTED** assembly (two spliced instrument lines). Not as-drawn evidence. |
| `vdd_level` (B) | one symmetric-edge VDD dip (`sf = sr`) after the baseline has settled | **UNMODIFIED** assembly; DUT netlist spliced byte-identical |

Both run on the committed `design/netlist/temp_por_top.spice` (bias_core +
temp_core + por_comparator + por_output_chain, real shared IBIAS node, real
RESETn -> temp_core.EN feedback). Nothing is replaced by an ideal bias or sensor,
PTAT/CTAT are open, RESETn is unloaded, committed XMN1 is `L=20 W=0.42`, and the
retired `diag-mn1-l20` edit is not used. The comparator is never disconnected.

## Class A injection (disclosed instrument)

Spliced just before `.ends` of `temp_por_top` (the control keeps both lines with
`gen = 0`, so topology is identical and the element is idle):

```
BINJ INJD VSS V=v(POR_RAW)*(1-v(ginj))
RINJ INJD POR_RAW <rinj>
```

`GINJ` is a global node driven by the testbench trapezoid
`g(t) = gen*(clip01((t-t0)/te) - clip01((t-t0-te-tw)/te))`: rise `te`, **flat
width `tw`**, fall `te` (full base width `tw + 2te`, half-amplitude width
`tw + te`). At `g = 0` the source equals the node voltage, so no idle current
flows. At `g = 1` `POR_RAW` is pulled toward VSS through `RINJ` while the comparator
output stage keeps driving it, so the achieved level is a **divider** of `RINJ`
against the comparator pull-up (measured per point, not assumed). `RINJ`
(1 kohm deep, 30 kohm shallow) is the amplitude axis. No capacitance or charge
is added. If injection prevents a physically meaningful operating point (nonphysical
node, never crossing V_MID, ...) the point is NONPHYSICAL/UNRESOLVED and no as-drawn
immunity is claimed from it. The injection current is saved as
`@r.xdut.rinj[i]` (ngspice sign: positive INJD -> POR_RAW, so pull-down reads negative).

## Class B stimulus

`V(VDD) = min(vf, rup*t) - ex*(clip01((t-t0)*s/ex) - clip01((t-t0-ex/s-th)*s/ex))`,
`ex = max(vf - vlow, 0)`: the brown-out source with equal edges `sf = sr = s`.
Edge duration is derived (`ex/s`), so the swept supply does not couple into a slew.
Control: `vlow = 99`.

## Grid (exploratory, bounded; expansion policy in `experiment.json`)

* Class A: `RINJ` {1k, 30k} x flat width {20 us, 200 us, 2 ms} at 20 us edges (6) +
  edges {10 us, 200 us} at the center (2) + control (1) = 9 requests.
* Class B: floor {2.0, 1.2, 0.4} V x hold {20 us, 200 us} at 50 kV/s (6) + slews
  {20, 200} kV/s at the center (2) + control (1) = 9 requests.
* Each request is 5 process x 3 temperature x 3 starting-supply = 45 PVT points:
  **18 requests, 810 declared points** (405 per class). No subset is declared.
* Baseline: glitch at `t0` = 8 ms; the checker requires exactly one release, RESETn
  and POR_RAW high, and the delivered bias settled over the last 2 ms, else UNRESOLVED.
  Observation: 8 ms after the glitch ends. `tmax = min(10 us, width/8, edge/8)`.

## Grading

`ERROR` (missing waveform/channel, non-finite data, convergence/model/backend error,
deck not attributable to this class/DUT) > `NONPHYSICAL` > `UNRESOLVED` (unviable baseline,
sample gap too coarse for the requested width/edge, drive not as declared, truncated
window, injection never exercised the dwell) > `FAIL` (resolved physical failure) > `PASS`.
`NOT_COVERED` = never submitted/refused/no report; never counted as coverage.
A completed simulation (klt status) is not a PASS.

What each stimulus **calls for** is stated per point: class A from the measured
POR_RAW dwell below V_MID (`< 50 us` rejection, `>= 1 ms` assertion required, else
optional but must release); class B from the VDD dwell below V_MUST. Failure codes
include `unwanted_assertion`, `missed_assertion`, `no_recovery`, `premature_release`
(spurious release), `reassert_chatter`, `reassert_after_recovery`, `not_high_at_end`,
`bias_not_recovered`, `spurious_assertion_control`.

**Delivered bias** is `+id` of bias_core `XMPIB` (PMOS whose drain is the IBIAS
node), saved as `@m.xdut.xbias.xmpib.msky130_fd_pr__pfet_g5v0d10v5[id]`; BSIM4 `[id]`
is positive for normal conduction, so it must be positive at baseline (else
NONPHYSICAL). The IBIAS **node voltage** is recorded separately and never used as a
current.

## Files

| File | Role |
|---|---|
| `experiment.json` | manifest: both classes, PVT axes, stimulus, grids, injection disclosure, grading |
| `testbench/tb_temp_por_glitch.sch` | assembled-DUT testbench (BVDD + BGINJ from `.param`s) |
| `glitch_checker.py` | pure-stdlib grader for both classes + synthetic cases (reuses `brownout_checker` primitives) |
| `run_glitch_campaign.py` | `plan` / `run` / `probe` / `record` / `selftest` |
| `selftest/test_glitch.py`, `selftest/*.wave.json.gz` | unit tests and committed synthetic fixtures |
| `records/`, `corners/`, `netlist-snapshots/` | append-only evidence (one record per class) |

## Cold start

```bash
python3 -I sim/glitch-top/glitch_checker.py            # synthetic verdict cases
python3 -I sim/glitch-top/selftest/test_glitch.py
python3 sim/glitch-top/run_glitch_campaign.py plan
python3 sim/glitch-top/run_glitch_campaign.py probe --tag vdd_control --tstop 9e-3   # ONE local corner, validation only
# commit + push first (run refuses a dirty/unpushed tree), then
KLT_SIM_BACKEND=batch python3 sim/glitch-top/run_glitch_campaign.py run --run-id <id>
python3 sim/glitch-top/run_glitch_campaign.py run --run-id <id> --retry-failed --capacity-wait 600
python3 sim/glitch-top/run_glitch_campaign.py record --run-id <id>    # writes both class records
python3 sim/glitch-top/run_glitch_campaign.py selftest
```

The grid goes to the Spot fleet as `klt sim` requests; never hand-launch `ngspice -b`
loops. A refused/failed submit is recorded and its points stay `NOT_COVERED`; there
is no local fallback. Raw outputs live in git-ignored `sim/build/glitch-top/<run-id>/`.
Spec/design are never edited to improve results; a failing cell is evidence.

## Results (run `20261012-014941-25e2978`, records `20261012-113515-25e2978-*`)

All 18 declared requests / 810 points were submitted to the Spot fleet and graded
(0 `NOT_COVERED`). The two classes are reported in separate records; a simulation
`pass` from `klt` is not a verdict.

| Class | PASS | FAIL | ERROR | NONPHYSICAL | UNRESOLVED |
|---|---|---|---|---|---|
| `por_raw_inject` (instrumented) | 152 | 0 | 0 | 172 | 81 |
| `vdd_level` (unmodified) | 67 | 5 | 45 | 288 | 0 |

* The large NONPHYSICAL counts are the default-deck solver-branch signature already seen in
  `sim/brownout-top/` (e.g. `singular_matrix` at the `temp_core` PNP emitter in a local
  probe). They are retained, not graded for behaviour, and give no immunity claim; the
  tightened-solver re-run is the declared follow-on (see `experiment.json` `not_covered`).
* `vdd_slew_v1.2_h0.0002_s200000` returned a fleet report with status `error`; its 45
  points are `ERROR`. Two other requests (`por_raw_edge_r1000_w0.0002_e1em05`,
  `vdd_cube_v1.2_h0.0002_s50000`) hung client-side until the driver's 4 h cap, were
  recorded as failed submits and were re-submitted once with `--retry-failed` (same run id).
* The 5 class-B FAILs and the class-A UNRESOLVED cells are per-point in the records; no
  numeric envelope is claimed.

