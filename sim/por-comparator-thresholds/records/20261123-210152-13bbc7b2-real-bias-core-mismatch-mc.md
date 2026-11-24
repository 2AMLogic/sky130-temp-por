# Record 20261123-210152-13bbc7b2-real-bias-core-mismatch-mc

- **Record ID**: 20261123-210152-13bbc7b2-real-bias-core-mismatch-mc
- **Experiment**: `por-comparator-thresholds` — por_comparator VPOR-up / VPOR-down / hysteresis over process x temperature (quasi-static VDD sweep)
- **Claim**: Issue #102 -- NOT a spec claim. Evidence for DR-003 rows 4/5 ([TBD-2] VPOR-up/VPOR-down, [TBD-3] hysteresis): records, for the unchanged design/por_comparator.sch, the VDD at which POR_RAW changes state on a quasi-static constant-dVDD/dt UP sweep (VPOR-up) and DOWN sweep (VPOR-down), their difference (hysteresis), and the margin of VPOR-up against the DR-001 2.97 V low rail, across {tt, ss, ff, sf, fs} x {-40, 27, 125 C}. Each primary sweep rate is paired with a half-rate quasi-staticity guard. A mismatch Monte Carlo supplement (run --axis mc, issue #348) adds per-corner mismatch distributions for the real-bias-core variant on tt/ss; see the monte_carlo block. Numbers are PROPOSALS for a follow-on DR-003 amendment; spec/ is not edited and nothing here relaxes the ratified spec.
- **Variant**: `real-bias-core` -- SECOND, separately-reported variant: the real design/bias_core drives IBIAS, VREF and BIAS_OK.
- **Bias treatment**: REAL bias_core (design/netlist/bias_core.spice) on the same VDD supplies IBIAS, VREF and BIAS_OK, so the actual VREF(P,T,VDD) and delivered IBIAS move the edges. Never mixed with the ideal-bias table; shows how far the real reference dependence displaces the thresholds.
- **PDK**: sky130A @ open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (matches sim/pdk.json pin); models `$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice (fleet: models.pdk=sky130A, models.lib=libs.tech/combined/sky130.lib.spice)`
- **Tools**: ngspice-47 : Circuit level simulation program (host; the grid ran on the fleet); XSCHEM V3.4.7; Linux 6.17.0-1019-aws x86_64
- **Repo state**: `13bbc7b2` on `feature/issue-474` (clean working tree)
- **Fleet runner**: klt `0.9.0` / `ngspice-47` (client klt `klt 0.9.3.dev4224+gcc049d4d9637`); client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used
- **Corner axis**: `mc` (mismatch Monte Carlo supplement, issue #348) -- one request per (process, temperature), process sections `tt_mm, ss_mm` (local mismatch only, never MC_PR_SWITCH global process MC), temperature -40 C, 27 C, 125 C; VDD is the swept variable (0 -> 3.63 V -> 0), no separate supply axis, at the primary 100 V/s only.
- **Statistical convention**: Per corner: mean and sample sigma (Bessel, n-1) of VPOR-up, VPOR-down and hysteresis over the valid Monte Carlo samples; hysteresis is computed PER SAMPLE (VPOR-up - VPOR-down of ONE realisation), never combined from the two marginal sigmas (comparator offset moves both edges of one realisation in the same direction, so the marginal combination overstates the hysteresis spread). The statistical resolution of a corner's sigma is stated as 1/sqrt(2(N_valid - 1)) of its valid N (16.2% at N = 20). Samples graded no_transition, multiple_transitions, unresolved or wrong_direction are excluded AND counted, never silently dropped; an all-invalid corner renders a three-state NO-RESULT, never sigma = 0. NOT sampled: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard (the MC points are unguarded), the ideal-bias variant, the ff/sf/fs sections, the ll/hh passive-skew axis, and post-layout parasitics. Temperatures draw INDEPENDENT realisation sets (one transient per temperature, one realisation set per request), so per-corner statistics are valid and NO per-sample temperature-drift or temperature-correlation claim is made.

## Request sizing and seeds (why this grid cannot be bigger)
- One klt sim request per (process, temperature) = 6 requests, N = 20 mismatch samples each, at the primary 100 V/s rate. Sizing arithmetic: the measured worst-corner cost of the real-bias-core 100 V/s grid is 142 s (corners/20261009-054331-79eebd4-real-bias-core/r100/klt-report.json, per-corner runtime_s; the 15-corner request summed to 1924 s), so one request is 20 x 142 s = 2840 s of serial fleet wall clock, 21% under the fleet's 3600 s per-job ceiling; N = 24 would sit at 3408 s inside the same ceiling and N = 20 is the recorded choice with the larger headroom (the sigma resolution at N = 20 is 16.2%). Folding the three temperatures into one request would be 60 x 142 s = 8520 s -> batch_job_timeout, the exact failure sim/temp-core-accuracy-mc recorded for its first 3000-unit requests.
- Seed offsets: Seed for request k = seed + k, k = 1..6 in (process, temperature) order: tt/-40C -> 20261115, tt/27C -> 20261116, tt/125C -> 20261117, ss/-40C -> 20261118, ss/27C -> 20261119, ss/125C -> 20261120. klt derives each sample's seed from the corner index (0 inside every one-corner request here), so a shared base seed across the six requests would re-draw the SAME realisations in each; the distinct offsets keep the six realisation sets independent. Each sample's own derived seed is recorded per sample in the record.

## Fleet submissions (one request per (process, temperature))
| request | N | seed (base + offset) | outcome | job id | runner klt | state | submitted at commit | refused earlier attempts |
|---|---|---|---|---|---|---|---|---|
| tt/-40C | 20 | 20261115 (20261114 + 1) | pass | klt-sim-738f6d5f31c1 | 0.9.0 | done | 13bbc7b2 (clean) | 0 |
| tt/27C | 20 | 20261116 (20261114 + 2) | pass | klt-sim-4193df567848 | 0.9.0 | done | 13bbc7b2 (clean) | 0 |
| tt/125C | 20 | 20261117 (20261114 + 3) | pass | klt-sim-8315eba460ad | 0.9.0 | done | 13bbc7b2 (clean) | 0 |
| ss/-40C | 20 | 20261118 (20261114 + 4) | pass | klt-sim-fa44b849d745 | 0.9.0 | done | 13bbc7b2 (clean) | 0 |
| ss/27C | 20 | 20261119 (20261114 + 5) | pass | klt-sim-94f2c460e28b | 0.9.0 | done | 13bbc7b2 (clean) | 0 |
| ss/125C | 20 | 20261120 (20261114 + 6) | pass | klt-sim-ec45126e03cd | 0.9.0 | done | 13bbc7b2 (clean) | 0 |

## Per-corner mismatch distributions (N = 20 samples per corner, Bessel (n-1) sigmas)
Hysteresis is per sample (VPOR-up - VPOR-down of ONE realisation). `resolution` is the statistical resolution of that corner's sigma, 1/sqrt(2(N-1)) of its valid N -- the number a future amendment must quote with any sigma from this table.
| corner | N valid/N run | VPOR-up mean ± sigma (V) | VPOR-down mean ± sigma (V) | hysteresis mean ± sigma (mV) | sigma resolution | excluded (of N) |
|---|---|---|---|---|---|---|
| tt/-40C | 20/20 | 2.7688 ± 0.1300 | 2.6096 ± 0.1235 | 159.3 ± 6.6 | 16.2% | 0 (unconditional) |
| tt/27C | 20/20 | 2.6928 ± 0.1246 | 2.5382 ± 0.1187 | 154.5 ± 6.0 | 16.2% | 0 (unconditional) |
| tt/125C | 20/20 | 2.7128 ± 0.1473 | 2.5623 ± 0.1403 | 150.5 ± 7.1 | 16.2% | 0 (unconditional) |
| ss/-40C | 20/20 | 2.7380 ± 0.1305 | 2.5800 ± 0.1240 | 158.0 ± 6.6 | 16.2% | 0 (unconditional) |
| ss/27C | 20/20 | 2.7305 ± 0.0870 | 2.5740 ± 0.0828 | 156.5 ± 4.4 | 16.2% | 0 (unconditional) |
| ss/125C | 20/20 | 2.7382 ± 0.1384 | 2.5844 ± 0.1321 | 153.8 ± 6.4 | 16.2% | 0 (unconditional) |

`unconditional` in the last column marks corners where **every** run sample carried both edges (0 exclusions): the mean/sigma of that corner are over ALL N run samples, not a releasing subset (issue #455 acceptance: unconditional sigmas, stated as such rather than inferred from the N valid/N run column).

## Reproduction of record 20261121-114636-63e27cba-real-bias-core-mismatch-mc (seed-for-seed)
**NOT reproduced.** 120 samples across 6 corner entries compared against the predecessor record by (process, temperature, sample index): derived seeds all match, pass/fail pattern (valid flag + exclusion reason) DIFFERS, extracted values EXCEED the stated 0.1 mV tolerance (max absolute delta 26.593 mV). A non-reproduction is stated here, never quietly re-baselined: the predecessor record stands as committed evidence.

Mismatching samples (118, listing first 10):

| corner | sample | field | old | new |
|---|---|---|---|---|
| tt/-40C | mc0 | vup | 2.7150476326741595 | 2.7163696149881953 |
| tt/-40C | mc0 | vdn | 2.558045751081402 | 2.5576292084382133 |
| tt/-40C | mc0 | hys | 0.15700188159275763 | 0.158740406549982 |
| tt/-40C | mc0 | vref_max_v | 1.267352361019135 | 1.266132910613825 |
| tt/-40C | mc1 | vup | 2.787165448628018 | 2.7883698910859 |
| tt/-40C | mc1 | hys | 0.15857282472434786 | 0.1598653867966311 |
| tt/-40C | mc1 | vref_max_v | 1.318913952524859 | 1.31876595845255 |
| tt/-40C | mc2 | valid | False | True |
| tt/-40C | mc2 | reason | no waveform retrieved | None |
| tt/-40C | mc2 | vup | None | 3.038370067697245 |
| tt/-40C | mc2 | vdn | None | 2.8661295776190143 |
| tt/-40C | mc2 | hys | None | 0.17224049007823083 |
| tt/-40C | mc2 | vref_max_v | None | 1.419286427522732 |
| tt/-40C | mc3 | vup | 2.7230476337313587 | 2.7223700336666568 |
| tt/-40C | mc3 | vdn | 2.5669667943580787 | 2.5673795019659416 |
| tt/-40C | mc3 | hys | 0.15608083937328 | 0.1549905317007152 |
| tt/-40C | mc3 | vref_max_v | 1.289907305449433 | 1.28953728327831 |
| tt/-40C | mc4 | vup | 2.583047613888716 | 2.5823700126449274 |
| tt/-40C | mc4 | hys | 0.14943936492535403 | 0.14874082418413348 |
| tt/-40C | mc4 | vref_max_v | 1.221818555923022 | 1.219403394350441 |
| tt/-40C | mc5 | vup | 2.7670575031973375 | 2.767188242782584 |
| tt/-40C | mc5 | vdn | 2.608941752512856 | 2.609467640489966 |
| tt/-40C | mc5 | hys | 0.15811575068448125 | 0.15772060229261786 |
| tt/-40C | mc5 | vref_max_v | 1.335222370453042 | 1.316098498195996 |
| tt/-40C | mc6 | valid | False | True |
| tt/-40C | mc6 | reason | no waveform retrieved | None |
| tt/-40C | mc6 | vup | None | 2.806342990101377 |
| tt/-40C | mc6 | vdn | None | 2.644317093845991 |
| tt/-40C | mc6 | hys | None | 0.16202589625538621 |
| tt/-40C | mc6 | vref_max_v | None | 1.336380909966032 |
| tt/-40C | mc7 | vup | 2.5883959932637204 | 2.588154704293512 |
| tt/-40C | mc7 | vdn | 2.43779111633887 | 2.438897117169115 |
| tt/-40C | mc7 | hys | 0.15060487692485047 | 0.14925758712439663 |
| tt/-40C | mc7 | vref_max_v | 1.198935245387371 | 1.213682786741233 |
| tt/-40C | mc8 | vup | 2.843047649174936 | 2.8424021634001053 |
| tt/-40C | mc8 | hys | 0.16409109661892485 | 0.16342881859782699 |
| tt/-40C | mc8 | vref_max_v | 1.322255816447532 | 1.327536914698229 |
| tt/-40C | mc9 | vup | 2.742969656811211 | 2.741513677910587 |
| tt/-40C | mc9 | vdn | 2.5849516125417358 | 2.583944197250345 |
| tt/-40C | mc9 | hys | 0.1580180442694754 | 0.1575694806602419 |
| tt/-40C | mc9 | vref_max_v | 1.278817526067221 | 1.279515652686855 |

## Statistical disclosures (stated, not hidden)
- **NOT a spec claim.** This record supplies a distribution as evidence; it proposes no threshold. `spec/` is untouched and DR-004 is not edited.
- **Independent realisation sets per temperature**: each temperature is its own transient run and its own request, so temperatures draw independent mismatch realisations. Per-corner statistics are valid; this record makes NO per-sample temperature-drift or temperature-correlation claim.
- **Unguarded points**: the MC grid runs the primary 100 V/s rate only, WITHOUT the half-rate quasi-staticity guard. That guard is what makes the corner-matrix results quasi-static evidence; the MC points inherit the rate choice the nominal campaign established 15/15 at every corner and are disclosed as unguarded.
- **Not sampled**: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard, the ideal-bias variant, the ll/hh passive-skew axis, post-layout parasitics, and the ff/sf/fs process sections.

## Margin context (evidence toward a possible future amendment; no proposal)
DR-004's margin `2.97 V - max(VPOR-up)` = +257 mV (real-bias-core, ss, 27 C) is a CORNER number with no sigma attached; the distributions below put a mismatch spread beside it. This is evidence toward a possible future amendment of that recommendation. It is NOT a spec claim: no threshold is proposed or ratified here, `spec/` is untouched and DR-004 is not edited.
Beside it: the ss/27 C mismatch distribution of VPOR-up is 2.7305 ± 0.0870 V over N = 20 (sigma resolution 16.2%). No number here amends or replaces DR-004's corner margin.

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
- netlist_snapshots: `sim/por-comparator-thresholds/netlist-snapshots/20261123-210152-13bbc7b2-real-bias-core-mismatch-mc/`
- artifact_manifest: `manifests/artifacts/por-comparator-thresholds-20261123-210152-13bbc7b2-real-bias-core-mismatch-mc.manifest.json`
- artifact_summary: `manifests/artifacts/por-comparator-thresholds-20261123-210152-13bbc7b2-real-bias-core-mismatch-mc.summary.md`
- json: `sim/por-comparator-thresholds/records/20261123-210152-13bbc7b2-real-bias-core-mismatch-mc.json`
- record: `sim/por-comparator-thresholds/records/20261123-210152-13bbc7b2-real-bias-core-mismatch-mc.md`
- **Timestamp / author**: 2026-11-23T21:01:52Z, loom-fleet-dispatch
- **Supersedes**: (none)

Written by `sim/por-comparator-thresholds/run_thresholds_campaign.py run --axis mc`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).
