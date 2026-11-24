# Record 20261124-031933-1df0a90f-real-bias-core-biaspex

- **Record ID**: 20261124-031933-1df0a90f-real-bias-core-biaspex
- **Experiment**: `por-comparator-thresholds` — por_comparator VPOR-up / VPOR-down / hysteresis over process x temperature (quasi-static VDD sweep)
- **Claim**: Issue #102 -- NOT a spec claim. Evidence for DR-003 rows 4/5 ([TBD-2] VPOR-up/VPOR-down, [TBD-3] hysteresis): records, for the unchanged design/por_comparator.sch, the VDD at which POR_RAW changes state on a quasi-static constant-dVDD/dt UP sweep (VPOR-up) and DOWN sweep (VPOR-down), their difference (hysteresis), and the margin of VPOR-up against the DR-001 2.97 V low rail, across {tt, ss, ff, sf, fs} x {-40, 27, 125 C}. Each primary sweep rate is paired with a half-rate quasi-staticity guard. A mismatch Monte Carlo supplement (run --axis mc, issue #348) adds per-corner mismatch distributions for the real-bias-core variant on tt/ss; see the monte_carlo block. Numbers are PROPOSALS for a follow-on DR-003 amendment; spec/ is not edited and nothing here relaxes the ratified spec.
- **Variant**: `real-bias-core-biaspex` -- BIAS-CORE POST-LAYOUT (issue #487): same testbench, stimulus, corner grid and rates as real-bias-core; the schematic bias_core is replaced by the klt-extracted (lumped RC) netlist of layout/bias_core/bias_core.gds (the post-#473/#488 render). por_comparator stays the schematic export.
- **Bias treatment**: REAL bias_core, extracted layout, drives IBIAS, VREF and BIAS_OK, identical stimulus to real-bias-core. Only bias_core is extracted; never mixed with the por_comparator post-layout variants (one extraction per record).
- **Netlist provenance**: post-layout extraction of bias_core only (klt extract --parasitics --deck sky130, lumped RC), derived by layout/bias_core/pex/make_sim_netlist.py (net-alias collapse + 01v8->g5v0d10v5 MOS model rewrite; see that script and layout/bias_core/pex/README.md) (testbench `sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds_realbias.sch`; DUT spliced from `design/netlist/por_comparator.spice`, `layout/bias_core/pex/bias_core.pex.sim.spice`)
- **PDK**: sky130A @ open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (matches sim/pdk.json pin); models `$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice (fleet: models.pdk=sky130A, models.lib=libs.tech/combined/sky130.lib.spice)`
- **Tools**: ngspice-47 : Circuit level simulation program (host; the grid ran on the fleet); XSCHEM V3.4.7; Linux 6.17.0-1019-aws x86_64
- **Repo state**: `1df0a90f` on `feature/issue-487` (clean working tree)
- **Repo state at fleet-submit time**: `1df0a90f` on `feature/issue-487` (clean working tree) -- the commit whose netlists the fleet simulated; the line above is the commit that extracted and wrote this record
- **Fleet runner**: klt `0.9.0` / `ngspice-47` (client klt `klt 0.9.3.dev4596+gaca420899fc0`); client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used
- **Corner axis**: `main` -- main = the 5 MOS process corners (the issue's 5x3 grid). Never merged with the other axis's table.
- **Corner matrix run**: process tt, ss, ff, sf, fs; temperature -40 C, 27 C, 125 C; VDD is the swept variable (0 -> 3.63 V -> 0), no separate supply axis; sweep rates 100, 50 V/s (primary + half-rate guard). 15 process x temperature points; full matrix, no subset.
- **Statistical convention**: N/A (corner-matrix check; no mismatch Monte Carlo)

## Measurement definitions (this campaign; none is a ratified bound)
- **VPOR-up / VPOR-down**: interpolated VDD at which POR_RAW crosses 0.5*VDD (POR_RAW high = above half the instantaneous supply) during the UP / DOWN segment; segments split at the VDD maximum; state evaluated only for VDD >= 1.0 V
- **hysteresis**: VPOR-up - VPOR-down at the same process/temperature
- **no transition**: a segment in which POR_RAW does not change state is reported as no_transition (with the state it stayed in), not omitted; hysteresis is then NO_RESULT
- **resolution**: an edge is accepted only if the two samples bracketing it differ by <= 10 mV of VDD; otherwise UNRESOLVED
- **quasi-static guard**: VPOR-up and VPOR-down at the primary rate must agree with the half-rate sweep within 10 mV (stated tolerance, chosen for this campaign, not ratified); otherwise the corner is reported RATE-DEPENDENT and excluded from the binding-corner table
- **binding corner**: the process/temperature point that sets the minimum or maximum of each metric over the corners with a clean, rate-consistent result
- **sweep**: V(VDD) = min(peak, rate*t, max(0, 2*peak - rate*t)): UP from a physical 0 V start at +rate V/s to the 3.63 V peak (the DR-001 high rail), then DOWN at -rate V/s to 0 V. Total sweep time 2*peak/rate is derived from the rate, never a fixed duration (gf180 DR-021 confound). VDD is the swept variable, so there is no separate supply axis; the klt corners.supply_v axis carries only the single sweep-peak value. Maximum time step 20 us = 2 mV of VDD at 100 V/s (1 mV at the 50 V/s half-rate guard).
- **rates**: dVDD/dt is constant and derived from the rate; each rate gets one klt request covering all 15 process x temperature points.
- **edge extraction**: VDD sample step <= 10 mV around an edge, linear interpolation inside the bracket; POR_RAW state evaluated for VDD >= 1 V only

## Fleet submissions
| rate (V/s) | tstop (ms) | outcome | job id | runner klt | state | submitted at commit | refused earlier attempts |
|---|---|---|---|---|---|---|---|
| 100 | 72.6 | pass | klt-sim-3be22062a748 | 0.9.0 | done | 1df0a90f (clean) | 0 |
| 50 | 145.2 | pass | klt-sim-a38996413186 | 0.9.0 | done | 1df0a90f (clean) | 0 |

## Per-corner results (primary rate 100 V/s; all 15 process x temperature points)
| corner | VPOR-up (V) | VPOR-down (V) | hysteresis (mV) | up edge | down edge | half-rate guard (up/down delta, mV) | status |
|---|---|---|---|---|---|---|---|
| tt_-40c | 2.6999 | 2.5443 | 155.6 | edge | edge | consistent (+2.02/-2.59) | OK |
| tt_27c | 2.7125 | 2.5580 | 154.5 | edge | edge | consistent (+0.98/-2.08) | OK |
| tt_125c | 2.7093 | 2.5610 | 148.3 | edge | edge | consistent (+1.62/-1.52) | OK |
| ss_-40c | 2.7030 | 2.5470 | 156.1 | edge | edge | consistent (+1.52/-2.52) | OK |
| ss_27c | 2.7171 | 2.5609 | 156.2 | edge | edge | consistent (+2.37/-1.81) | OK |
| ss_125c | 2.7131 | 2.5610 | 152.2 | edge | edge | consistent (+1.33/-2.27) | OK |
| ff_-40c | 2.6970 | 2.5412 | 155.8 | edge | edge | consistent (+1.92/-2.64) | OK |
| ff_27c | 2.7090 | 2.5555 | 153.6 | edge | edge | consistent (+1.53/-1.90) | OK |
| ff_125c | 2.7052 | 2.5590 | 146.3 | edge | edge | consistent (+1.47/-2.70) | OK |
| sf_-40c | 2.6930 | 2.5390 | 154.1 | edge | edge | consistent (+2.46/-1.07) | OK |
| sf_27c | 2.7070 | 2.5527 | 154.3 | edge | edge | consistent (+2.52/-1.77) | OK |
| sf_125c | 2.7037 | 2.5581 | 145.6 | edge | edge | consistent (+1.33/-2.77) | OK |
| fs_-40c | 2.7030 | 2.5472 | 155.8 | edge | edge | consistent (+1.52/-2.71) | OK |
| fs_27c | 2.7170 | 2.5610 | 156.0 | edge | edge | consistent (+3.02/-2.11) | OK |
| fs_125c | 2.7130 | 2.5592 | 153.8 | edge | edge | consistent (+2.47/-2.84) | OK |

## Binding-corner table (EVIDENCE for a follow-on DR-003 amendment; not ratified, `spec/` untouched)
Computed over the 15 of 15 corners with a clean, rate-consistent result.
| metric | min (V or mV) | corner setting the min | max (V or mV) | corner setting the max |
|---|---|---|---|---|
| VPOR-up | 2.6930 V | sf_-40c | 2.7171 V | ss_27c |
| VPOR-down | 2.5390 V | sf_-40c | 2.5610 V | ss_125c |
| hysteresis | 145.6 mV | sf_125c | 156.2 mV | ss_27c |

Margin vs the DR-001 low rail (2.97 V): VPOR-up,max = 2.7171 V (ss_27c) -> margin = rail - max(VPOR-up) = **+253 mV** (a positive number means the rail clears the worst-case-high rising threshold; a NEGATIVE number means VPOR-up exceeds the rail at that corner and the block would not release at the low rail). VPOR-up,min = 2.6930 V (sf_-40c), i.e. +277 mV below the rail; the DR-001 high rail (3.63 V) is +913 mV above max(VPOR-up). The binding side for 'release at the low rail' is max(VPOR-up); the binding side for 'not tripping inside the operating range' is VPOR-down,min.

## Absent coverage (stated, not hidden)
- The passive-skew (ll/hh) axis is covered only as a separately-recorded supplement on tt MOS (ll/hh x 3 temperatures); combined MOS-corner x resistor-skew points (e.g. ss MOS with res_high) are NOT run -- sky130.lib.spice has no such combined section and no multi-section bundle was built for this campaign.
- Mismatch Monte Carlo is run only as the `--axis mc` supplement: the real-bias-core variant, tt/ss sections, -40/27/125 C, at the 100 V/s primary rate, N = 20 per corner (see the monte_carlo block). NOT sampled by it: the ideal-bias variant, the ff/sf/fs sections, the ll/hh passive-skew axis, global process MC, and mismatch on the post-layout extracted netlist. The corner-matrix numbers remain corner values of the nominal drawn circuit.
- Sweep rates other than 100 V/s (and its 50 V/s guard) are not simulated; supply-ramp-rate sensitivity of the assembled block is covered by sim/supply-ramp-top.
- The ideal-bias variant uses a constant 1 uA IBIAS and a 1.25 V VREF at every corner; real bias_core spread is only shown by the separately-reported real-bias-core variant.
- Post-layout scope: only bias_core is extracted (lumped RC star per net, vertical-overlap coupling only, no lateral coupling, no distributed RC; the ~5.9 mm of res_xhigh_po bodies are the drawn-geometry model cards, so their own distributed capacitance is not extracted beyond the per-net lumped cap); the MOS models are rewritten 01v8 -> g5v0d10v5 because the layout lacks the hvi marker; por_comparator and the testbench stimulus are schematic-level.

## Links
- testbench: `sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds_realbias.sch`
- manifest: `sim/por-comparator-thresholds/experiment.json`
- driver: `sim/por-comparator-thresholds/run_thresholds_campaign.py`
- extractor: `sim/por-comparator-thresholds/threshold_extractor.py`
- netlist_snapshots: `sim/por-comparator-thresholds/netlist-snapshots/20261124-031933-1df0a90f-real-bias-core-biaspex/`
- artifact_manifest: `manifests/artifacts/por-comparator-thresholds-20261124-031933-1df0a90f-real-bias-core-biaspex.manifest.json`
- artifact_summary: `manifests/artifacts/por-comparator-thresholds-20261124-031933-1df0a90f-real-bias-core-biaspex.summary.md`
- json: `sim/por-comparator-thresholds/records/20261124-031933-1df0a90f-real-bias-core-biaspex.json`
- record: `sim/por-comparator-thresholds/records/20261124-031933-1df0a90f-real-bias-core-biaspex.md`
- **Timestamp / author**: 2026-11-24T03:19:33Z, 313063438+loom-fleet-dispatch[bot]@users.noreply.github.com
- **Supersedes**: (none)

Written by `sim/por-comparator-thresholds/run_thresholds_campaign.py`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).
