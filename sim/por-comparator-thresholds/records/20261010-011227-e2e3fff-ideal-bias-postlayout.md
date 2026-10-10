# Record 20261010-011227-e2e3fff-ideal-bias-postlayout

- **Record ID**: 20261010-011227-e2e3fff-ideal-bias-postlayout
- **Experiment**: `por-comparator-thresholds` — por_comparator VPOR-up / VPOR-down / hysteresis over process x temperature (quasi-static VDD sweep)
- **Claim**: Issue #102 -- NOT a spec claim. Evidence for DR-003 rows 4/5 ([TBD-2] VPOR-up/VPOR-down, [TBD-3] hysteresis): records, for the unchanged design/por_comparator.sch, the VDD at which POR_RAW changes state on a quasi-static constant-dVDD/dt UP sweep (VPOR-up) and DOWN sweep (VPOR-down), their difference (hysteresis), and the margin of VPOR-up against the DR-001 2.97 V low rail, across {tt, ss, ff, sf, fs} x {-40, 27, 125 C}. Each primary sweep rate is paired with a half-rate quasi-staticity guard. Numbers are PROPOSALS for a follow-on DR-003 amendment; spec/ is not edited and nothing here relaxes the ratified spec.
- **Variant**: `ideal-bias-postlayout` -- POST-LAYOUT (issue #124, T1 item 7) counterpart of ideal-bias: identical testbench, stimulus, corner grid and rates; only the por_comparator DUT is replaced by the klt-extracted (lumped RC) netlist of layout/por_comparator/por_comparator.gds.
- **Bias treatment**: IDEAL, identical to ideal-bias (1 uA IBIAS, min(1.25 V, v(VDD)) VREF, BIAS_OK = v(VDD)).
- **Netlist provenance**: post-layout extraction (klt extract --parasitics --deck sky130, lumped RC), derived by layout/por_comparator/pex/make_sim_netlist.py (pin-order wrapper + 01v8->g5v0d10v5 MOS model rewrite; see that script and layout/por_comparator/pex/README.md) (testbench `sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds.sch`; DUT spliced from `layout/por_comparator/pex/por_comparator.pex.sim.spice`)
- **PDK**: sky130A @ open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (matches sim/pdk.json pin); models `$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice (fleet: models.pdk=sky130A, models.lib=libs.tech/combined/sky130.lib.spice)`
- **Tools**: ngspice-42 : Circuit level simulation program (host; the grid ran on the fleet); XSCHEM V3.4.4; Linux 7.0.0-1013-aws x86_64
- **Repo state**: `e2e3fff` on `feature/issue-124` (clean working tree)
- **Repo state at fleet-submit time**: `0b98b1d` on `feature/issue-124` (clean working tree) -- the commit whose netlists the fleet simulated; the line above is the commit that extracted and wrote this record
- **Fleet runner**: klt `0.5.0` / `ngspice-46` (client klt `klt 0.7.0+g5e5b55992a7f`); client/runner klt version skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init, so `set ng_nomodcheck` is carried in the netlist
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
| 100 | 72.6 | pass | klt-sim-e6d4da52a513 | 0.5.0 | done | 0b98b1d (clean) | 0 |
| 50 | 145.2 | pass | klt-sim-3eeb6b1413b2 | 0.5.0 | done | 0b98b1d (clean) | 0 |

## Per-corner results (primary rate 100 V/s; all 15 process x temperature points)
| corner | VPOR-up (V) | VPOR-down (V) | hysteresis (mV) | up edge | down edge | half-rate guard (up/down delta, mV) | status |
|---|---|---|---|---|---|---|---|
| tt_-40c | 2.6990 | 2.5484 | 150.7 | edge | edge | consistent (+0.73/-0.66) | OK |
| tt_27c | 2.6949 | 2.5454 | 149.5 | edge | edge | consistent (+1.36/-1.15) | OK |
| tt_125c | 2.6855 | 2.5450 | 140.5 | edge | edge | consistent (+0.03/+0.60) | OK |
| ss_-40c | 2.7010 | 2.5496 | 151.5 | edge | edge | consistent (+1.52/-1.26) | OK |
| ss_27c | 2.6970 | 2.5466 | 150.3 | edge | edge | consistent (+1.47/-1.01) | OK |
| ss_125c | 2.6890 | 2.5450 | 144.1 | edge | edge | consistent (+1.20/+0.48) | OK |
| ff_-40c | 2.6970 | 2.5476 | 149.5 | edge | edge | consistent (+0.58/-0.09) | OK |
| ff_27c | 2.6912 | 2.5438 | 147.3 | edge | edge | consistent (-0.20/-0.77) | OK |
| ff_125c | 2.6830 | 2.5437 | 139.3 | edge | edge | consistent (+0.54/-0.90) | OK |
| sf_-40c | 2.6970 | 2.5476 | 149.4 | edge | edge | consistent (+0.43/-0.87) | OK |
| sf_27c | 2.6930 | 2.5450 | 148.1 | edge | edge | consistent (+0.77/-0.55) | OK |
| sf_125c | 2.6850 | 2.5470 | 138.0 | edge | edge | consistent (+1.35/-0.65) | OK |
| fs_-40c | 2.6990 | 2.5490 | 150.0 | edge | edge | consistent (+0.50/-0.67) | OK |
| fs_27c | 2.6950 | 2.5455 | 149.5 | edge | edge | consistent (+0.54/-1.13) | OK |
| fs_125c | 2.6872 | 2.5426 | 144.6 | edge | edge | consistent (+0.75/-0.02) | OK |

## Binding-corner table (EVIDENCE for a follow-on DR-003 amendment; not ratified, `spec/` untouched)
Computed over the 15 of 15 corners with a clean, rate-consistent result.
| metric | min (V or mV) | corner setting the min | max (V or mV) | corner setting the max |
|---|---|---|---|---|
| VPOR-up | 2.6830 V | ff_125c | 2.7010 V | ss_-40c |
| VPOR-down | 2.5426 V | fs_125c | 2.5496 V | ss_-40c |
| hysteresis | 138.0 mV | sf_125c | 151.5 mV | ss_-40c |

Margin vs the DR-001 low rail (2.97 V): VPOR-up,max = 2.7010 V (ss_-40c) -> margin = rail - max(VPOR-up) = **+269 mV** (a positive number means the rail clears the worst-case-high rising threshold; a NEGATIVE number means VPOR-up exceeds the rail at that corner and the block would not release at the low rail). VPOR-up,min = 2.6830 V (ff_125c), i.e. +287 mV below the rail; the DR-001 high rail (3.63 V) is +929 mV above max(VPOR-up). The binding side for 'release at the low rail' is max(VPOR-up); the binding side for 'not tripping inside the operating range' is VPOR-down,min.

## Local single-corner cross-check (`--backend local`)
Single-corner LOCAL cross-check (host ngspice-42, `--backend local`, ideal-bias-postlayout, tt, 27 C, 100 V/s): VPOR-up 2.6949 V, VPOR-down 2.5455 V, hysteresis 149.4 mV. Schematic ideal-bias at the same point (fleet record 20261009-054322-10d3e9f-ideal-bias): 2.6950 V / 2.5470 V.

## Absent coverage (stated, not hidden)
- The passive-skew (ll/hh) axis is covered only as a separately-recorded supplement on tt MOS (ll/hh x 3 temperatures); combined MOS-corner x resistor-skew points (e.g. ss MOS with res_high) are NOT run -- sky130.lib.spice has no such combined section and no multi-section bundle was built for this campaign.
- Mismatch Monte Carlo (comparator input offset, divider ratio mismatch) is NOT run; the numbers are corner values of the nominal drawn circuit, not a distribution.
- Sweep rates other than 100 V/s (and its 50 V/s guard) are not simulated; supply-ramp-rate sensitivity of the assembled block is covered by sim/supply-ramp-top.
- The ideal-bias variant uses a constant 1 uA IBIAS and a 1.25 V VREF at every corner; real bias_core spread is only shown by the separately-reported real-bias-core variant.
- Post-layout scope: only por_comparator is extracted (lumped RC star per net, vertical-overlap coupling only, no lateral coupling, no distributed RC); the MOS models are rewritten 01v8 -> g5v0d10v5 because the layout lacks the hvi marker; bias_core and the testbench stimulus are schematic-level.

## Links
- testbench: `sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds.sch`
- manifest: `sim/por-comparator-thresholds/experiment.json`
- driver: `sim/por-comparator-thresholds/run_thresholds_campaign.py`
- extractor: `sim/por-comparator-thresholds/threshold_extractor.py`
- netlist_snapshots: `sim/por-comparator-thresholds/netlist-snapshots/20261010-011227-e2e3fff-ideal-bias-postlayout/`
- corners_dir: `sim/por-comparator-thresholds/corners/20261010-011227-e2e3fff-ideal-bias-postlayout/`
- json: `sim/por-comparator-thresholds/records/20261010-011227-e2e3fff-ideal-bias-postlayout.json`
- record: `sim/por-comparator-thresholds/records/20261010-011227-e2e3fff-ideal-bias-postlayout.md`
- **Timestamp / author**: 2026-10-10T01:12:27Z, Loom Builder (Claude)
- **Supersedes**: (none)

Written by `sim/por-comparator-thresholds/run_thresholds_campaign.py`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).
