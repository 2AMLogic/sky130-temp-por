# Branch attribution at tt/3.300V/-40C and sf/2.970V/-40C -- issue #454 (2026-11-26)

**New appended evidence.** Nothing in `../diagnosis-454/`, `../grid/`, the
pilot or any earlier record is edited. This directory answers the
"Remaining work after #519" increment of issue #454: controlled single-point
runs at `tt/3.300V/-40C` (which change, if any, moves PTAT back within the
supply rails and whether RESETn crosses 2.64 V in the original 30 ms), and
the schematic-side result at `sf/2.970V/-40C`. All runs are local, one
`ngspice -b` each, sequential, single corner (no grid, per the host and repo
rules; the fleet grid stays the graded authority). Item 7 stays `unmet`.

| where | what |
|---|---|
| `inputs/` | the decks exactly as run (paths written `<repo>` / `~`, like `../diagnosis-454/inputs/`; substitute a checkout root and a PDK root to rerun), the testbench copy, the three derived netlists, and `derive-variants.sh` regenerating them from the pinned grid inputs |
| `runs/` | the ngspice-47 run logs (`.txt` because the repo `.gitignore` excludes `*.log` outside `sim/*/corners/`) |

Every deck adds `set ng_nomodcheck` and extra `.meas` probes relative to the
grid's `corner.cir`; the `tran 1u 0.03 0 1e-05` window and the 2.64 V
`RISE=1` crossing are the original, except where the run's name says
`long` (300 ms), `5ms` or `reltol`.

## Runs at tt/3.300V/-40C (extracted leg unless stated)

| run | one change vs base | PTAT max / 30 ms value | RESETn | crossing |
|---|---|---|---|---|
| `tt-n40-base` | none (reproduction of `../diagnosis-454`) | 14.96 V @ 1.208 ms / **12.789 V** | max 52.7 mV @ 10.2 us; -6.9 mV @ 30 ms | none |
| `tt-n40-trace` | time probes only | 14.96 V @ 1.208 ms / 12.79 V | -3.2 mV @ 2 ms ... -7.6 mV @ 29 ms | none |
| `tt-n40-nodeset` | `.nodeset v(xdut.ptat)=0.283` | identical to base, every printed digit | identical | none |
| `tt-n40-long` | window 300 ms | 16.05 V @ 55.3 ms / 12.79 V @ 30 ms, 3.291 V @ 100-200 ms | 3.040 V from ~55.3 ms | **55.30 ms** (on the garbage trajectory) |
| `tt-n40-reltol-1e-3-5ms` | window 5 ms (control) | 14.96 V @ 1.208 ms / 12.81 V @ 4 ms | -13.1 mV @ 5 ms | none |
| `tt-n40-reltol-1e-4-5ms` | + `reltol=1e-4` | **2.907 V** @ 1.216 ms / -11.9 mV @ 2 ms | 3.041 V @ 1.23 ms, -12.4 mV @ 5 ms | **1.2139 ms** |
| `tt-n40-reltol-1e-5-5ms` | + `reltol=1e-5` | **3.058 V** @ 1.219 ms / 1.380 V @ 4 ms | 3.041 V @ 1.22 ms, 3.041 V @ 5 ms | **1.2161 ms** |
| `tt-n40-reltol-1e-4-30ms` | `reltol=1e-4`, original 30 ms window (~46 min wall) | -47 uV @ 30 ms (in rails) | crossing at 1.2139 ms, but the tail cycles (max 3.055 V @ 16.2 ms, ~0 V at 10/20/30 ms) | **1.2139 ms** |
| `tt-n40-nocc` | 131 `Ccc_*` coupling caps removed | 1.57 mV @ 80 us / **0.40 mV** | max 52.7 mV @ 10.2 us, 1.07 mV @ 30 ms | none |
| `tt-n40-nocc-long` | + window 300 ms | 0.40 mV decaying to 0.39 mV @ 290 ms | ~1.04-1.07 mV throughout | none |
| `tt-n40-nor` | 569 star resistors shorted (1 u-ohm) | transient op solves (after gmin/source-stepping failures); run crawls, killed at 300 s | -- | not completable |

Schematic leg, same point:

