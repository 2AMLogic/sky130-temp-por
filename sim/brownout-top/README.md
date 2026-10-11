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
| `experiment.json` | the manifest: PVT axes, stimulus construction, the numeric exploratory grid and rationale, expansion policy, grading definitions, declared solver variants and the #153 tightened re-run set |
| `testbench/tb_temp_por_brownout.sch` | assembled-DUT testbench; BVDD builds power-up + one dip from `.param`s |
| `brownout_checker.py` | pure-stdlib waveform grader (+ synthetic cases) |
| `run_brownout_campaign.py` | `plan` / `run` / `probe` / `record` / `selftest` / `cost`; `--variant` selects a declared solver variant |
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

## Tightened-solver companion re-run (issue #153)

The default-deck record `20261010-222529-41bde9f` has 673 NONPHYSICAL points
whose brown-out behavior is unknown. #153 re-runs them with a **declared solver
variant**, not a circuit change. The variant and the re-run set were committed in
`experiment.json` before any tightened request was submitted:

* `solver_variants.reltol2e-4` appends `reltol=2e-4` to the testbench's one
  `.options method=gear trtol=50` line. Everything else is byte-identical to the
  default deck: circuit, stimulus `.param`s, `.save` channels, tstop/tmax, the
  corner matrix and `timeout_s`. The deck banner names the variant. The unit
  tests check that the options line is the only non-comment change.
* `tightened_rerun.rerun_tags` lists all 21 requests. Every request holds at least
  one source-NONPHYSICAL point, so whole 45-corner requests cover all 673 targets.
  The 272 source-physical points come along as controls, with request and PVT
  identities unchanged. A tightened run refuses `--only` tags outside this list.
* Physicality bounds and grading are **unchanged**. The bounded junction-clamp-scale
  undershoot stays NONPHYSICAL; a separate class would be its own declared
  decision.
* Changed control verdicts are evidence. Both outcomes are kept, and control
  agreement is not a precondition for publishing.

```bash
# pilot (tightened_rerun.pilot_tags) from a clean pushed commit, then project cost
KLT_SIM_BACKEND=batch python3 sim/brownout-top/run_brownout_campaign.py run --variant reltol2e-4 --run-id <id> \
    --only control --only cube_v1.2_h0.0001_f50000_r10000
python3 sim/brownout-top/run_brownout_campaign.py cost --run-id <id>
# remaining requests into the SAME run (refuses deck drift since the first submit; each batch's commit is recorded)
KLT_SIM_BACKEND=batch python3 sim/brownout-top/run_brownout_campaign.py run --variant reltol2e-4 --run-id <id> --retry-failed [--only <tag> ...]
# grade + companion record; --compare-source defaults to tightened_rerun.source_record
python3 sim/brownout-top/run_brownout_campaign.py record --variant reltol2e-4 --run-id <id>
```

`--retry-failed` submits every selected request that does not yet have a usable
report, including requests that have never been submitted. Earlier attempts are
archived.

The record carries `comparison` in its JSON twin, with one row per declared point.
Each row holds the request tag, PVT id, role (`target` = source NONPHYSICAL,
`control` = source PASS/FAIL) and selected/excluded status. It also holds the
default and tightened verdicts, both physicality flags, both job ids, per-corner
runtimes and fail codes. Per-request rows give job ids, elapsed time, fleet outcome,
earlier attempts and NOT_COVERED/ERROR counts. The markdown twin renders the
transition matrix, the changed controls, the per-request job table and the
per-point table. The comparison refuses a broken join in either direction. A
refused or unsubmitted request stays NOT_COVERED, and an uncovered control is
counted separately rather than as a changed verdict. The pilot cost projections
(`cost-projection-*.json`) are copied into the netlist snapshot and summarized in
the record. The default-deck record is never edited. The new record names it as
**Companion of** and does not supersede it.

