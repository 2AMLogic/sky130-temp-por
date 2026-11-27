# Work Log

Chronological record of recently merged pull requests and closed issues. This file is maintained by the Loom Guide role.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)
- [2026-08](work_log/WORK_LOG_2026-08.md)

### 2026-11-27

- **Issue #544** (closed): Remove the unconditional solver-dependence claim from the bias-core verdict
- **PR #545**: fix(sim): make the op-branch verdict defer to solver_dependence

### 2026-11-26

- **Issue #529** (closed): Enforce append-only CI checks for layout PEX records
- **PR #533**: fix: extend the append-only CI check to layout PEX records
- **Issue #539** (closed): Make the corner-run batch and deck-transport klt fixtures work with a noexec TMPDIR
- **PR #542**: test(sim): move the corner-run and deck-transport klt stubs into tracked fixtures
- **Issue #538** (closed): Stop generating a klt executable in the evidence-store self-test’s temporary directory
- **PR #540**: test(sim): move the evidence-store fake klt into a tracked fixture
- **PR #531**: fix(sim): keep klt's stderr for an unusable deck-list report
- **Issue #528** (closed): Consolidate the three deck-list report checks so malformed output preserves fleet diagnostics
- **PR #534**: fix: report klt stdout that is not a JSON object as NO-JSON
- **PR #525**: chore: ignore daemon-written .loom/account-ranking.codex state
- **Issue #530** (closed): submit_prepared and load_request_report crash on klt stdout that is JSON but not an object
- **Issue #523** (closed): gitignore: daemon-written .loom/account-ranking.* state makes check-main-clean.sh exit 3 spuriously
- **PR #527**: docs: record per-rail PEX ramp grid fleet run vs baseline
- **PR #526**: fix: measure PEX reset release at 80% of each final supply
- **PR #519**: docs: attribute the 51 block-level pex grid error rows with single-corner repros

### 2026-11-25

- **PR #518**: docs: record post-#501 block-level pex grid result in roadmap item 7

### 2026-11-24

- **PR #476**: docs: state klayout-tools#6025 as closed in bias-core and output-chain READMEs
- **Issue #470** (closed): Three cell READMEs still call klayout-tools#6025 open (outside #454's AC-6 scope)
- **PR #516**: docs: re-quote stale extract cards in two bias_core leaf READMEs
- **PR #512**: fix(layout): upper-case the bias_core family's net labels so the flat pex netlist loads
- **PR #511**: fix(sim): re-scope spiceinit provenance, group helper inlining, name sparse-grid cross product
- **PR #510**: fix(layout): re-render drc/extract evidence for 6 leaf cells onto the released sky130 deck
- **PR #509**: docs: quantify E8 VPOR-up mismatch tail vs the 2.97 V rail and disposition it as the recorded sigma's expected tail
- **PR #508**: fix(sim): sync early-assert manifest prose and probe grid lookup
- **PR #507**: docs(layout): drop unrecorded probe figure from bias_core pex README
- **Issue #515** (closed): corner-run.py:435 docstring says "both backends" then "the runner" — scope the ngspice_init clause to the fleet runner on the next edit of this file
- **Issue #514** (closed): layout: two leaf READMEs quote stale extract cards (bias_core_settle_flag M$10, bias_core_passives R$3)
- **Issue #506** (closed): sim: the pre-flight local probe figure cited in layout/bias_core/pex/README.md has no in-repo record
- **Issue #502** (closed): 9 cells now record LVS against the released deck while their DRC/extract evidence still cites the unreleased one
- **Issue #501** (closed): temp_por_top: make composed-sibling net labels case-consistent so klt pex output is simulatable
- **Issue #500** (closed): sim/por-bias-ok-early-assert: sync stale pre-XMOKA manifest prose and minor runner hygiene
- **Issue #497** (closed): corner-run.py no longer stages sim/spiceinit: stale provenance docs and a dead constant
- **Issue #494** (closed): por-comparator-thresholds: VPOR-up exceeds the DR-001 2.97 V low rail on 4 of 120 paired and 5 of 300 fresh mismatch draws
- **PR #505**: feat(sim): measure POR thresholds against extracted bias_core parasitics
- **Issue #487** (closed): sim: measure VPOR up/down/hysteresis with the extracted bias_core against the re-rendered layout
- **Issue #490** (closed): docs: four stale "153/153" LVS device counts after the #473 re-render landed 154/154
- **Issue #473** (closed): layout: re-implement bias_core_settle_flag (and re-assembly bias_core / temp_por_top) after the #455 OK-detector schematic changes
- **PR #488**: layout: re-render OK-detector leaf and assemblies for the landed #455 schematic
- **PR #498**: sim: deterministic forced-offset reproduction of early BIAS_OK / POR_RAW pulse
- **PR #496**: docs(layout): make generated .ref.spice banner describe build_reference accurately
- **Issue #495** (closed): bias_core OK detector: early BIAS_OK assertion glitches POR_RAW at VDD~1.82 V on cold mismatch draws (uncorrected, now masked by the uic startup)
- **PR #491**: sim: start mismatch-MC transient from the all-zero state; 120/120 and 300/300 valid
- **PR #485**: feat: run corner-run grids through klt sim on the fleet, local only for single points
- **Issue #484** (closed): compose-cell.py's generated-reference provenance banner understates the transformations (and now names a removed one)
- **PR #477**: feat: add block-level klt pex evidence for temp_por_top (cannot-grade, net-label case collision)
- **Issue #474** (closed): Resolve cold-mismatch BIAS_OK chatter and initial-timepoint transient aborts after #455
- **Issue #327** (closed): corner-run.py: run full grids on the fleet and support all four rejected manifests

