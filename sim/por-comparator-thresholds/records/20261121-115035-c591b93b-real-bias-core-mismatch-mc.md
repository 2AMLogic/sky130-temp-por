# Record 20261121-115035-c591b93b-real-bias-core-mismatch-mc

- **Record ID**: 20261121-115035-c591b93b-real-bias-core-mismatch-mc
- **Experiment**: `por-comparator-thresholds` — por_comparator VPOR-up / VPOR-down / hysteresis over process x temperature (quasi-static VDD sweep)
- **Claim**: Issue #102 -- NOT a spec claim. Evidence for DR-003 rows 4/5 ([TBD-2] VPOR-up/VPOR-down, [TBD-3] hysteresis): records, for the unchanged design/por_comparator.sch, the VDD at which POR_RAW changes state on a quasi-static constant-dVDD/dt UP sweep (VPOR-up) and DOWN sweep (VPOR-down), their difference (hysteresis), and the margin of VPOR-up against the DR-001 2.97 V low rail, across {tt, ss, ff, sf, fs} x {-40, 27, 125 C}. Each primary sweep rate is paired with a half-rate quasi-staticity guard. A mismatch Monte Carlo supplement (run --axis mc, issue #348) adds per-corner mismatch distributions for the real-bias-core variant on tt/ss; see the monte_carlo block. Numbers are PROPOSALS for a follow-on DR-003 amendment; spec/ is not edited and nothing here relaxes the ratified spec.
- **Variant**: `real-bias-core` -- SECOND, separately-reported variant: the real design/bias_core drives IBIAS, VREF and BIAS_OK.
- **Bias treatment**: REAL bias_core (design/netlist/bias_core.spice) on the same VDD supplies IBIAS, VREF and BIAS_OK, so the actual VREF(P,T,VDD) and delivered IBIAS move the edges. Never mixed with the ideal-bias table; shows how far the real reference dependence displaces the thresholds.
- **PDK**: sky130A @ open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (matches sim/pdk.json pin); models `$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice (fleet: models.pdk=sky130A, models.lib=libs.tech/combined/sky130.lib.spice)`
- **Tools**: ngspice-47 : Circuit level simulation program (host; the grid ran on the fleet); XSCHEM V3.4.7; Linux 7.0.0-1017-aws x86_64
- **Repo state**: `c591b93b` on `feature/issue-455` (clean working tree)
- **Fleet runner**: klt `0.9.0` / `ngspice-47` (client klt `klt 0.9.3.dev2575+g6bd18bbc8637`); client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used
- **Corner axis**: `mc` (mismatch Monte Carlo supplement, issue #348) -- one request per (process, temperature), process sections `tt_mm, ss_mm, ff_mm, sf_mm, fs_mm` (local mismatch only, never MC_PR_SWITCH global process MC), temperature -40 C, 27 C, 125 C; VDD is the swept variable (0 -> 3.63 V -> 0), no separate supply axis, at the primary 100 V/s only.
- **Statistical convention**: Per corner: mean and sample sigma (Bessel, n-1) of VPOR-up, VPOR-down and hysteresis over the valid Monte Carlo samples; hysteresis is computed PER SAMPLE (VPOR-up - VPOR-down of ONE realisation), never combined from the two marginal sigmas (comparator offset moves both edges of one realisation in the same direction, so the marginal combination overstates the hysteresis spread). The statistical resolution of a corner's sigma is stated as 1/sqrt(2(N_valid - 1)) of its valid N (16.2% at N = 20). Samples graded no_transition, multiple_transitions, unresolved or wrong_direction are excluded AND counted, never silently dropped; an all-invalid corner renders a three-state NO-RESULT, never sigma = 0. NOT sampled: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard (the MC points are unguarded), the ideal-bias variant, the ff/sf/fs sections, the ll/hh passive-skew axis, and post-layout parasitics. Temperatures draw INDEPENDENT realisation sets (one transient per temperature, one realisation set per request), so per-corner statistics are valid and NO per-sample temperature-drift or temperature-correlation claim is made.

## Request sizing and seeds (why this grid cannot be bigger)
- One klt sim request per (process, temperature) = 6 requests, N = 20 mismatch samples each, at the primary 100 V/s rate. Sizing arithmetic: the measured worst-corner cost of the real-bias-core 100 V/s grid is 142 s (corners/20261009-054331-79eebd4-real-bias-core/r100/klt-report.json, per-corner runtime_s; the 15-corner request summed to 1924 s), so one request is 20 x 142 s = 2840 s of serial fleet wall clock, 21% under the fleet's 3600 s per-job ceiling; N = 24 would sit at 3408 s inside the same ceiling and N = 20 is the recorded choice with the larger headroom (the sigma resolution at N = 20 is 16.2%). Folding the three temperatures into one request would be 60 x 142 s = 8520 s -> batch_job_timeout, the exact failure sim/temp-core-accuracy-mc recorded for its first 3000-unit requests.
- Seed offsets: Seed for request k = seed + k, k = 1..6 in (process, temperature) order: tt/-40C -> 20261115, tt/27C -> 20261116, tt/125C -> 20261117, ss/-40C -> 20261118, ss/27C -> 20261119, ss/125C -> 20261120. klt derives each sample's seed from the corner index (0 inside every one-corner request here), so a shared base seed across the six requests would re-draw the SAME realisations in each; the distinct offsets keep the six realisation sets independent. Each sample's own derived seed is recorded per sample in the record.

## Fleet submissions (one request per (process, temperature))
| request | N | seed (base + offset) | outcome | job id | runner klt | state | submitted at commit | refused earlier attempts |
|---|---|---|---|---|---|---|---|---|
| tt/-40C | 20 | 20261202 (20261201 + 1) | error | klt-sim-883da65119ef | 0.9.0 | failed | 50e1d37f (clean) | 0 |
| tt/27C | 20 | 20261203 (20261201 + 2) | pass | klt-sim-59039ee9a448 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| tt/125C | 20 | 20261204 (20261201 + 3) | pass | klt-sim-6664d3dc4580 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| ss/-40C | 20 | 20261205 (20261201 + 4) | pass | klt-sim-78bab87d8b76 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| ss/27C | 20 | 20261206 (20261201 + 5) | pass | klt-sim-22231c24df2d | 0.9.0 | done | 50e1d37f (clean) | 0 |
| ss/125C | 20 | 20261207 (20261201 + 6) | pass | klt-sim-d2bd74a95fb0 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| ff/-40C | 20 | 20261208 (20261201 + 7) | error | klt-sim-706b9909f427 | 0.9.0 | failed | 50e1d37f (clean) | 0 |
| ff/27C | 20 | 20261209 (20261201 + 8) | pass | klt-sim-840e20ed80a4 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| ff/125C | 20 | 20261210 (20261201 + 9) | pass | klt-sim-7deecb9b2aa2 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| sf/-40C | 20 | 20261211 (20261201 + 10) | pass | klt-sim-c0de828c00a5 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| sf/27C | 20 | 20261212 (20261201 + 11) | pass | klt-sim-32b8ce444b9f | 0.9.0 | done | 50e1d37f (clean) | 0 |
| sf/125C | 20 | 20261213 (20261201 + 12) | pass | klt-sim-1abb54a93960 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| fs/-40C | 20 | 20261214 (20261201 + 13) | error | klt-sim-275cfc92bb10 | 0.9.0 | failed | 50e1d37f (clean) | 0 |
| fs/27C | 20 | 20261215 (20261201 + 14) | pass | klt-sim-4d15cc9b1da2 | 0.9.0 | done | 50e1d37f (clean) | 0 |
| fs/125C | 20 | 20261216 (20261201 + 15) | pass | klt-sim-786ed7575d19 | 0.9.0 | done | 50e1d37f (clean) | 0 |

## Per-corner mismatch distributions (N = 20 samples per corner, Bessel (n-1) sigmas)
Hysteresis is per sample (VPOR-up - VPOR-down of ONE realisation). `resolution` is the statistical resolution of that corner's sigma, 1/sqrt(2(N-1)) of its valid N -- the number a future amendment must quote with any sigma from this table.
| corner | N valid/N run | VPOR-up mean ± sigma (V) | VPOR-down mean ± sigma (V) | hysteresis mean ± sigma (mV) | sigma resolution | excluded (of N) |
|---|---|---|---|---|---|---|
| tt/-40C | 19/20 | 2.7464 ± 0.0975 | 2.5883 ± 0.0930 | 158.1 ± 4.6 | 16.7% | 1 |
| tt/27C | 20/20 | 2.7327 ± 0.0971 | 2.5759 ± 0.0921 | 156.8 ± 5.0 | 16.2% | 0 (unconditional) |
| tt/125C | 20/20 | 2.6657 ± 0.1203 | 2.5171 ± 0.1151 | 148.6 ± 5.3 | 16.2% | 0 (unconditional) |
| ss/-40C | 19/20 | 2.7088 ± 0.1001 | 2.5527 ± 0.0949 | 156.1 ± 5.3 | 16.7% | 1 |
| ss/27C | 20/20 | 2.7115 ± 0.1695 | 2.5556 ± 0.1607 | 155.9 ± 8.9 | 16.2% | 0 (unconditional) |
| ss/125C | 20/20 | 2.7133 ± 0.1505 | 2.5603 ± 0.1435 | 152.9 ± 7.0 | 16.2% | 0 (unconditional) |
| ff/-40C | 17/20 | 2.7201 ± 0.1247 | 2.5633 ± 0.1187 | 156.8 ± 6.2 | 17.7% | 3 |
| ff/27C | 20/20 | 2.6834 ± 0.1041 | 2.5298 ± 0.0992 | 153.6 ± 5.0 | 16.2% | 0 (unconditional) |
| ff/125C | 20/20 | 2.7301 ± 0.1437 | 2.5816 ± 0.1374 | 148.5 ± 6.4 | 16.2% | 0 (unconditional) |
| sf/-40C | 19/20 | 2.6696 ± 0.0799 | 2.5155 ± 0.0757 | 154.1 ± 4.5 | 16.7% | 1 |
| sf/27C | 20/20 | 2.7246 ± 0.1622 | 2.5696 ± 0.1544 | 155.0 ± 7.9 | 16.2% | 0 (unconditional) |
| sf/125C | 20/20 | 2.7119 ± 0.0741 | 2.5658 ± 0.0711 | 146.1 ± 3.2 | 16.2% | 0 (unconditional) |
| fs/-40C | 17/20 | 2.6994 ± 0.0942 | 2.5437 ± 0.0898 | 155.7 ± 4.6 | 17.7% | 3 |
| fs/27C | 20/20 | 2.7459 ± 0.1050 | 2.5886 ± 0.0999 | 157.4 ± 5.2 | 16.2% | 0 (unconditional) |
| fs/125C | 20/20 | 2.7392 ± 0.1331 | 2.5850 ± 0.1266 | 154.3 ± 6.7 | 16.2% | 0 (unconditional) |

`unconditional` in the last column marks corners where **every** run sample carried both edges (0 exclusions): the mean/sigma of that corner are over ALL N run samples, not a releasing subset (issue #455 acceptance: unconditional sigmas, stated as such rather than inferred from the N valid/N run column).

### Excluded samples (counted, never silently dropped)
| corner | sample | reason |
|---|---|---|
| tt/-40C | mc14 | no waveform retrieved |
| ss/-40C | mc14 | NO_RESULT (up:multiple_transitions) |
| ff/-40C | mc6 | no waveform retrieved |
| ff/-40C | mc13 | no waveform retrieved |
| ff/-40C | mc18 | no waveform retrieved |
| sf/-40C | mc16 | NO_RESULT (up:multiple_transitions) |
| fs/-40C | mc1 | no waveform retrieved |
| fs/-40C | mc13 | no waveform retrieved |
| fs/-40C | mc18 | no waveform retrieved |

## Statistical disclosures (stated, not hidden)
- **NOT a spec claim.** This record supplies a distribution as evidence; it proposes no threshold. `spec/` is untouched and DR-004 is not edited.
- **Independent realisation sets per temperature**: each temperature is its own transient run and its own request, so temperatures draw independent mismatch realisations. Per-corner statistics are valid; this record makes NO per-sample temperature-drift or temperature-correlation claim.
- **Unguarded points**: the MC grid runs the primary 100 V/s rate only, WITHOUT the half-rate quasi-staticity guard. That guard is what makes the corner-matrix results quasi-static evidence; the MC points inherit the rate choice the nominal campaign established 15/15 at every corner and are disclosed as unguarded.
- **Not sampled**: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard, the ideal-bias variant, the ll/hh passive-skew axis, post-layout parasitics, and the ff/sf/fs process sections.

## Margin context (evidence toward a possible future amendment; no proposal)
DR-004's margin `2.97 V - max(VPOR-up)` = +257 mV (real-bias-core, ss, 27 C) is a CORNER number with no sigma attached; the distributions below put a mismatch spread beside it. This is evidence toward a possible future amendment of that recommendation. It is NOT a spec claim: no threshold is proposed or ratified here, `spec/` is untouched and DR-004 is not edited.
Beside it: the ss/27 C mismatch distribution of VPOR-up is 2.7115 ± 0.1695 V over N = 20 (sigma resolution 16.2%). No number here amends or replaces DR-004's corner margin.

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
- netlist_snapshots: `sim/por-comparator-thresholds/netlist-snapshots/20261121-115035-c591b93b-real-bias-core-mismatch-mc/`
- artifact_manifest: `manifests/artifacts/por-comparator-thresholds-20261121-115035-c591b93b-real-bias-core-mismatch-mc.manifest.json`
- artifact_summary: `manifests/artifacts/por-comparator-thresholds-20261121-115035-c591b93b-real-bias-core-mismatch-mc.summary.md`
- json: `sim/por-comparator-thresholds/records/20261121-115035-c591b93b-real-bias-core-mismatch-mc.json`
- record: `sim/por-comparator-thresholds/records/20261121-115035-c591b93b-real-bias-core-mismatch-mc.md`
- **Timestamp / author**: 2026-11-21T11:50:35Z, 313063438+loom-fleet-dispatch[bot]@users.noreply.github.com
- **Supersedes**: (none)

Written by `sim/por-comparator-thresholds/run_thresholds_campaign.py run --axis mc`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).
