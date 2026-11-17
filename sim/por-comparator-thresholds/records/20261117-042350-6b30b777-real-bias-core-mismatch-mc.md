# Record 20261117-042350-6b30b777-real-bias-core-mismatch-mc

- **Record ID**: 20261117-042350-6b30b777-real-bias-core-mismatch-mc
- **Experiment**: `por-comparator-thresholds` — por_comparator VPOR-up / VPOR-down / hysteresis over process x temperature (quasi-static VDD sweep)
- **Claim**: Issue #102 -- NOT a spec claim. Evidence for DR-003 rows 4/5 ([TBD-2] VPOR-up/VPOR-down, [TBD-3] hysteresis): records, for the unchanged design/por_comparator.sch, the VDD at which POR_RAW changes state on a quasi-static constant-dVDD/dt UP sweep (VPOR-up) and DOWN sweep (VPOR-down), their difference (hysteresis), and the margin of VPOR-up against the DR-001 2.97 V low rail, across {tt, ss, ff, sf, fs} x {-40, 27, 125 C}. Each primary sweep rate is paired with a half-rate quasi-staticity guard. A mismatch Monte Carlo supplement (run --axis mc, issue #348) adds per-corner mismatch distributions for the real-bias-core variant on tt/ss; see the monte_carlo block. Numbers are PROPOSALS for a follow-on DR-003 amendment; spec/ is not edited and nothing here relaxes the ratified spec.
- **Variant**: `real-bias-core` -- SECOND, separately-reported variant: the real design/bias_core drives IBIAS, VREF and BIAS_OK.
- **Bias treatment**: REAL bias_core (design/netlist/bias_core.spice) on the same VDD supplies IBIAS, VREF and BIAS_OK, so the actual VREF(P,T,VDD) and delivered IBIAS move the edges. Never mixed with the ideal-bias table; shows how far the real reference dependence displaces the thresholds.
- **PDK**: sky130A @ open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (matches sim/pdk.json pin); models `$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice (fleet: models.pdk=sky130A, models.lib=libs.tech/combined/sky130.lib.spice)`
- **Tools**: ngspice-47 : Circuit level simulation program (host; the grid ran on the fleet); XSCHEM V3.4.7; Linux 7.0.0-1014-aws x86_64
- **Repo state**: `6b30b777` on `feature/issue-401` (clean working tree)
- **Fleet runner**: klt `0.9.0` / `ngspice-47` (client klt `klt 0.9.3.dev268+g17a90d6ed20d`); client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used
- **Corner axis**: `mc` (mismatch Monte Carlo supplement, issue #348) -- one request per (process, temperature), process sections `tt_mm, ss_mm` (local mismatch only, never MC_PR_SWITCH global process MC), temperature -40 C, 27 C, 125 C; VDD is the swept variable (0 -> 3.63 V -> 0), no separate supply axis, at the primary 100 V/s only.
- **Statistical convention**: Per corner: mean and sample sigma (Bessel, n-1) of VPOR-up, VPOR-down and hysteresis over the valid Monte Carlo samples; hysteresis is computed PER SAMPLE (VPOR-up - VPOR-down of ONE realisation), never combined from the two marginal sigmas (comparator offset moves both edges of one realisation in the same direction, so the marginal combination overstates the hysteresis spread). The statistical resolution of a corner's sigma is stated as 1/sqrt(2(N_valid - 1)) of its valid N (16.2% at N = 20). Samples graded no_transition, multiple_transitions, unresolved or wrong_direction are excluded AND counted, never silently dropped; an all-invalid corner renders a three-state NO-RESULT, never sigma = 0. NOT sampled: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard (the MC points are unguarded), the ideal-bias variant, the ff/sf/fs sections, the ll/hh passive-skew axis, and post-layout parasitics. Temperatures draw INDEPENDENT realisation sets (one transient per temperature, one realisation set per request), so per-corner statistics are valid and NO per-sample temperature-drift or temperature-correlation claim is made.

## Request sizing and seeds (why this grid cannot be bigger)
- One klt sim request per (process, temperature) = 6 requests, N = 20 mismatch samples each, at the primary 100 V/s rate. Sizing arithmetic: the measured worst-corner cost of the real-bias-core 100 V/s grid is 142 s (corners/20261009-054331-79eebd4-real-bias-core/r100/klt-report.json, per-corner runtime_s; the 15-corner request summed to 1924 s), so one request is 20 x 142 s = 2840 s of serial fleet wall clock, 21% under the fleet's 3600 s per-job ceiling; N = 24 would sit at 3408 s inside the same ceiling and N = 20 is the recorded choice with the larger headroom (the sigma resolution at N = 20 is 16.2%). Folding the three temperatures into one request would be 60 x 142 s = 8520 s -> batch_job_timeout, the exact failure sim/temp-core-accuracy-mc recorded for its first 3000-unit requests.
- Seed offsets: Seed for request k = seed + k, k = 1..6 in (process, temperature) order: tt/-40C -> 20261115, tt/27C -> 20261116, tt/125C -> 20261117, ss/-40C -> 20261118, ss/27C -> 20261119, ss/125C -> 20261120. klt derives each sample's seed from the corner index (0 inside every one-corner request here), so a shared base seed across the six requests would re-draw the SAME realisations in each; the distinct offsets keep the six realisation sets independent. Each sample's own derived seed is recorded per sample in the record.

## Fleet submissions (one request per (process, temperature))
| request | N | seed (base + offset) | outcome | job id | runner klt | state | submitted at commit | refused earlier attempts |
|---|---|---|---|---|---|---|---|---|
| tt/-40C | 20 | 20261115 (20261114 + 1) | pass | klt-sim-76394a4bbf32 | 0.9.0 | done | 86e1ee15 (clean) | 0 |
| tt/27C | 20 | 20261116 (20261114 + 2) | pass | klt-sim-a30498db7991 | 0.9.0 | done | 86e1ee15 (clean) | 0 |
| tt/125C | 20 | 20261117 (20261114 + 3) | pass | klt-sim-2ebfe1672d98 | 0.9.0 | done | 86e1ee15 (clean) | 0 |
| ss/-40C | 20 | 20261118 (20261114 + 4) | pass | klt-sim-d0d6956a2578 | 0.9.0 | done | 86e1ee15 (clean) | 0 |
| ss/27C | 20 | 20261119 (20261114 + 5) | pass | klt-sim-82373595f310 | 0.9.0 | done | 86e1ee15 (clean) | 0 |
| ss/125C | 20 | 20261120 (20261114 + 6) | pass | klt-sim-02ce15e85314 | 0.9.0 | done | 86e1ee15 (clean) | 0 |

## Per-corner mismatch distributions (N = 20 samples per corner, Bessel (n-1) sigmas)
Hysteresis is per sample (VPOR-up - VPOR-down of ONE realisation). `resolution` is the statistical resolution of that corner's sigma, 1/sqrt(2(N-1)) of its valid N -- the number a future amendment must quote with any sigma from this table.
| corner | N valid/N run | VPOR-up mean ± sigma (V) | VPOR-down mean ± sigma (V) | hysteresis mean ± sigma (mV) | sigma resolution | excluded (of N) |
|---|---|---|---|---|---|---|
| tt/-40C | 13/20 | 2.7789 ± 0.1520 | 2.6195 ± 0.1444 | 159.4 ± 7.6 | 20.4% | 7 |
| tt/27C | 10/20 | 2.7023 ± 0.1157 | 2.5521 ± 0.1127 | 150.2 ± 14.4 | 23.6% | 10 |
| tt/125C | 15/20 | 2.7396 ± 0.1478 | 2.5874 ± 0.1405 | 152.2 ± 7.4 | 18.9% | 5 |
| ss/-40C | 11/20 | 2.7675 ± 0.1033 | 2.6082 ± 0.0979 | 159.3 ± 5.5 | 22.4% | 9 |
| ss/27C | 13/20 | 2.7344 ± 0.1006 | 2.5776 ± 0.0957 | 156.9 ± 5.0 | 20.4% | 7 |
| ss/125C | 19/20 | 2.7283 ± 0.1405 | 2.5749 ± 0.1335 | 153.3 ± 7.1 | 16.7% | 1 |

### Excluded samples (counted, never silently dropped)
| corner | sample | reason |
|---|---|---|
| tt/-40C | mc0 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/-40C | mc1 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/-40C | mc7 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/-40C | mc8 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/-40C | mc9 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/-40C | mc17 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/-40C | mc18 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc3 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc4 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc5 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc6 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc7 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc10 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc11 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc13 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc14 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/27C | mc18 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/125C | mc3 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/125C | mc4 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/125C | mc6 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/125C | mc8 | NO_RESULT (up:no_transition, down:no_transition) |
| tt/125C | mc19 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc0 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc3 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc6 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc8 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc9 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc10 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc12 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc17 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/-40C | mc19 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc3 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc4 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc5 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc6 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc7 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc12 | NO_RESULT (up:no_transition, down:no_transition) |
| ss/27C | mc19 | NO_RESULT (down:multiple_transitions) |
| ss/125C | mc11 | NO_RESULT (up:no_transition, down:no_transition) |

**Failed-release realisations.** 38 of the 120 samples graded `no_transition` with POR_RAW **held low through the entire sweep** -- in those realisations reset never releases within the 3.63 V peak. In every one of them `bias_core`'s reference came up (max v(vref) over the sweep 1.137-1.376 V, the intended 1.25 V branch), so the failure is downstream of the reference -- not a bias_core startup failure.
The per-corner distributions above therefore describe only the **releasing subset** of each corner; the failed-release fraction is part of the mismatch behaviour this record measures, and DR-004's corner margin does not capture it.

### Failed-release mechanism diagnostics (issue #401)
Per-sample reduction of the enable/clamp path the netlist already saves (`v(bias_ok)`, `v(xdut.cmpo)`, `v(xdut.n1)`, `v(xdut.sns)`): each node's sweep max and its value at the sweep peak (t = tstop/2, interpolated; the VDD peak is 3.63 V). `BIAS_OK asserted` means its at-peak level is a rail swing -- at least 0.9 of the at-peak supply; `CMPO released` means max v(xdut.cmpo) >= 0.5 V. Both are diagnostic labels on recorded evidence, and the raw values below can be re-read against any other criterion. `sns` at the peak carries the input-differential check: SNS sits at the divider ratio times the peak whether or not the comparator trips, so a stuck sample still shows a release-direction differential.

| corner | sample | class | BIAS_OK max (V) | BIAS_OK @peak (V) | VDD @peak (V) | CMPO max (V) | CMPO @peak (V) | N1 @peak (V) | SNS @peak (V) | vref max (V) |
|---|---|---|---|---|---|---|---|---|---|---|
| tt/-40C | mc0 | enable-clamp | 0.101 | 0.000 | 3.630 | 0.220 | 0.000 | 3.630 | 1.676 | 1.263 |
| tt/-40C | mc1 | enable-clamp | 0.104 | 0.000 | 3.630 | 0.216 | 0.000 | 3.630 | 1.676 | 1.313 |
| tt/-40C | mc7 | enable-clamp | 0.107 | 0.000 | 3.630 | 0.217 | 0.000 | 3.630 | 1.676 | 1.204 |
| tt/-40C | mc8 | enable-clamp | 0.107 | 0.000 | 3.630 | 0.212 | 0.000 | 3.630 | 1.675 | 1.319 |
| tt/-40C | mc9 | enable-clamp | 0.106 | 0.000 | 3.630 | 0.217 | 0.000 | 3.630 | 1.676 | 1.274 |
| tt/-40C | mc17 | enable-clamp | 0.100 | 0.000 | 3.630 | 0.216 | 0.000 | 3.630 | 1.676 | 1.284 |
| tt/-40C | mc18 | enable-clamp | 0.102 | 0.000 | 3.630 | 0.216 | 0.000 | 3.630 | 1.676 | 1.290 |
| tt/27C | mc3 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.053 | 0.000 | 3.630 | 1.675 | 1.225 |
| tt/27C | mc4 | enable-clamp | 0.012 | 0.000 | 3.630 | 0.061 | 0.000 | 3.630 | 1.675 | 1.214 |
| tt/27C | mc5 | enable-clamp | 0.010 | 0.000 | 3.630 | 0.049 | 0.000 | 3.630 | 1.676 | 1.236 |
| tt/27C | mc6 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.054 | 0.000 | 3.630 | 1.676 | 1.256 |
| tt/27C | mc7 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.052 | 0.000 | 3.630 | 1.676 | 1.197 |
| tt/27C | mc10 | enable-clamp | 0.010 | 0.000 | 3.630 | 0.047 | 0.000 | 3.630 | 1.675 | 1.239 |
| tt/27C | mc11 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.042 | 0.000 | 3.630 | 1.676 | 1.312 |
| tt/27C | mc13 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.045 | 0.000 | 3.630 | 1.675 | 1.325 |
| tt/27C | mc14 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.059 | 0.000 | 3.630 | 1.676 | 1.291 |
| tt/27C | mc18 | enable-clamp | 0.011 | 0.000 | 3.630 | 0.045 | 0.000 | 3.630 | 1.675 | 1.137 |
| tt/125C | mc3 | enable-clamp | 0.981 | 0.000 | 3.630 | 0.095 | 0.000 | 3.630 | 1.676 | 1.210 |
| tt/125C | mc4 | enable-clamp | 0.987 | 0.000 | 3.630 | 0.099 | 0.000 | 3.630 | 1.676 | 1.213 |
| tt/125C | mc6 | enable-clamp | 0.989 | 0.000 | 3.630 | 0.104 | 0.000 | 3.630 | 1.676 | 1.269 |
| tt/125C | mc8 | enable-clamp | 0.004 | 0.000 | 3.630 | 0.004 | 0.000 | 3.630 | 1.675 | 1.151 |
| tt/125C | mc19 | enable-clamp | 0.973 | 0.000 | 3.630 | 0.088 | 0.000 | 3.630 | 1.676 | 1.187 |
| ss/-40C | mc0 | enable-clamp | 0.128 | 0.000 | 3.630 | 0.237 | 0.000 | 3.630 | 1.676 | 1.206 |
| ss/-40C | mc3 | enable-clamp | 0.127 | 0.000 | 3.630 | 0.243 | 0.000 | 3.630 | 1.676 | 1.376 |
| ss/-40C | mc6 | enable-clamp | 0.131 | 0.000 | 3.630 | 0.239 | 0.000 | 3.630 | 1.675 | 1.297 |
| ss/-40C | mc8 | enable-clamp | 0.119 | 0.000 | 3.630 | 0.238 | 0.000 | 3.630 | 1.676 | 1.370 |
| ss/-40C | mc9 | enable-clamp | 0.128 | 0.000 | 3.630 | 0.241 | 0.000 | 3.630 | 1.675 | 1.217 |
| ss/-40C | mc10 | enable-clamp | 0.126 | 0.000 | 3.630 | 0.241 | 0.000 | 3.630 | 1.676 | 1.162 |
| ss/-40C | mc12 | enable-clamp | 0.125 | 0.000 | 3.630 | 0.237 | 0.000 | 3.630 | 1.676 | 1.233 |
| ss/-40C | mc17 | enable-clamp | 0.127 | 0.000 | 3.630 | 0.241 | 0.000 | 3.630 | 1.676 | 1.268 |
| ss/-40C | mc19 | enable-clamp | 0.127 | 0.000 | 3.630 | 0.238 | 0.000 | 3.630 | 1.677 | 1.277 |
| ss/27C | mc3 | enable-clamp | 0.019 | 0.000 | 3.630 | 0.061 | 0.000 | 3.630 | 1.677 | 1.232 |
| ss/27C | mc4 | enable-clamp | 0.017 | 0.000 | 3.630 | 0.065 | 0.000 | 3.630 | 1.676 | 1.195 |
| ss/27C | mc5 | enable-clamp | 0.020 | 0.000 | 3.630 | 0.062 | 0.000 | 3.630 | 1.677 | 1.275 |
| ss/27C | mc6 | enable-clamp | 0.020 | 0.000 | 3.630 | 0.058 | 0.000 | 3.630 | 1.676 | 1.282 |
| ss/27C | mc7 | enable-clamp | 0.017 | 0.000 | 3.630 | 0.055 | 0.000 | 3.630 | 1.676 | 1.195 |
| ss/27C | mc12 | enable-clamp | 0.019 | 0.000 | 3.630 | 0.058 | 0.000 | 3.630 | 1.675 | 1.292 |
| ss/125C | mc11 | enable-clamp | 1.043 | 0.000 | 3.630 | 0.112 | 0.000 | 3.630 | 1.676 | 1.317 |

**Mechanism established, all 38 failed-release realisations: the enable/clamp path never released.** in 38 the enable/clamp path never released (BIAS_OK never asserted -- at the sweep peak its level is not a rail swing, below 0.9 of the at-peak supply, so BIAS_OKB stayed high, XMDCMPO held CMPO at VSS and XMENSRC kept the load rail VDDA disconnected).

## Reproduction of record 20261115-002854-ad5bbeda-real-bias-core-mismatch-mc (seed-for-seed)
**Reproduced.** 120 samples across 6 corner entries compared against the predecessor record by (process, temperature, sample index): derived seeds all match, pass/fail pattern (valid flag + exclusion reason) all match, extracted values all within the stated 0.1 mV tolerance (max absolute delta 0.000 mV). A non-reproduction is stated here, never quietly re-baselined: the predecessor record stands as committed evidence.

## Statistical disclosures (stated, not hidden)
- **NOT a spec claim.** This record supplies a distribution as evidence; it proposes no threshold. `spec/` is untouched and DR-004 is not edited.
- **Independent realisation sets per temperature**: each temperature is its own transient run and its own request, so temperatures draw independent mismatch realisations. Per-corner statistics are valid; this record makes NO per-sample temperature-drift or temperature-correlation claim.
- **Unguarded points**: the MC grid runs the primary 100 V/s rate only, WITHOUT the half-rate quasi-staticity guard. That guard is what makes the corner-matrix results quasi-static evidence; the MC points inherit the rate choice the nominal campaign established 15/15 at every corner and are disclosed as unguarded.
- **Not sampled**: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard, the ideal-bias variant, the ll/hh passive-skew axis, post-layout parasitics, and the ff/sf/fs process sections.

## Margin context (evidence toward a possible future amendment; no proposal)
DR-004's margin `2.97 V - max(VPOR-up)` = +257 mV (real-bias-core, ss, 27 C) is a CORNER number with no sigma attached; the distributions below put a mismatch spread beside it. This is evidence toward a possible future amendment of that recommendation. It is NOT a spec claim: no threshold is proposed or ratified here, `spec/` is untouched and DR-004 is not edited.
Beside it: the ss/27 C mismatch distribution of VPOR-up is 2.7344 ± 0.1006 V over N = 13 (sigma resolution 20.4%). No number here amends or replaces DR-004's corner margin.
Note also the failed-release realisations counted above: 38 of 120 samples never release reset at all. A margin computed over releasing realisations -- corner or distribution -- does not describe those samples.

## Absent coverage (stated, not hidden)
- The passive-skew (ll/hh) axis is covered only as a separately-recorded supplement on tt MOS (ll/hh x 3 temperatures); combined MOS-corner x resistor-skew points (e.g. ss MOS with res_high) are NOT run -- sky130.lib.spice has no such combined section and no multi-section bundle was built for this campaign.
- Mismatch Monte Carlo is run only as the `--axis mc` supplement: the real-bias-core variant, tt/ss sections, -40/27/125 C, at the 100 V/s primary rate, N = 20 per corner (see the monte_carlo block). NOT sampled by it: the ideal-bias variant, the ff/sf/fs sections, the ll/hh passive-skew axis, global process MC, and mismatch on the post-layout extracted netlist. The corner-matrix numbers remain corner values of the nominal drawn circuit.
- Sweep rates other than 100 V/s (and its 50 V/s guard) are not simulated; supply-ramp-rate sensitivity of the assembled block is covered by sim/supply-ramp-top.
- Post-layout parasitics are not included (schematic-level netlist).
- The ideal-bias variant uses a constant 1 uA IBIAS and a 1.25 V VREF at every corner; real bias_core spread is only shown by the separately-reported real-bias-core variant.

## Links
- testbench: `sim/por-comparator-thresholds/testbench/tb_por_comparator_thresholds_realbias.sch`
- manifest: `sim/por-comparator-thresholds/experiment.json`
- driver: `sim/por-comparator-thresholds/run_thresholds_campaign.py`
- extractor: `sim/por-comparator-thresholds/threshold_extractor.py`
- netlist_snapshots: `sim/por-comparator-thresholds/netlist-snapshots/20261117-042350-6b30b777-real-bias-core-mismatch-mc/`
- artifact_manifest: `manifests/artifacts/por-comparator-thresholds-20261117-042350-6b30b777-real-bias-core-mismatch-mc.manifest.json`
- artifact_summary: `manifests/artifacts/por-comparator-thresholds-20261117-042350-6b30b777-real-bias-core-mismatch-mc.summary.md`
- json: `sim/por-comparator-thresholds/records/20261117-042350-6b30b777-real-bias-core-mismatch-mc.json`
- record: `sim/por-comparator-thresholds/records/20261117-042350-6b30b777-real-bias-core-mismatch-mc.md`
- **Timestamp / author**: 2026-11-17T04:23:50Z, opencode (Loom builder)
- **Supersedes**: 20261115-002854-ad5bbeda-real-bias-core-mismatch-mc

Written by `sim/por-comparator-thresholds/run_thresholds_campaign.py run --axis mc`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).