### 2026-11-23

- **Issue #493** (closed): Attestation item-9 pins 13 hot sim runner sources, so concurrent sim PRs collide in a conflict only a local_only re-attest can resolve
- **PR #492**: test(sim): exercise render_mc_md in the MC 'Not sampled' bullet test
- **Issue #489** (closed): test_mc_statistics: render_mc_md 'Not sampled' bullet has no real test (tautological assertion)
- **PR #486**: fix(sim): derive MC record prose from effective grid overrides
- **PR #483**: refactor(layout): retire unused lvs.params, lvs.drop_kwargs and block from_stage
- **PR #482**: fix: store falsy supersedes in new sim records instead of the (none) sentinel
- **Issue #481** (closed): por-comparator-thresholds: --axis mc record renders manifest prose for the un-overridden grid when --mc-process/--mc-seed are used
- **PR #475**: design+sim: fix bias_core OK-detector mismatch margin and chatter; 0 non-releasing mismatch samples (issue #455)
- **Issue #455** (closed): bias_core OK-detector: BIAS_OK never asserts in 38 of 120 mismatch samples, so reset never releases; find the device and fix the design
- **Issue #353** (closed): Collapse the four `supersedes` encodings into one: the display placeholder `(none)` is load-bearing machine state in two runners
- **Issue #321** (closed): Remove undeclared descriptor keys from compose-cell.py (lvs.params, lvs.drop_kwargs, blocks[].from_stage): no committed cell recipe uses them

### 2026-11-21

- **PR #466**: refactor(sim): drop run_solver_sweep's interp() duplicate of sim_common.interp_at
- **PR #465**: fix: reset the supply-ramp cross-check for each variant
- **Issue #463** (closed): Replace run_solver_sweep.interp with sim_common.interp_at (#170 residue)
- **Issue #457** (closed): Scope the supply-ramp cross-check to its variant so the next record cannot inherit it
- **PR #469**: docs: record passing klt pex re-run at the 0.9.2 pin; correct closed klayout-tools#6025 status

### 2026-11-20

- **PR #464**: fix(layout): recompose temp_por_top onto the massist leaf stream, retire the XMASSIST LVS exclusion
- **Issue #453** (closed): Re-compose temp_por_top from the current por_output_chain stream: retire the XMASSIST LVS exclusion and re-run DRC/LVS/ERC at klt 0.9.2

### 2026-11-19

- **PR #448**: fix: compute pnp-mismatch signal ratio once so a zero mean records a failed check
- **Issue #446** (closed): Compute the PNP mismatch signal ratio once so a zero mean records a failed check

### 2026-11-18

- **PR #444**: docs(roadmap): move declined #308 item to Not planned and reconcile decided issues
- **PR #442**: docs: state the real blocker on the attest-layout replacement roadmap item
- **PR #440**: docs: fix stale claims that target-spec.md does not exist
- **PR #439**: refactor: drop inert capacity_wait_s parameter from submit_batch
- **PR #436**: ci: bump signoff klt pin to 0.9.2 and re-render manifests
- **PR #435**: spec: relocate ratified target-spec rows to spec/target-spec.md and pin them in item 10
- **PR #434**: refactor(sim): drop caller-side fleet concurrency-cap retry in favor of klt capacity_wait_s
- **Issue #443** (closed): docs/ROADMAP.md: the declined #308 item sits under ## Next, and line 119 still calls it undecided
- **Issue #441** (closed): docs/ROADMAP.md:75 names a satisfied klt-pin prerequisite for the attest-layout.py replacement (#308)
- **Issue #438** (closed): Six live docs still assert spec/target-spec.md does not exist (false after PR #435)
- **Issue #437** (closed): corner-run.py: submit_batch's capacity_wait_s parameter is inert after #314
- **Issue #433** (closed): Bump signoff-manifest CI pin klayout-tools 0.8.0 -> 0.9.x and re-render manifests
- **Issue #342** (closed): Guide's automated docs tick reds the signoff gate whenever it edits README.md (hashed in item-10's hygiene envelope)
- **Issue #314** (closed): Remove the caller-side fleet concurrency-cap retry (cap_retry): klt has waited this refusal out itself since 0.8.0
- **Issue #308** (closed): Replace layout/bin/attest-layout.py with klt signoff --attest 2 (native since klt 0.9.0; needs the CI pin bumped from 0.8.0)
- **PR #431**: ci: add the merge_group trigger and teach the append-only gate merge-group baselines
- **Issue #429** (closed): Merge queue: add the merge_group trigger and adapt the PR-metadata gates

