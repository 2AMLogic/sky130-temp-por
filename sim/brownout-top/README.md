# sim/brownout-top — as-drawn brown-out campaign (issue #116)

Records what RESETn does when the supply of the **unchanged assembled**
`design/netlist/temp_por_top.spice` (bias_core + temp_core + por_comparator +
por_output_chain, real shared IBIAS node, real RESETn -> temp_core.EN feedback)
dips and recovers, across three independent dip axes (floor, hold, falling slew;
recovery slew as a fourth, one-at-a-time axis) and the PVT grid. Rising-ramp
evidence (`sim/supply-ramp-top/`) cannot establish falling behavior
(`spec/porting-plan.md` §3.4). This is **not a spec claim**: no numeric brown-out
envelope is ratified (DR-003 §8) and no gf180mcu number is used anywhere.
Glitch characterization (POR_RAW- and VDD-referenced) is the sibling child of #106.

PTAT/CTAT are left open (the design has no output buffer), RESETn is unloaded,
nothing is replaced by an ideal bias or sensor, and the retired diagnostic XMN1
edit is not used (committed XMN1 is L=20 W=0.42).

## Files

| File | Role |
|---|---|
| `experiment.json` | the manifest: PVT axes, stimulus construction, the numeric exploratory grid and rationale, expansion policy, grading definitions |
| `testbench/tb_temp_por_brownout.sch` | assembled-DUT testbench; BVDD builds power-up + one dip from `.param`s |
| `brownout_checker.py` | pure-stdlib waveform grader (+ synthetic cases) |
| `run_brownout_campaign.py` | `plan` / `run` / `probe` / `record` / `selftest` |
| `selftest/test_brownout.py` | unit tests (axes independence, counts, accounting, append-only) |
| `selftest/*.wave.json.gz` | committed synthetic fixtures re-graded by the tests/self-test |
| `records/`, `corners/`, `netlist-snapshots/` | append-only evidence |

## Stimulus

```
V(VDD) = min(vf, rup*t) - ex*( clip01((t-t0)*sf/ex) - clip01((t-t0-ex/sf-th)*sr/ex) )
ex = max(vf - vlow, 0)
```

* `vf` = **starting supply** (klt `supply_v`, 2.97/3.30/3.63 V); power-up is a
  100 kV/s ramp from a physical 0 V; `t0` = 10 ms (>2.3x the slowest RESETn release, 4.3 ms, in the #98 as-drawn record).
* `vlow` dip floor (absolute V), `sf` falling slew, `th` hold at the floor,
  `sr` recovery slew — four separate parameters. Fall time is `ex/sf` and
  recovery time is `ex/sr`: durations are **derived** from voltage excursion /
  slew, never a fixed duration, so the swept supply cannot couple into a slew.
* No-dip control: `vlow = 99` (ex = 0). Same windows, no dip.
* Observation: 10 ms after the recovery edge ends. `tmax` = min(10 µs, hold/6,
  shortest edge/12); the checker independently enforces a sample-gap limit
  (min(20 µs, hold/5, shortest edge/10)).

Grid (exploratory, bounded; see `experiment.json` `grid`): floors {2.0, 1.2, 0.4}
V × holds {10 µs, 100 µs, 1 ms} × fall slews {2, 50} kV/s at recovery
10 kV/s (18 requests), + recovery 1 and 100 kV/s at the center point (2), + the
control (1) = **21 requests × 45 PVT points = 945 declared points**. Cost is
binding: a first 3-slew/40 ms grid timed out on the fleet (see
`stimulus.cost_note`). The
expansion policy (add midpoints where a PASS/FAIL boundary appears, 10 kV/s and
100 kV/s slews, then 1 MV/s with finer `tmax`, …) is in the manifest; expansion is always a new record.

## Verdicts

`ERROR` (missing waveform/channel, bad data, convergence/model/backend error) >
`NONPHYSICAL` > `UNRESOLVED` (unviable baseline, truncated, sparse, stimulus
mismatch) > `FAIL` (resolved physical failure, trace kept) > `PASS`.
Points never simulated (unsubmitted, refused, no report) are `NOT_COVERED` and
are never counted as covered. A completed simulation is not a PASS. Codes and
definitions: `brownout_checker.py` docstring and `experiment.json` `grading`.

**Delivered bias** is measured explicitly: `+id` of bias_core `XMPIB`
(PMOS whose drain is the IBIAS node; BSIM4 `[id]` is positive for normal conduction,
KCL-checked against the consumer diode devices). The IBIAS **node voltage** is recorded
separately and never used as a current.

## Cold start

```bash
# toolchain (see sim/README.md): pinned PDK via volare, ngspice, xschem, klt
python3 sim/bin/corner-run.py --print-env

# 0. checks that need no simulator
python3 sim/brownout-top/selftest/test_brownout.py
python3 sim/brownout-top/brownout_checker.py
python3 sim/brownout-top/run_brownout_campaign.py plan

# 1. (optional) ONE local single-corner probe: netlist / channel-name validation only
python3 sim/brownout-top/run_brownout_campaign.py probe --tag cube_v1.2_h0.0001_f2000_r10000 --tstop 3e-3

# 2. commit + push the source first (run refuses a dirty or unpushed tree), then submit the grid
KLT_SIM_BACKEND=batch python3 sim/brownout-top/run_brownout_campaign.py run --run-id <id>
#    capacity refusals: re-run only the missing requests (earlier attempts are archived)
python3 sim/brownout-top/run_brownout_campaign.py run --run-id <id> --retry-failed --capacity-wait 600

# 3. grade + write the append-only record (refuses to overwrite)
python3 sim/brownout-top/run_brownout_campaign.py record --run-id <id>
python3 sim/brownout-top/run_brownout_campaign.py selftest
```

The grid goes to the Spot fleet as `klt sim` requests; never hand-launch
`ngspice -b` loops. If a submit fails, the failure is recorded and the affected
points stay `NOT_COVERED`; there is no local fallback. Raw outputs live in the
git-ignored `sim/build/brownout-top/<run-id>/`; the committed evidence is the
record (`records/<id>.md` + `.json`), per-point logs with the exact input deck
(`corners/<id>/<request>/*.log`), change-triggered traces (`*.trace.csv.gz`),
the fleet reports and the request/netlist pairs (`netlist-snapshots/<id>/`).

Spec/design are never edited to improve results; a failing cell is evidence.
