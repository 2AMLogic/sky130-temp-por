# Work Log

Chronological record of recently merged pull requests and closed issues. This file is maintained by the Loom Guide role.

### 2026-10-10

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

### 2026-09-23

- **PR #77**: fix: strap PNP collectors to VSS and reach LVS match on klt 0.6.0
- **PR #76**: docs: embed fleet burndown chart in README
- **Issue #30** (closed): T1 item 2/10: lay out bias_core (first increment toward layout)
- **Issue #75** (closed): README: embed the fleet burndown chart (one line)

### 2026-09-21

- **PR #73**: fix: land bias_core supply legs on the real pads (block-local ports)
- **PR #72**: refactor: drop dead helpers and stale doc claims from sim_common.py
- **PR #70**: feat: add klt erc supply spec and report for bias_core (T1 item 11)
- **PR #68**: feat: add klt signoff block manifest as the T1 verdict of record
- **Issue #69** (closed): bias_core assembly: supply routes are single continuous rail islands but connect to none of the blocks' internal supply pads
- **Issue #71** (closed): Remove dead parse_measurements()/_cr() and write_log() from sim_common.py: zero callers, stale 'actually used' docstring claims
- **Issue #66** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo
- **Issue #67** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read

### 2026-09-17

- **PR #65**: feat: compose bias_core sub-blocks into one DRC-clean assembly
- **PR #63**: layout: promote ec/vss (pnp8_leg) and vss (xq1_xqr) external pins
- **Issue #61** (closed): bias_core: promote ec/vss (pnp8_leg) and vss (xq1_xqr) external pins once the closed-collector-ring escape restriction is addressed

### 2026-09-16

- **PR #62**: layout: promote missing external pins on bias_core sub-blocks
- **PR #60**: docs: fix stale narrative in design/netlist.py module docstring
- **PR #58**: Docs: correct stale "empty"/"pre-spec" status claims
- **PR #55**: layout: unambiguous klt commit pin + pin-mismatch warning
- **PR #54**: chore: remove unused shutil import in run_op_branch.py
- **PR #52**: layout: compose bias_core's current-mirror + error-amp stack, DRC- and LVS-clean
- **PR #50**: chore: remove dead run_ngspice()/mc_control_block() from sim_common.py
- **PR #48**: layout: bias_core startup kick chain, DRC- and LVS-clean
- **PR #47**: layout: trim residual fictional references in _klt_common.py docstrings
- **PR #46**: layout: compose bias_core's settle-flag output stage (BIAS_OK), DRC- and LVS-clean
- **Issue #56** (closed): bias_core: promote missing external pins on mirror_amp/settle_flag for full-cell assembly
- **Issue #59** (closed): design/netlist.py: module docstring is stale — temp_por_top/sim-harness claims no longer true
- **Issue #57** (closed): Docs: README.md and chipalooza proposal still claim the repo is empty/pre-spec
- **Issue #51** (closed): layout: host klt install is 38 commits behind layout/pdk.json's klt_version_pin, so compose-cell.py --check fails on every existing cell
- **Issue #53** (closed): Remove unused shutil import: run_op_branch.py
- **Issue #35** (closed): bias_core layout: PFET/NFET current-mirror + error-amp stack
- **Issue #49** (closed): Dead code + duplicated ngspice-run logic in sim/bin/sim_common.py
- **Issue #38** (closed): bias_core layout: startup kick chain
- **Issue #45** (closed): Trim residual fictional references in _klt_common.py's function docstrings (follow-up to #42)
- **Issue #39** (closed): bias_core layout: settle-flag output stage (BIAS_OK)

### 2026-09-15

- **PR #44**: docs: rewrite _klt_common.py module docstring to match this repo
- **PR #43**: layout: bias_core bias/ratio resistors + Miller caps sub-block
- **PR #41**: feat: lay out bias_core's XQ1/XQR reference PNPs (DRC-clean, LVS-blocked)
- **PR #33**: layout: port compose-cell recipe, lay out bias_core's 8:1 PNP leg
- **PR #32**: docs: DR-003, recommended target-spec table values with sim evidence
- **Issue #42** (closed): Fix fictional provenance narrative in layout/bin/_klt_common.py's docstring
- **Issue #37** (closed): bias_core layout: bias/ratio resistors + Miller compensation caps
- **Issue #36** (closed): bias_core layout: XQ1/XQR reference PNPs (collector-strap blocked in part)
- **Issue #29** (closed): T1 item 5/10: ratify the target spec table as a decision-record PR

### 2026-09-09

- **PR #28**: sim: characterize sky130 native devices (nfet_05v0_nvt vs nfet_03v3_nvt) for MASSIST
- **Issue #27** (closed): Characterize sky130's native devices (nfet_05v0_nvt vs nfet_03v3_nvt) for the POR startup-assist leg: Vth spread, minimum operating voltage, and MASSIST's always-on static current over PVT (porting-plan §2.6 / §4 item 2)
