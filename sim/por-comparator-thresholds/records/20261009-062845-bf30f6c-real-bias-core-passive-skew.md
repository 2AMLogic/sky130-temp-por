# Record 20261009-062845-bf30f6c-real-bias-core-passive-skew

- **Record ID**: 20261009-062845-bf30f6c-real-bias-core-passive-skew
- **Experiment**: `por-comparator-thresholds` — por_comparator VPOR-up / VPOR-down / hysteresis over process x temperature (quasi-static VDD sweep)
- **Claim**: Issue #102 -- NOT a spec claim. Evidence for DR-003 rows 4/5 ([TBD-2] VPOR-up/VPOR-down, [TBD-3] hysteresis): records, for the unchanged design/por_comparator.sch, the VDD at which POR_RAW changes state on a quasi-static constant-dVDD/dt UP sweep (VPOR-up) and DOWN sweep (VPOR-down), their difference (hysteresis), and the margin of VPOR-up against the DR-001 2.97 V low rail, across {tt, ss, ff, sf, fs} x {-40, 27, 125 C}. Each primary sweep rate is paired with a half-rate quasi-staticity guard. Numbers are PROPOSALS for a follow-on DR-003 amendment; spec/ is not edited and nothing here relaxes the ratified spec.
- **Variant**: `real-bias-core` -- SECOND, separately-reported variant: the real design/bias_core drives IBIAS, VREF and BIAS_OK.
- **Bias treatment**: REAL bias_core (design/netlist/bias_core.spice) on the same VDD supplies IBIAS, VREF and BIAS_OK, so the actual VREF(P,T,VDD) and delivered IBIAS move the edges. Never mixed with the ideal-bias table; shows how far the real reference dependence displaces the thresholds.
- **Netlist provenance**: schematic (`sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds_realbias.sch`; DUT spliced from `design/netlist/por_comparator.spice`, `design/netlist/bias_core.spice`)
- **PDK**: sky130A @ open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (matches sim/pdk.json pin); models `$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice (fleet: models.pdk=sky130A, models.lib=libs.tech/combined/sky130.lib.spice)`
- **Tools**: ngspice-42 : Circuit level simulation program (host; the grid ran on the fleet); XSCHEM V3.4.4; Linux 6.17.0-1019-aws x86_64
- **Repo state**: `bf30f6c` on `feature/issue-102` (clean working tree)
- **Repo state at fleet-submit time**: `10d3e9f` on `feature/issue-102` (clean working tree) -- the commit whose netlists the fleet simulated; the line above is the commit that extracted and wrote this record
- **Fleet runner**: klt `0.5.0` / `ngspice-46` (client klt `klt 0.7.0+g4cbdfa769875`); client/runner klt version skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init, so `set ng_nomodcheck` is carried in the netlist
- **Corner axis**: `passive-skew` -- SUPPLEMENT, recorded separately (run --axis passive-skew; record ids end in -passive-skew). sky130's ll/hh .lib sections are tt MOS/BJT with parameters_res_low/high + cap_low/high; per sim/pdk.json they are the ONLY sections that move sky130_fd_pr__res_xhigh_po sheet resistance (tt/ss/ff/sf/fs all include parameters_res_nom). klt passes a bare process string through as `.lib <models.lib> <process>`, so the axis is reachable. The divider (XRTOP/XRBOT/XRHYS) is all xhigh_po, so a ratio cancellation is expected to first order; this axis measures it rather than assuming it. Never merged with the other axis's table.
- **Corner matrix run**: process ll, hh; temperature -40 C, 27 C, 125 C; VDD is the swept variable (0 -> 3.63 V -> 0), no separate supply axis; sweep rates 100, 50 V/s (primary + half-rate guard). 6 process x temperature points; full matrix, no subset.
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
| 100 | 72.6 | pass | klt-sim-945beda51712 | 0.5.0 | done | 9f589eb (clean) | 5 |
| 50 | 145.2 | pass | klt-sim-fdcda9473f5a | 0.5.0 | done | 10d3e9f (clean) | 0 |