### 2026-11-17

- **PR #427**: docs: cite real-bias-core corner envelope (22 mV, 16 mV tt/ss) in mismatch-MC comparisons
- **Issue #386** (closed): characterization-report/README: the '18 mV corner envelope' compared against the mismatch sigmas is the ideal-bias span, not real-bias-core's
- **PR #423**: chore(loom): resync installed Loom to v0.19.1306
- **PR #422**: feat(sim): keep the enable/clamp-path MC diagnostics; POR non-release mechanism established — bias_core BIAS_OK never asserts
- **Issue #401** (closed): por_comparator: 38 of 120 local-mismatch realisations never release POR_RAW, and the count is not the upper tail of the releasing distribution
- **PR #421**: docs: time-scope stale klt hvi-marker capability statements to their render pins
- **PR #419**: feat(layout): draw the native-Vt XMASSIST in por_output_chain; LVS match 34/34 with no exclusion
- **Issue #420** (closed): Stale tool-capability and blocker statements in layout/ and docs/ after klt grew the native-Vt (hvi+lvtn) flavour
- **Issue #97** (closed): Lay out por_output_chain as the next DRC/LVS-verified POR leaf

### 2026-11-16

- **PR #416**: test(sim): cover the tripwire's two live-fire paths -- a tripped marker and an accepted argv
- **PR #414**: fix: cmd_compare's append-only guard covers both record twins, pathfully, before grading
- **PR #413**: test(sim): put per-runner CLI probes behind a tripwire klt that refuses klt sim
- **PR #412**: docs: state the closed-corners/ exemption in the manifest byte-rule paragraph
- **PR #411**: ci: bound graded T1 count and check manifest pins against envelopes
- **PR #410**: test: retire pnp-mismatch's stale FIXTURE_SEEDS entry (Fixes #408)
- **PR #407**: test: make raise_statement fail loudly on long or unterminated raises
- **PR #385**: refactor(sim): route iq-top's classify_failure through sim_common.classify_error (one vocabulary for the klt timeout)
- **PR #378**: refactor(sim): route thresholds trace decimation through sim_common.decimate
- **Issue #415** (closed): test(sim): ship the two now-possible regression tests for the deck-transport tripwire
- **Issue #408** (closed): self-checks red on main since #395: run_pnp_mismatch.py regained real corpus coverage, so its FIXTURE_SEEDS entry is stale
- **Issue #403** (closed): sim/README.md: state the closed-corners/ exemption in the artifact-manifest byte-rule paragraph
- **Issue #402** (closed): run_accuracy_mc.py's record guard is a third wording #369's greps missed, and it only checks the .md
- **Issue #398** (closed): raise_statement() in test_pdk_pin.py silently truncates long raises and rejects bind-then-raise
- **Issue #389** (closed): CI cannot see a T1 signoff regression: nothing bounds t1_met_count or checks the manifest pin against the envelope's provenance.input.content_hash
- **Issue #371** (closed): iq-top: route the sixth classify_error copy through sim_common (10db1d54 residue; renamed classify_failure, two vocabularies for one klt timeout)
- **Issue #363** (closed): Tighten the capacity-wait CLI probe guard: cli() checks token presence, not that argparse rejects it
- **Issue #341** (closed): Route the fifth campaign's trace writer through sim_common.decimate, and delete the dead read_trace (1e17ab35 residue)
- **PR #406**: fix: repo-root-relative DR annotation paths; scope malformed-row check to DR rows
- **PR #400**: refactor: drop dead local assignments flagged by ruff F841
- **PR #395**: evidence: live pnp-mismatch record from store-routed runner (#325 acceptance step 6)
- **PR #390**: refactor(sim): route the last two hand-rolled append-only guards through refuse_existing
- **Issue #397** (closed): CI gate conflict: artifact-manifest byte rule vs closed append-only corners/ blocks store-routed re-runs
- **Issue #394** (closed): check_decision_record_index.py: wrong ::error annotation path, and malformed-row check applies to the whole README
- **Issue #391** (closed): Remove the four unused locals ruff F841 flags (the half of #361's residue it left behind)
- **Issue #369** (closed): Convert the last two hand-rolled append-only guards in sim/bin/ to sim_common.refuse_existing
- **Issue #335** (closed): Live verification: one real record from a store-routed runner (issue #325 acceptance step 6)
- **PR #379**: sim: mismatch Monte Carlo record and mode for the por_comparator thresholds (issue #348)
- **PR #352**: docs(layout): drop _klt_common.py's stale caller count and provenance claim
- **PR #392**: test: guard the one-definition pin-refusal invariant as source contract
- **PR #396**: test(sim): pin non-re-renderable records in an explicit, doubly-guarded registry
- **PR #357**: refactor(sim): dispatch write_wave_fixture on the .gz suffix and adopt it in the last two checkers
- **PR #381**: refactor(sim): render the fleet-PDK record sentence from one shared renderer
- **Issue #348** (closed): por-comparator-thresholds: mismatch Monte Carlo on VPOR up, VPOR down and hysteresis
- **Issue #344** (closed): Delete the false provenance narrative in _klt_common.py's docstring: three importers, not "one caller today", and README calls the same file a byte-for-byte port
- **Issue #388** (closed): No source-level guard test for the single-definition invariant #338 just established (pdk_mismatch_message)
- **Issue #367** (closed): Nine committed sim records cannot be re-rendered from their own .json twin (renderers resolve post-dating schema keys by hard key)
- **Issue #351** (closed): Route the last two checkers' wave-fixture writers through sim_common.write_wave_fixture (ea999aa7 residue; 345 KiB uncompressed in-tree)
- **Issue #368** (closed): Dedupe the fleet-PDK record sentence: one sim_common renderer, not six hand-assembled bridges