| run | netlist / change | PTAT | RESETn | crossing |
|---|---|---|---|---|
| `sch-tt` | grid schematic (`g5v0d10v5` MOS) | ~1e-8 V until ~2.7 ms (dead), then 0.2830 V; max 1.616 V @ 2.759 ms | 2.9698 V | **2.7574 ms** |
| `sch-tt-reltol-1e-4(-partial)` | + `reltol=1e-4` | crawl: 12.6 ms of the 30 ms in 240 s | | not completable |
| `sch-tt-reltol-1e-5(-partial)` | + `reltol=1e-5` | crawl: 6.1 ms of the 30 ms in 240 s | | not completable |
| `sch-tt-01v8swap` | schematic with the extractor's model swap (`g5v0d10v5` -> `01v8`, 114 MOS, no parasitics) | 0.2683 V; max 3.678 V @ 0.21 ms (brief, recovers) | 3.1089 V | **1.1817 ms** |

## What the tt/3.300V/-40C runs establish (AC 1)

1. **The 12.79 V PTAT state is a numerical solution branch, not a physical
   extraction result.** A passive RC extraction cannot hold a node at 3.9x
   the 3.30 V rail (the only drivers of PTAT are pfet drains, a nfet drain to
   VSS and megohm trim resistors); the `1.47691e+236 ^ 2 out of range` error
   in `b.xdut.x$153.brbody` (base log, the PDK `res_xhigh_po` nonlinear body
   resistor evaluating that voltage) is the symptom. Tightening `reltol`
   1e-3 -> 1e-4 pulls PTAT back within the rails (max 2.91 V vs 14.96 V) and
   produces the 2.64 V crossing at 1.2139 ms -- **inside the original 30 ms
   window** (`tt-n40-reltol-1e-4-30ms`), at 0.44x the schematic's 2.757 ms.
2. **The branch is selected during the transient, not at the DC operating
   point**: `.nodeset v(xdut.ptat)=0.283` changes nothing (bit-identical
   output), and the trace shows PTAT at -3.44 V at 1 ms before snapping to
   +12.83 V at 2 ms (peak 14.96 V at 1.208 ms).
3. **The entry path is the aF-scale coupling capacitors**: with the 131
   `Ccc_*` cards removed, no excursion occurs at all (PTAT ~0.4 mV) -- but the
   block then sits on its zero-current branch and never starts in 300 ms,
   while the same transient on the grid schematic starts at 2.76 ms. The
   coupling values (7.7e-18 F .. 1.2e-17 F) are 4-5 orders below the
   net-to-vsubs caps (fF) and cannot matter physically; they matter only as
   the numerical path off the dead branch.
4. **A longer window does not rescue the row and its "release" is not
   physical**: at 300 ms the default-tolerance run crosses at 55.30 ms only
   after PTAT peaks at 16.05 V, and RESETn thereafter sits high while PTAT
   rests at 3.29 V -- a garbage trajectory, not a slow timer.
5. **The systematic early release of the extracted leg is the #467 model
   mismatch, not the parasitics.** The grid schematic with nothing but the
   extractor's model substitution (`01v8` for 114 `g5v0d10v5` MOS) releases
   at **1.1817 ms** -- matching the tight-tolerance extracted run (1.2139 ms)
   and the fleet's early-release band (20 passing corners at 0.32-0.88x the
   schematic; 4 late at 6.2-10.0x). The `nor` variant (star-R short) shows
   the series resistors are not freely removable (the netlist becomes
   unsolvable-slow), so the R-card bisection stops there.
6. **Tolerance tightening is not a fleet remedy**: at `reltol<=1e-4` BOTH
   legs crawl (~50-100x slower; the 30 ms extracted run needs ~46 min, the
   schematic run does not finish in 240 s), against the ramp request's
   `timeout_s: 3000`. The grid's default-tolerance configuration is the only
   viable one; within it the extracted leg is exposed to the non-physical
   branch at the 12 group-A corners.

## What the sf/2.970V/-40C runs establish (AC 2)

