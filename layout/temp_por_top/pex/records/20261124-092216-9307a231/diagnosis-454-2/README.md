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
grid's `corner.cir`. The decks retain the 2.64 V `RISE=1` crossing and
the original 30 ms window except for `long` (300 ms) and `5ms` runs.

Run names below map to `inputs/deck-<run>.cir` and `runs/<run>-run.txt`.
The following logs have different names from their decks.

| Deck in `inputs/` | Log in `runs/` |
|---|---|
| `deck-tt-n40-trace.cir` | `tt-n40-trace-repeat-run.txt` (unseeded control repeated alongside the corrected nodeset) |
| `deck-tt-n40-reltol-1e-4-full.cir` | `tt-n40-reltol-1e-4-30ms-run.txt` and `tt-n40-reltol-1e-4-30ms-partial-run.txt` (earlier partial run) |
| `deck-sch-tt-reltol-1e-4.cir` | `sch-tt-reltol-1e-4-partial-run.txt` |
| `deck-sch-tt-reltol-1e-5.cir` | `sch-tt-reltol-1e-5-partial-run.txt` |
| Deck unavailable | `tt-n40-reltol-1e-5-30ms-partial-run.txt` (exploratory run, last logged timestep 7.05 ms) |

## Runs at tt/3.300V/-40C (extracted leg unless stated)

| run | one change vs base | PTAT max / 30 ms value | RESETn | crossing |
|---|---|---|---|---|
| `tt-n40-base` | none (reproduction of `../diagnosis-454`) | 14.96 V @ 1.208 ms / **12.789 V** | max 52.7 mV @ 10.2 us; -6.9 mV @ 30 ms | none |
| `tt-n40-trace` | time probes only | 14.96 V @ 1.208 ms / 12.79 V | -3.2 mV @ 2 ms ... -7.6 mV @ 29 ms | none |
| `tt-n40-nodeset` | ngspice ignored the nonexistent `xdut.ptat` node (warning on line 1 of the log) | invalid control | | |
| `tt-n40-nodeset-ptat` | 0.283 V nodeset on the `ptat` hub and all three split terminals, same deck as `tt-n40-trace` otherwise | 0.543 mV @ 5.12 us / **−3.446 V** | 3.041 V @ 2 ms, −33.7 mV @ 30 ms | **1.20544 ms** |
| `tt-n40-long` | window 300 ms | 16.05 V @ 55.3 ms / 12.79 V @ 30 ms, 3.291 V @ 100-200 ms | 3.040 V from ~55.3 ms | **55.30 ms** (on the garbage trajectory) |
| `tt-n40-reltol-1e-3-5ms` | window 5 ms (control) | 14.96 V @ 1.208 ms / 12.81 V @ 4 ms | -13.1 mV @ 5 ms | none |
| `tt-n40-reltol-1e-4-5ms` | + `reltol=1e-4` | **2.907 V** @ 1.216 ms / -11.9 mV @ 2 ms | 3.041 V @ 1.23 ms, -12.4 mV @ 5 ms | **1.2139 ms** |
| `tt-n40-reltol-1e-5-5ms` | + `reltol=1e-5` | **3.058 V** @ 1.219 ms / 1.380 V @ 4 ms | 3.041 V @ 1.22 ms, 3.041 V @ 5 ms | **1.2161 ms** |
| `tt-n40-reltol-1e-4-30ms` | `reltol=1e-4`, original 30 ms window | -47 uV @ 30 ms | crossing at 1.2139 ms, but the tail cycles (max 3.055 V @ 16.2 ms, ~0 V at 10/20/30 ms) | **1.2139 ms** |
| `tt-n40-nocc` | 131 `Ccc_*` coupling caps removed | 1.57 mV @ 80 us / **0.40 mV** | max 52.7 mV @ 10.2 us, 1.07 mV @ 30 ms | none |
| `tt-n40-nocc-long` | + window 300 ms | 0.40 mV decaying to 0.39 mV @ 290 ms | ~1.04-1.07 mV throughout | none |
| `tt-n40-nor` | 569 star resistors shorted (1 u-ohm) | transient op solves after gmin/source-stepping failures, last logged timestep 0.116 ms | -- | incomplete |

Schematic leg, same point:

| run | netlist / change | PTAT | RESETn | crossing |
|---|---|---|---|---|
| `sch-tt` | grid schematic (`g5v0d10v5` MOS) | ~1e-8 V until ~2.7 ms (dead), then 0.2830 V; max 1.616 V @ 2.759 ms | 2.9698 V | **2.7574 ms** |
| `sch-tt-reltol-1e-4-partial` | + `reltol=1e-4` | last logged timestep 12.6 ms of 30 ms | | incomplete |
| `sch-tt-reltol-1e-5-partial` | + `reltol=1e-5` | last logged timestep 6.1 ms of 30 ms | | incomplete |
| `sch-tt-01v8swap` | schematic with the extractor's model swap (`g5v0d10v5` -> `01v8`, 114 MOS, no parasitics) | 0.2683 V; max 3.678 V @ 0.21 ms (brief, recovers) | 3.1089 V | **1.1817 ms** |

## What the tt/3.300V/-40C runs establish (AC 1)

1. **The 12.79 V PTAT state is a non-physical transient solution.** ngspice
   reports `1.47691e+236, 2 out of range for ^` in `b.xdut.x$153.brbody`
   (the `res_xhigh_po` body resistor)
   during the initial operating-point solve. Gmin stepping completes with PTAT
   at −9.86e−153 V. At 30 ms, PTAT is 3.9 times the 3.30 V supply voltage. [Base log](runs/tt-n40-base-run.txt)
   Tightening `reltol` from 1e-3 to 1e-4 reduces the 5 ms PTAT peak
   from 14.96 V to 2.91 V.
   The 30 ms run at 1e-4 measures PTAT at −47 µV at the end and gives the
   first 2.64 V crossing at **1.2139 ms**, 0.44x the schematic's 2.757 ms.