### 2026-11-15

- **PR #374**: feat(sim): first cell-level PVT record for por_output_chain, plus batch-submit capacity wait
- **PR #359**: refactor(sim): declare the fleet capacity-wait flag once, defaulting to the host rule
- **PR #393**: ci: guard the decision-record index in spec/README.md with a self-checking checker
- **PR #382**: chore(sim): remove the four unused imports ruff F401 flags
- **PR #387**: docs(roadmap): re-anchor the Now list to main @ 98a0d49c and state the re-anchor trigger
- **PR #355**: refactor(sim): route the last two PDK pin refusals through cr.pdk_mismatch_message
- **PR #377**: refactor(sim): rename iq-top's stride thinner decimate to thin_uniform
- **PR #372**: refactor(sim): route the thresholds per-point .log and error_class through sim_common
- **PR #354**: refactor(sim): build the deck-list record's batch provenance in sim_common, not twice
- **PR #373**: refactor(sim): drop dead boolean scaffolding from brownout/glitch checker stand-ins
- **PR #383**: refactor(census): make the sibling memo actually cache, drop dead run_census(cell_dir=) and the double cell.json parse
- **Issue #349** (closed): Add a cell-level testbench and PVT record for por_output_chain
- **Issue #339** (closed): Consolidate the fleet capacity-wait flag: one field, eleven CLI declarations, two names, nine defaulting it off
- **Issue #361** (closed): Remove the four unused imports ruff F401 flags: one 25e5f542 residue plus three never used in their file
- **Issue #362** (closed): docs/ROADMAP.md: re-anchor the Now list against current main and state what triggers a re-anchor
- **Issue #338** (closed): Route the last two PDK pin-mismatch messages through cr.pdk_mismatch_message (#292 residue, already drifted to pdk.variant)
- **Issue #356** (closed): iq-top: rename run_iq_campaign.decimate — the bare name is sim_common's change-triggered decimator everywhere else in sim/
- **Issue #365** (closed): por-comparator-thresholds: route the last inline point_log and error_class copies through sim_common (10db1d54 residue; the error_class copy cannot say `timeout`)
- **Issue #350** (closed): Consolidate the record's deck-list batch provenance block into sim_common (#297 residue: 45 identical lines in both bespoke runners)
- **Issue #334** (closed): Remove dead boolean scaffolding in the brownout/glitch synth stand-ins (`and False` guard, no-op `pass` branch, subsumed disjunct)
- **Issue #364** (closed): pad-island-census.py: three inert leftovers — a memo cache that never caches, an unused run_census(cell_dir=), and a double cell.json parse
- **PR #375**: docs(spec): index all seven decision records in spec/README with per-DR status table
- **Issue #346** (closed): Index DR-004, DR-005 and DR-007 in spec/README.md
- **PR #366**: refactor(sim): render every record's append-only trailer from one sim_common helper
- **Issue #337** (closed): Consolidate the duplicated record-markdown trailer into sim_common (10 renderers, 4 drifted footer texts)
- **PR #370**: docs(report): index the mirror-degeneration record and retire #86 as an open owner
- **Issue #347** (closed): Characterization report: cite the mirror-degeneration record and correct the #86 wording

### 2026-11-14

- **PR #345**: docs: roadmap as of 2026-11-13
- **PR #343**: feat(sim): derive a three-state fleet-PDK-vs-pin verdict in every runner's record
- **Issue #333** (closed): Compare the recorded fleet-runner PDK stamp with the sim/pdk.json pin (today it is recorded, never checked)
- **PR #336**: refactor(sim): route the last six runners through evidence_store and close corners/ to additions
- **Issue #325** (closed): Route the six remaining sim runners through evidence_store: they still commit raw corner bytes in-tree (1 MB added since adoption)
- **Issue #360** (closed): por-comparator-thresholds: adopt sim_common.decimate + write_gz_rows in run_thresholds_campaign.write_trace (the fifth, un-migrated trace writer)
- **Issue #358** (closed): run_glitch_campaign.py rides one flag for two retry mechanisms: the capacity wait is also the concurrency-cap poll
- **PR #332**: refactor(sim): read the fleet's PDK through one sim_common helper, not five
- **Issue #328** (closed): Share one fleet-PDK reader in sim_common: 3 private copies, and 3 runners record the client's PDK as fleet_pdk_report

### 2026-11-13