## Per-corner results (primary rate 100 V/s; all 6 process x temperature points)
| corner | VPOR-up (V) | VPOR-down (V) | hysteresis (mV) | up edge | down edge | half-rate guard (up/down delta, mV) | status |
|---|---|---|---|---|---|---|---|
| ll_-40c | 2.6950 | 2.5412 | 153.8 | edge | edge | consistent (+1.40/-2.12) | OK |
| ll_27c | 2.7070 | 2.5543 | 152.7 | edge | edge | consistent (+0.56/-2.04) | OK |
| ll_125c | 2.7035 | 2.5557 | 147.8 | edge | edge | consistent (+1.52/-1.28) | OK |
| hh_-40c | 2.6990 | 2.5415 | 157.6 | edge | edge | consistent (+2.52/-2.88) | OK |
| hh_27c | 2.7110 | 2.5530 | 158.1 | edge | edge | consistent (+3.36/-2.52) | OK |
| hh_125c | 2.7050 | 2.5512 | 153.8 | edge | edge | consistent (+3.14/-3.85) | OK |

## Binding-corner table (EVIDENCE for a follow-on DR-003 amendment; not ratified, `spec/` untouched)
Computed over the 6 of 6 corners with a clean, rate-consistent result.
| metric | min (V or mV) | corner setting the min | max (V or mV) | corner setting the max |
|---|---|---|---|---|
| VPOR-up | 2.6950 V | ll_-40c | 2.7110 V | hh_27c |
| VPOR-down | 2.5412 V | ll_-40c | 2.5557 V | ll_125c |
| hysteresis | 147.8 mV | ll_125c | 158.1 mV | hh_27c |

Margin vs the DR-001 low rail (2.97 V): VPOR-up,max = 2.7110 V (hh_27c) -> margin = rail - max(VPOR-up) = **+259 mV** (a positive number means the rail clears the worst-case-high rising threshold; a NEGATIVE number means VPOR-up exceeds the rail at that corner and the block would not release at the low rail). VPOR-up,min = 2.6950 V (ll_-40c), i.e. +275 mV below the rail; the DR-001 high rail (3.63 V) is +919 mV above max(VPOR-up). The binding side for 'release at the low rail' is max(VPOR-up); the binding side for 'not tripping inside the operating range' is VPOR-down,min.

## Absent coverage (stated, not hidden)
- The passive-skew (ll/hh) axis is covered only as a separately-recorded supplement on tt MOS (ll/hh x 3 temperatures); combined MOS-corner x resistor-skew points (e.g. ss MOS with res_high) are NOT run -- sky130.lib.spice has no such combined section and no multi-section bundle was built for this campaign.
- Mismatch Monte Carlo (comparator input offset, divider ratio mismatch) is NOT run; the numbers are corner values of the nominal drawn circuit, not a distribution.
- Sweep rates other than 100 V/s (and its 50 V/s guard) are not simulated; supply-ramp-rate sensitivity of the assembled block is covered by sim/supply-ramp-top.
- Post-layout parasitics are not included (schematic-level netlist).
- The ideal-bias variant uses a constant 1 uA IBIAS and a 1.25 V VREF at every corner; real bias_core spread is only shown by the separately-reported real-bias-core variant.

## Links
- testbench: `sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds_realbias.sch`
- manifest: `sim/por-comparator-thresholds/experiment.json`
- driver: `sim/por-comparator-thresholds/run_thresholds_campaign.py`
- extractor: `sim/por-comparator-thresholds/threshold_extractor.py`
- netlist_snapshots: `sim/por-comparator-thresholds/netlist-snapshots/20261009-062845-bf30f6c-real-bias-core-passive-skew/`
- corners_dir: `sim/por-comparator-thresholds/corners/20261009-062845-bf30f6c-real-bias-core-passive-skew/`
- json: `sim/por-comparator-thresholds/records/20261009-062845-bf30f6c-real-bias-core-passive-skew.json`
- record: `sim/por-comparator-thresholds/records/20261009-062845-bf30f6c-real-bias-core-passive-skew.md`
- **Timestamp / author**: 2026-10-09T06:28:45Z, Loom Builder (Claude Opus 5.5), issue #102
- **Supersedes**: (none)

Written by `sim/por-comparator-thresholds/run_thresholds_campaign.py`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).