2. **The excursion develops during the transient and depends on the operating-point
   starting guess.** In `tt-n40-trace-repeat`, unseeded PTAT starts at
   −9.86e−153 V, reaches −3.44 V at 1 ms, peaks at +14.96 V at 1.208 ms
   and is +12.83 V at 2 ms. RESETn misses 2.64 V. In `tt-n40-nodeset-ptat`,
   ngspice accepts the 0.283 V guess on `ptat` and `xdut.ptat__t0` through
   `xdut.ptat__t2`. PTAT converges to 2.96e−15 V initially, falls to −3.511 V
   at 2 ms and ends at −3.446 V. RESETn crosses at 1.20544 ms and returns low
   by 10 ms. The valid nodeset changes which non-physical trajectory is reached.
3. **Removing all coupling capacitors suppresses the excursion in this run.**
   With the 131 `Ccc_*` cards removed, PTAT stays near 0.4 mV and the block
   stays on the zero-current branch through 300 ms. The grid schematic starts
   at 2.76 ms. In `../grid/temp_por_top.pex.spice`, the 131 couplings range
   from 3.869e−18 to 2.2846e−16 F. The 16 with a PTAT endpoint range from
   3.869e−18 to 3.0948e−17 F. The 71 net-to-substrate caps range from
   1.7277e−15 to 1.7074e−12 F. The smallest substrate cap is 7.6 times the
   largest coupling cap. The removal experiment shows the extracted simulation
   is sensitive to these cards. Their physical contribution remains unmeasured.
4. **The 300 ms run crosses on a non-physical trajectory.** At default
   tolerance RESETn crosses at 55.30 ms, and PTAT peaks at 16.05 V at
   55.31 ms. RESETn subsequently stays high while PTAT settles near 3.29 V.
5. **The #467 model swap advances schematic release at this cold tt point.**
   Changing only the 114 schematic MOS models from `g5v0d10v5` to `01v8`
   moves the 2.64 V crossing from 2.75744 ms to **1.18170 ms**. The extracted
   run at `reltol=1e-4` crosses at 1.2139 ms. [Original schematic](runs/sch-tt-run.txt) · [Model-swapped schematic](runs/sch-tt-01v8swap-run.txt)

   In the fleet grid, 20 passing
   `request-ramp.t_release_v_ih` rows release at 0.32–0.88 times their
   schematic crossing time. The cold tt result (0.43 times the original)
   makes the model mismatch a plausible explanation for those early releases.
   The other four passing rows release at 6.17–10.04 times their schematic
   crossing time. Their cause remains open. [Fleet grid report](../grid/klt-pex.report.json)

   The `nor` variant (star-R short)
   completes its operating-point solve, but its transient log ends at 0.116 ms,
   before a release time could be measured.
6. **Tighter tolerance increases the number of transient samples.** Over the
   same 30 ms, ngspice reports 3,072 rows at default tolerance and 2,247,983
   at 1e-4. The schematic logs at 1e-4 and 1e-5 end at 12.6 and 6.1 ms
   respectively. The operator reported about 46 minutes for the extracted
   1e-4 run, 240 s for each partial schematic run and 300 s for `nor`.
   Those wall times are unrecorded operator observations. Performance against
   the fleet request's 3,000 s timeout remains unverified. [Ramp request](../pextb-grid/request-ramp.json)

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
  [30 ms schematic log](runs/sch-sf-run.txt) · [300 ms schematic log](runs/sch-sf-long-run.txt)
- **Extracted leg at the same corner: the non-physical branch, opposite
  polarity.** PTAT parks at **-3.44 V** (below ground) with RESETn low
  (max 42.5 mV at 10.2 us); removing the coupling caps collapses it to the
  dead branch (0.39 mV, no start). The `01v8`-swapped schematic at this
  corner releases at 1.047 ms (RESETn-high 2.789 V, crosses 2.64 V) while its
  own PTAT rides a 4.557 V excursion -- so the non-physical PTAT branch is a
  property of the `01v8` leg + default tolerance, appearing with or without
  parasitics, in either polarity, at both tested corners.
  [Extracted log](runs/ext-sf-run.txt) · [Coupling removed](runs/ext-sf-nocc-run.txt) · [Model-swapped schematic](runs/sch-sf-01v8swap-run.txt)

## Attribution of the 24 group-A rows (supersedes "design vs solver unresolved")

- **22 extracted-only rows cover 11 corners with two ramp measurements each.**
  The schematic crosses at all 11. The extracted `tt/3.300V/-40C` run
  demonstrates a non-physical branch sensitive to tolerance, the PTAT nodeset
  and coupling capacitance. A similar branch is the inferred cause of the
  missed crossings at the other ten corners.
- **The remaining two rows cover `sf/2.970V/-40C`, where both legs miss.**
  The report attributes the rows to the schematic side. Its 2.6383 V logic
  high falls below the harness's fixed 2.64 V threshold (**#521**).
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
  the klt pin bump). The schematic model-swap controls cover only
  `tt/3.300V/-40C` and `sf/2.970V/-40C`. Both are error rows for
  `request-ramp.t_release_v_ih` in the fleet grid. The contribution of the
  mismatch to release timing at the 24 passing corners remains unmeasured.

Neither report is cited as item 7 in the manifest: the pilot is a single
point and the grid reports `error`. A passing block-level grid remains the
condition for that.