- **PR #330**: refactor(sim): submit the last two local ngspice grids through klt sim as deck-list requests
- **Issue #319** (closed): Remove the local ngspice grid launchers from run_op_branch.py and run_pnp_mismatch.py: submit through klt sim like the other runners
- **PR #320**: refactor(sim): share the campaign submit bootstrap across the nine fleet runners
- **Issue #307** (closed): Share the campaign cmd_run bootstrap in sim_common (9 copies; 3 runners submit from a dirty tree, 1 bypasses submit_prepared)
- **PR #326**: refactor(sim): one shared per-request report triage for the six campaign graders
- **Issue #322** (closed): Share the per-request report triage in sim_common (6 hand copies; 2 drop client_klt_version, 3 wordings for one failure)
- **PR #324**: fix(sim): grade the accuracy-MC `none` control against the expected corner grid
- **Issue #318** (closed): accuracy-MC `none` control: a process section with no report is absent from the corner count and cannot make the control NOT VERIFIED
- **PR #315**: fix(sim): derive accuracy-MC record PDK and fleet engine from the run
- **Issue #312** (closed): run_accuracy_mc.py writes a hardcoded open_pdks commit and a '?' ngspice fallback into its record header
- **PR #317**: fix(sim): grade the accuracy-MC `none` control three-state so an empty one cannot PASS
- **Issue #310** (closed): temp-core-accuracy-mc: negative control can PASS with zero compared samples; drop hardcoded none_max_sd_V and dead local
- **PR #316**: fix(sim): make load_corner_run() return the one registered corner_run module
- **Issue #304** (closed): Make load_corner_run() reuse the loaded module: drop three guards that still let corner-run.py load twice
- **PR #313**: fix(sim): derive the solver sweep's record PDK/Tools lines from the run
- **Issue #306** (closed): run_solver_sweep.py writes a hardcoded 'fleet runner klt 0.5.0' into record Tools lines
- **PR #311**: fix(manifests): walk list-valued evidence entries and object `file` refs in check-citations.py
- **Issue #302** (closed): check-citations.py silently skips list-valued manifest evidence entries (item 11)
- **PR #300**: refactor(sim): derive each record's fleet/host tool versions instead of hardcoding them
- **Issue #297** (closed): Share the record pdk/tools provenance block across fleet runners (7 copies; 4 hardcode stale tool versions)
- **PR #305**: feat(manifests): gate items 1 and 9 with klt's own local_only attest check
- **PR #301**: feat(manifests): re-hash attestation.checks[] files so source edits fail CI
- **Issue #299** (closed): signoff gate never re-hashes item 1 and item 9 attested files, so source edits silently stale the envelopes
- **PR #298**: fix(netlist): strip klt's klt-netlist-inputs provenance line in normalize()
- **Issue #295** (closed): design/netlist.py --check fails on main: committed netlists predate klt's klt-netlist-inputs provenance line
- **PR #296**: refactor(sim): hoist the attemptN reader, point_log and classify_error into sim_common
- **Issue #293** (closed): Consolidate six drifted attemptN readers (and point_log/classify_error) into sim_common
- **PR #294**: refactor(netlist): resolve the PDK through corner-run.py instead of a private copy
- **Issue #292** (closed): Dedupe PDK pin resolution: design/netlist.py re-implements corner-run.py's resolver (already drifted)
- **PR #290**: sim(glitch-top): fleet re-run of vdd_slew_v1.2_h0.0002_s200000 with lowered request timeout
- **Issue #181** (closed): glitch-top: re-run failed vdd_level request vdd_slew_v1.2_h0.0002_s200000 (45 ERROR points)

### 2026-11-11

- **PR #288**: chore: remove retired guard reproducer now covered upstream
- **Issue #191** (closed): Remove docs/guard-repro reproducer: stale, unreferenced test of a Loom-managed hook

### 2026-11-07

- **PR #286**: sim: measure DR-007 mirror-degen mirror-term ratio on the batch fleet
- **Issue #284** (closed): sim: measure DR-007's degenerated-mirror projection with a mirror-term MC variant run

### 2026-11-06

- **Issue #229** (closed): Live fleet verification of campaign-driver evidence storage (follow-on from PR #226)
- **PR #281**: test: run brownout campaign tests in self-checks CI, stub PDK lookup
- **Issue #280** (closed): Wire sim/brownout-top/selftest/test_brownout.py into self-checks CI; fix its 4 PDK-bound tests
- **PR #278**: chore(manifests): re-attest item 9 after runner drift
- **Issue #276** (closed): Re-attest item 9 after sim_common cap_retry refactor (#275)
- **PR #275**: refactor(sim): share fleet concurrency-cap retry in sim_common
- **Issue #274** (closed): Consolidate three copies of fleet concurrency-cap retry into sim_common

### 2026-11-05

- **PR #273**: ci: run corner-run batch and sim_common waveform tests in self-checks
- **Issue #272** (closed): Wire unrun sim/bin tests into self-checks CI (one already failing)

### 2026-11-02

- **Issue #260** (closed): T1 item 11 (power delivery): block-level temp_por_top ERC spec that accounts for the NT-biased temp_core nwells (2 erc.missing_tie)