The grid goes to the Spot fleet as `klt sim` requests; never hand-launch
`ngspice -b` loops. If a submit fails, the failure is recorded and the affected
points stay `NOT_COVERED`; there is no local fallback. Raw outputs live in the
git-ignored `sim/build/brownout-top/<run-id>/`; the committed evidence is the
record (`records/<id>.md` + `.json`), per-point logs with the exact input deck
(`corners/<id>/<request>/*.log`), change-triggered traces (`*.trace.csv.gz`),
the fleet reports and the request/netlist pairs (`netlist-snapshots/<id>/`).

Spec/design are never edited to improve results; a failing cell is evidence.

## Records

| Record | What it is |
|---|---|
| `records/20261010-130609-db29746-fleet-timeout.md` | First submission (`fleet1`, the 30-request manifest at `db29746`). Two jobs hit the 3600 s timeout with 0/45 usable corners each, and the attempt was abandoned. Not a result. |
| `records/20261010-222529-41bde9f.md` (+ `.json`) | Declared 945-point grid, simulated at `bcf00bf` (21 fleet jobs) and graded at `41bde9f`. Deck inputs are identical between the two commits, and every submitted netlist's sha256 matches its fleet report. **PASS 267, FAIL 5, NONPHYSICAL 673, ERROR 0, UNRESOLVED 0, NOT_COVERED 0.** |
| `records/20261010-222928-0265c45-checker-selftest.md` | Checker self-test: 16/16 synthetic cases give the expected verdict. |
| `records/20261011-214916-183a3fc.md` (+ `.json`) | #153 tightened-solver (`reltol2e-4`) **pilot**, a companion of `20261010-222529-41bde9f`. It is not the re-grade. Two pilot requests (`control`, `cube_v1.2_h0.0001_f50000_r10000`; jobs `klt-sim-c3ba332c37d3`, `klt-sim-fd2409da90fb`) hit the fleet's enforced 3600 s whole-job limit, and klt discarded every corner. Each request was first refused 5 times at the shared fleet's concurrency cap. The cost rule held the other 19 requests back. **ERROR 90, NOT_COVERED 855; no tightened point graded.** The per-point comparison covers all 945 points. |

How to read the graded record:

* **NONPHYSICAL is the majority.** It mostly comes from temp_core-side nodes at impossible voltages and the supply current reversing, the same signature as the as-drawn supply-ramp record. The grid used the default solver tolerances, so those cells are **unknown**, not passing. The 50 kV/s falls to 1.2 V and 0.4 V have **no physical point at all** (270/270 NONPHYSICAL). A tightened-solver fleet re-run is #153.
* **The five FAILs are physical and kept with traces.**
  * Fast 100 kV/s recovery at -40 C (tt 2.97 V, tt 3.30 V, ff 2.97 V): RESETn rides VDD above V_IH for a few microseconds while POR_RAW is still low, then re-asserts.
  * Shallow 2.0 V dip at 50 kV/s, tt/27 C/2.97 V (two holds): the first assertion begins only after VDD has recovered.
* Across the 221 physical points where RESETn asserted, VDD at assertion ranged from 0.36 to 1.00 x the starting supply (median 0.74), and no assertion was rail-limited. Release came a median 2.3 ms after VDD recovered (max 4.0 ms).
* None of this is a ratified bound, and no gf180mcu number is used.

How to read the #153 tightened pilot (`20261011-214916-183a3fc`):

* **It does not change what is known.** The 673 default-deck NONPHYSICAL points are still unknown. No tightened point was graded.
* **Cost is the blocker.** The tightened deck is much slower on the fleet. Both pilot jobs timed out at 3600 s, against 450 s and 1402 s on the default deck, so the ratio is at least x8 on whole-job time. A local single-corner timing probe (the fleet-equivalent SPARSE solver, ff / 125 C / 2.97 V `control`) took 389 s against 19 s on the default deck, about x20. Projected against the 3600 s limit, all 21 requests exceed it.
* The fleet runner ignores `options.ngspice_init`, so every fleet run so far, default and tightened, used ngspice's SPARSE solver rather than the KLU that `sim/spiceinit` selects.
* Continuing needs a declared manifest change first. Options are KLU carried in the netlist, one corner per job, a longer job limit, or a looser tolerance. See the record's Notes.