- **Schematic leg (the grid's failing side): the POR releases and the
  measurement threshold, not the circuit, misses.** RESETn rises at ~1.80 ms
  and stays high at **2.6383 V** through 300 ms (logic high is ~VDD-0.33 V at
  both rails; `resetnmax = 2.63833 V`). That is **1.7 mV below the pinned
  2.64 V crossing** (`0.8 x 3.30 V`), while the repo's own release definition
  is `V_IH = 0.8 x vf` = 2.376 V at this rail
  (`sim/supply-ramp-top/experiment.json`), which RESETn crosses at ~1.80 ms.
  PTAT (1.098 V) and CTAT (0.780 V) are normal. The row errors as "no 2.64 V
  crossing" although the block released; filed as **#521** (spec decision,
  out of #454's scope). 4 of the 12 group-A corners are 2.970 V corners where
  both legs' RESETn-high is threshold-critical.
- **Extracted leg at the same corner: the non-physical branch, opposite
  polarity.** PTAT parks at **-3.44 V** (below ground) with RESETn low
  (max 42.5 mV at 10.2 us); removing the coupling caps collapses it to the
  dead branch (0.39 mV, no start). The `01v8`-swapped schematic at this
  corner releases at 1.047 ms (RESETn-high 2.789 V, crosses 2.64 V) while its
  own PTAT rides a 4.557 V excursion -- so the non-physical PTAT branch is a
  property of the `01v8` leg + default tolerance, appearing with or without
  parasitics, in either polarity, at both tested corners.

## Attribution of the 24 group-A rows (supersedes "design vs solver unresolved")

- **22 extracted-side rows (12 corners, 11 real misses + `sf/2.970V/-40C`
  both-sides)**: a tolerance-selected non-physical ngspice branch on the
  `01v8` extracted leg, entering through the aF coupling caps -- a **solver
  cause**, amplified by the extraction, on top of the model-mismatch-driven
  early release. Not a physical release beyond the window, not a slow timer.
- **2 schematic-side rows (`sf/2.970V/-40C`)**: the fixed 2.64 V threshold vs
  the 2.638 V logic-high on the 2.970 V rail (**#521**), a harness
  definition artifact, not a circuit failure.
- The evidence runs out at: only `tt/3.300V/-40C` and `sf/2.970V/-40C` were
  re-run locally (single-point, per the issue); the other 10 group-A corners'
  branch states are inferred, not measured. Group B (27 `ss` abort rows) is
  untouched by this increment (the issue keeps it separate from #153); no
  common cause with group A is claimed. Whether a `g5v0d10v5`-extracted
  netlist (post-#467 re-render) still shows the branch is untested.

## klt gaps

No new klt defect is demonstrated by these runs. The two filed from the
#519 increment stand unchanged: klayout-tools#7904 (mis-sorted
`delta[].error.code`) and klayout-tools#7905 (non-retained `.include` path
in batch `corner.cir`). The fixed 2.64 V `.meas` threshold is this repo's
own request spec (#521), not a klt behavior. Separately filed while
recording this: 2AMLogic/loom#15412 (a Loom bash config-resolver argv limit
that killed a #454 builder step on 2026-11-20; unrelated to the circuit).

## Disclosure for the cited reports

The cited reports are unchanged from the #519 increment
(`../klt-pex.report.json` pilot, `pass`; `../grid/klt-pex.report.json`,
`error`, 84/135):

- **`body_bias.status`: `biased`** (0 unbiased devices, 0 unbiased nets, 0
  unbiased PMOS body nets).
- **`extraction.model`**: net-to-ground area/perimeter capacitance plus
  vertical-overlap net-to-net coupling; lateral coupling only for declared
  `--critical-net` pairs; a single lumped series resistance per net,
  star-distributed across its device terminals; fringe shielding not
  modelled.
- **`model_mismatch`** (114 MOS: `nfet/pfet_g5v0d10v5` in the reference vs
  `nfet/pfet_01v8` in the extracted) is unchanged -- #467 (open, blocked on
  the klt pin bump). This record shows that mismatch also dominates the
  release-time delta of every passing ramp row, not just the comparator
  accuracy it was filed for.

Neither report is cited as item 7 in the manifest: the pilot is a single
point and the grid reports `error`. A passing block-level grid remains the
condition for that.