### 2026-10-28

- **PR #265**: fix: name both graded tie classes in temp_por_top ERC ties_disclosure
- **Issue #263** (closed): temp_por_top ERC spec: ties_disclosure still says only nwell->VDD is graded
- **PR #262**: feat: add block-specific ERC supply spec for temp_por_top NT wells
- **PR #261**: fix: grade signoff items 3, 4, 11 against temp_por_top, not bias_core
- **Issue #259** (closed): T1 status: correct README and signoff-report claim that items 3, 4 and 11 are met — they grade the bias_core sub-block; block-level temp_por_top LVS is partial and ERC has 2 findings
- **PR #258**: refactor: hoist selftest record scaffolding and wave fixture writer into sim_common
- **Issue #254** (closed): Consolidate duplicated selftest record scaffolding and fixture writer into sim_common

### 2026-10-27

- **PR #256**: fix: make package.json check scripts run self-checks.yml steps instead of exiting 0
- **Issue #255** (closed): Hermit: package.json check scripts always exit 0; run the real self-checks or fail loudly
- **PR #253**: chore(klt): bump klayout-tools pin to 0.8.0 and re-render signoff evidence
- **Issue #252** (closed): Bump klayout-tools pin 758c6e224053 → 0.8.0
- **PR #251**: refactor: hoist probe, append-only guard and spiceinit loader into sim_common
- **Issue #247** (closed): Consolidate duplicated probe, append-only guard, and spiceinit loader into sim_common
- **Issue #203** (closed): Consolidate duplicated .end-stripping idiom into sim_common (10 copies)
- **PR #248**: fix: regenerate layout streams under the pinned klt and re-sync bias_core ports
- **Issue #243** (closed): Re-generate leaf layout streams under the pinned klt: committed leaf GDS now show 351 poly.endcap.diff.1 DRC violations
- **PR #246**: refactor: build campaign fleet requests through sim_common.base_request
- **Issue #245** (closed): Consolidate duplicated fleet-request scaffolding (batch block, MODEL_LIB) in campaign build_request into sim_common
- **PR #244**: feat: assemble temp_por_top GDS from the leaf streams and cite it for T1 item 2
- **Issue #240** (closed): T1 item 2 (layout): assemble the temp_por_top GDS from the committed leaf cells and cite it as block-level layout evidence

### 2026-10-23

- **PR #236**: refactor: netlist sim testbenches via klt netlist, remove raw xschem path
- **Issue #235** (closed): Remove raw-xschem netlist_with_xschem from sim harness: use netlist_with_klt everywhere
- **PR #237**: refactor(sim): share record-assembly helpers between brownout and glitch drivers
- **Issue #228** (closed): Consolidate duplicated record-assembly block in brownout/glitch campaign drivers into sim_common

- **PR #231**: sim(glitch-top): fleet subset run record with stored-evidence manifest
- **PR #233**: fix(sim): glitch record skips evidence store for empty classes
- **Issue #230** (closed): glitch-top record fails on a single-class subset run: empty stage refused for the all-NOT_COVERED class
- **PR #227**: refactor: hoist DUT .end-strip and ng_nomodcheck control into sim_common
- **Issue #225** (closed): Dedupe campaign-runner netlist boilerplate (.end strip, ng_nomodcheck banner) into sim_common
- **PR #226**: feat(sim): store campaign driver evidence in the artifact store
- **Issue #218** (closed): Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)
- **PR #224**: feat(signoff): attest design sources and cite the item-1 envelope
- **Issue #220** (closed): T1 item 1: run the design-source attestation through klt netlist (#193) and commit the passing envelope
- **PR #222**: feat(sim): add --backend batch to corner-run for fleet-routed PVT grids
- **Issue #219** (closed): corner-run.py: add a klt sim --backend batch path so the six local-grid experiments can be re-run on the fleet
- **PR #221**: feat(sim): route new corner-run evidence through the fleet artifact store

### 2026-10-20

- **PR #212**: refactor(design): netlist via klt netlist instead of raw xschem
- **Issue #193** (closed): Replace raw xschem call in design/netlist.py with klt netlist (drop hand-rolled PDK lookup, no timeout)
- **PR #215**: fix: refresh item-10 attestation envelope for edited self-checks.yml
- **Issue #214** (closed): signoff-manifest red on main: item-10 attestation envelope drifted after #192
- **PR #192**: fix(pdk): re-pin open_pdks to f6eeac7 via ciel and refuse a mismatched tree
- **Issue #188** (closed): Re-pin the sky130 PDK to open_pdks f6eeac7 (ciel 2.6.1) so testbenches name an installable revision (T1 item 9)
- **PR #207**: refactor(sim): share trace decimation and gz writer across checkers
- **Issue #206** (closed): Consolidate duplicated trace writer and decimation loop in sim checkers (6 copies)

### 2026-10-17

- **PR #200**: refactor(sim): consolidate corner_id, fmt and batch-submit core into sim_common
- **PR #198**: feat(signoff): attest T1 items 1, 9 and 10 via klt inventories
- **Issue #199** (closed): Consolidate corner_id/fmt and batch-submit copies into sim_common
- **Issue #186** (closed): T1 items 1, 9 and 10: commit design-source, testbench and repo-hygiene inventories and attest them with klt signoff --attest
- **PR #196**: refactor(sim): share klt_version and testbench netlist head via sim_common
- **PR #194**: docs: confirm temp_core mismatch figure and propose DR-007 accuracy design change
- **PR #190**: chore(signoff): bump klt pin to 758c6e224053 and re-render report
- **Issue #195** (closed): Dedupe sim campaign helpers: klt_version and tb_netlist_head copied across runners
- **Issue #187** (closed): temp_core accuracy: the 3-sigma mismatch error is about 25x the draft untrimmed target; confirm the figure, then propose a fix before the accuracy row can be ratified
- **Issue #185** (closed): Bump the pinned klt build to one that grades T1 items 1, 2, 9 and 10 on artifact-anchored evidence, and re-render the signoff report

### 2026-10-15

- **PR #180**: refactor(layout): retire unused lvs.dependency_variants from compose-cell
- **PR #179**: test: add guard reproducer and controls for /tmp-cwd relative writes
- **Issue #110** (closed): Remove unused LVS dependency-variant support from compose-cell.py
- **Issue #106** (closed): Brown-out and glitch-immunity matrix for assembled temp_por_top (porting-plan §3.4/§3.5)
- **Issue #88** (closed): Guard false positive: worktree write confinement rejects resolved /tmp loop paths

### 2026-10-12

- **PR #176**: sim: glitch-top POR_RAW-domain and VDD-level glitch campaign (#117)
- **Issue #117** (closed): Characterize POR_RAW-domain and VDD-level glitch immunity as distinct assembly experiments

### 2026-10-11

- **PR #172**: sim: consolidate duplicated waveform primitives into sim_common (#170)
- **PR #171**: sim: brownout-top declares reltol2e-4-klu variant and the enforced 3600 s job limit (#153)
- **PR #169**: sim: brownout-top tightened-solver (reltol2e-4) re-run harness + pilot record (#153)
- **Issue #170** (closed): Consolidate duplicated waveform primitives across ramp and brown-out checkers
- **PR #167**: sim: temp-core accuracy Monte Carlo campaign with per-term error budget (#105)
- **PR #166**: ci: preserve frozen netlist snapshots and corner evidence as append-only (#165)
- **PR #163**: ci: enforce append-only simulation records against the Git baseline
- **PR #161**: Solver-sensitivity replicate for natural-release iq-total (45 points x 3 variants)
- **PR #158**: ci: gate brown-out checker synthetic verdict cases
- **Issue #105** (closed): Full-signal-path mismatch Monte Carlo for temp_core accuracy (DR-003 TBD-1, T1 item 6)
- **Issue #165** (closed): Preserve frozen simulation decks and raw corner evidence in CI
- **Issue #164** (closed): Auditor Capability Request: Python interpreter for local evidence checks
- **Issue #162** (closed): CI: enforce append-only simulation records against the Git baseline
- **Issue #160** (closed): Resolve assembled iq-total exclusions with a full-grid solver-sensitivity replicate
- **Issue #159** (closed): Guard decision: retain confirmation for detached-checkout hard resets
- **Issue #156** (closed): CI: gate the brown-out checker synthetic verdict cases
- **Issue #155** (closed): Guard decision: retain confirmation for main-checkout stash

### 2026-10-10

- **PR #154**: sim: as-drawn brown-out campaign over independent dip axes x PVT (#116)
- **PR #152**: sim: EN-high base control lands; six temp_core cold-start FAILs not reproduced on any variant
- **Issue #116** (closed): As-drawn brown-out campaign: independent depth, duration and falling-slew matrix
- **Issue #86** (closed): temp_core startup records fail at six points inside the ratified envelope; demonstrate or record the cause

- **PR #150**: sim: diagnose the two RESETn re-assertions in the as-drawn ramp campaign (#142)
- **PR #149**: sim: solver/ramp discrimination sweep of temp_core cold-start FAILs (partial; fleet capacity)
- **Issue #142** (closed): supply-ramp-top: RESETn re-asserts after release at 2 of 360 as-drawn PVT/ramp points
- **PR #147**: refactor(sim): consolidate klt_version/load_manifest/load_wave into sim_common
- **Issue #140** (closed): Consolidate duplicated klt_version/load_manifest/load_wave helpers into sim_common.py (load_wave has drifted)
- **PR #145**: pad-island-census: cross-net merge check, gated sibling fallback, 3-state frame (#92)
- **PR #144**: bias_core: declare nwell->VDD tie, disclose p_substrate; T1 item 11 met (#90)
- **PR #143**: sim(supply-ramp-top): as-drawn 360-point fleet campaign after XMN1 fix (#101)
- **PR #141**: Post-layout (klt extract/pex) re-run of the por_comparator threshold campaign (T1 item 7)
- **Issue #92** (closed): pad-island-census: fail on cross-net island merges and gate the unpromoted-sibling-port fallback
- **Issue #90** (closed): bias_core ERC: declare (or disclose) well/substrate ties so T1 item 11 grades past supply_spec_incomplete
- **Issue #101** (closed): por_output_chain: XMN1 (L=25) has no valid model bin in the pinned PDK, so as-drawn temp_por_top cannot be simulated
- **Issue #124** (closed): Post-layout (klt pex) re-run of the por_comparator threshold campaign (T1 item 7)
- **Issue #132** (closed): Guard decision: retain main-checkout write confinement for sweep checkpoint writes

### 2026-10-09

- **PR #139**: docs(spec): DR-006 proposed Iq rows recommendation (TBD-4/5/6)
- **Issue #136** (closed): Draft DR recommending sky130 Iq rows (TBD-4/5/6) from committed iq-top evidence
- **PR #135**: Reject non-finite and malformed waveforms before Iq grading
- **PR #131**: docs(spec): align spec/README.md with DR-003 ratification (#127)
- **PR #134**: docs(spec): DR-005 proposed temp_buffer scope and PTAT/CTAT load assumption (#125)
- **PR #130**: docs(spec): DR-004 proposed sky130 POR threshold/hysteresis/ramp recommendation
- **PR #128**: Refresh characterization report and add coverage guard (#122)
- **PR #126**: docs(readme): align ratification-status statements with DR-003
- **Issue #133** (closed): Reject non-finite and malformed waveforms before Iq grading
- **Issue #127** (closed): spec/README.md: decision-records bullet says DR-003 is still proposed (ratified scoped to rows 1 and 6)
- **Issue #125** (closed): Decide temp_buffer scope and the Sensor-output row via a decision record
- **Issue #123** (closed): Draft DR recommending sky130 VPOR↑/VPOR↓, hysteresis and supply-ramp rows from committed #98/#102 evidence (T1 item 5)
- **Issue #122** (closed): Refresh the stale characterization report and add coverage guard so it cannot silently rot (T1 item 8)
- **Issue #85** (closed): README: ratification-status paragraphs outside the target table are stale after DR-003 rows 1 and 6 were ratified
- **PR #121**: sim(iq-top): assembled temp_por_top Iq campaign, por-iq / iq-total / temp-iq (#107)
- **Issue #107** (closed): Block-assembly Iq characterization: por-iq, temp-iq, iq-total (DR-003 TBD-4/5/6)
- **PR #119**: sim: record fleet refusal of as-drawn supply-ramp re-run (#101)
- **PR #115**: refactor(sim): hoist duplicated campaign-runner helpers into sim_common (#114)
- **PR #113**: sim: por_comparator VPOR-up/VPOR-down/hysteresis over PVT (por-comparator-thresholds campaign)
- **Issue #114** (closed): Consolidate duplicated helpers across the two batch campaign runners into sim_common.py
- **Issue #102** (closed): Characterize por_comparator VPOR↑/VPOR↓ and hysteresis over PVT (resolves DR-003 TBD-2/TBD-3 evidence gap)
- **Issue #96** (closed): Guard decision: retain confirmation for untracked layout cleanup
- **PR #111**: fix: por_output_chain XMN1 to a legal nfet_g5v0d10v5 model bin (L=20 W=0.42) (#101)
- **PR #109**: layout: add temp_core leaf cell (DRC clean, LVS match 48/48, no exclusions)
- **PR #108**: ci: run repo self-checks on every push (#103)
- **PR #100**: sim: assembled temp_por_top supply-ramp campaign across rates and PVT
- **PR #99**: layout: por_output_chain leaf (DRC clean, LVS match minus native XMASSIST) (#97)
- **PR #95**: layout: por_comparator leaf cell (21 devices), DRC clean, LVS match (#82)
- **Issue #104** (closed): Lay out temp_core as a DRC/LVS-verified leaf (T1 item 2)
- **Issue #103** (closed): CI: run the repo's existing self-checks (netlist export, checker selftests) on every push
- **Issue #98** (closed): Record assembled temp_por_top supply-ramp behavior across rates and PVT
- **Issue #82** (closed): T1 item 2: lay out por_comparator (21 devices) with the compose-cell recipe, DRC clean and LVS matched

### 2026-10-08

- **Issue #34** (closed): T1 item 2/10 continued: remaining bias_core device groups + full-cell assembly
- **PR #91**: bias_core: wire all cross-block nets on met3-met5, LVS match 50/50 devices, 27/27 nets (#81)
- **PR #87**: docs: block-level characterization report (T1 item 8)
- **PR #83**: spec: ratify DR-003 via the two-key ceremony (operating temperature + supply rows only)
- **Issue #81** (closed): bias_core: wire the nine remaining cross-block nets on the met3–met5 planes klayout-tools#2738 added (T1 items 4 and 11)
- **Issue #64** (closed): bias_core: wire remaining cross-block nets (pg/pb/n2/na/nbtop/VREF/nokx) once layer-assignment tooling improves
- **Issue #40** (closed): bias_core: full-cell assembly (compose all device-group sub-blocks)
- **Issue #31** (closed): T1 item 8/10: aggregate a block-level characterization report
- **Issue #78** (closed): Run the two-key ratification ceremony on DR-003 (target-spec table)

