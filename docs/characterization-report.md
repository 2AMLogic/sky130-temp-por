# Block-level characterization report

Aggregation of the simulation evidence committed under [`sim/`](../sim/README.md)
against the target-specification rows in [`README.md`](../README.md#target-specification-partially-ratified--dr-003-issue-78-remaining-rows-tbd).
Issue #31 (T1 item 8). This report only **aggregates** existing records:

- No simulation was run to produce it; every citation resolves to a file on `main`.
- No spec row, record, or design file is edited by it (`sim/` is append-only evidence).
- It does **not** award, propose, or record a T1 tier, and does not relax the spec.
- Where evidence is missing, partial, or recorded as FAIL, that is stated as a gap, not smoothed over.

Numbers below are copied from the cited records; nothing is inferred or extrapolated.

## 1. Ratification scope

[DR-003](../spec/decision-records/DR-003-ratify-target-spec-recommendation.md)
(Status: ratified, two-key path, issue #78, scoped) made exactly two rows final in
`README.md`: **operating temperature** and **supply**. The other six rows are
explicit placeholders (section 4). DR-003 ratifies the supply row at
[DR-001](../spec/decision-records/DR-001-supply-flavor.md)'s value without
re-ratifying DR-001 itself; DR-001's own file still reads `proposed`, and
`spec/README.md`'s index still lists all three DRs as proposed (a stale index, not
the authoritative target table).

## 2. Evidence coverage at a glance

| Coverage level | What exists on `main` | What does not |
|---|---|---|
| Device slice | Bare `nfet_05v0_nvt` / `nfet_03v3_nvt` devices over the full 45-point PVT grid ([E6](#e6)); PNP mismatch Monte Carlo ([E7](#e7)) | - |
| Leaf cell | `bias_core` startup/branch selection ([E1](#e1)-[E4](#e4)); `temp_core` co-instantiated with `bias_core`, startup only ([E5a](#e5a), [E5b](#e5b)); `por_comparator` VPOR-up / VPOR-down / hysteresis on a quasi-static VDD sweep, ideal-bias and real-`bias_core` variants ([E8](#e8)) | No cell-level record for `por_output_chain` alone (it is exercised only inside the whole-block campaigns E9-E11). `por_comparator` thresholds have no mismatch Monte Carlo, no combined MOS x resistor-skew corners, and no post-layout parasitics |
| Whole block | `temp_por_top` supply-ramp behaviour, 8 ramp rates x 45 PVT points, on a **diagnostic** netlist variant ([E9](#e9)); the as-drawn variant has no PVT/ramp result ([E9](#e9)); `temp_por_top` Iq (por-iq / iq-total / incremental temp-iq), 45-point grid, as drawn ([E10](#e10)) | No as-drawn supply-ramp PVT result; no brown-out record; the whole-block records inherit the open `temp_core` non-physical-branch signature (#86) |

Every PVT-grid record samples a **3 x 3 x 5 grid**: temperature {-40, 27, 125} C,
supply {2.97, 3.30, 3.63} V, process {tt, ss, ff, sf, fs}. Corner PASS/FAIL is
judged against harness bounds declared in each `experiment.json`, which the records
themselves describe as liveness/branch-selection windows and "NOT a spec claim".

## 3. Ratified rows

### 3.1 Operating temperature: -40...+125 C (final)

| Aspect | Content |
|---|---|
| Ratified target | -40...+125 C, no stretch value (README table; DR-003 row 1, HOLD as drafted) |
| Conditions exercised | Temperature points -40, 27, 125 C only, in every PVT-grid record ([E1](#e1), [E2](#e2), [E3](#e3), [E5a](#e5a), [E5b](#e5b), [E6](#e6)) and in the PNP mismatch Monte Carlo ([E7](#e7)). [E4](#e4) probes 22-32 C at tt only and is a solver diagnostic, not a temperature claim |
| Recorded outcome | Device slice ([E6](#e6)): Overall PASS at all 45 points; Vth of the native-device bins crosses zero inside the range (e.g. `n05l25` ranges -24.5 mV at sf/125 C to +239.5 mV at fs/-40 C), per that experiment's README. `bias_core` ([E3](#e3)): Overall PASS at all 45 points, `vref` 1.24557-1.25815 V across the grid, supply current 7.62936e-07-1.196e-06 A. `temp_core` ([E5a](#e5a), [E5b](#e5b)): Overall **FAIL** in both records, 42/45 points PASS each (see 3.1.1). PNP mismatch ([E7](#e7)): PASS, dVBE sigma recorded at -40/27/125 C |
| Limits of the evidence | Three temperature points sample the endpoints and the midpoint of the range; they do not establish compliance across the continuous -40...+125 C envelope. Whole-block records exist ([E9](#e9), [E10](#e10)) but use the same three temperature points, and their outcomes are partly FAIL / flagged (section 5). The POR comparator thresholds are measured at -40/27/125 C ([E8](#e8)). No record measures temperature error or PTAT/CTAT slope, so nothing here shows the *sensor function* is correct across the range. The `bias_core` first-record FAILs and `temp_core` FAILs below are open as recorded |

#### 3.1.1 Recorded `temp_core` startup FAILs (kept visible)

Both records have `Overall: FAIL` with three failing corner entries each. The
`isup`/`ptat`/`ctat` values at the failing points are non-physical in several cases
(for example negative supply current). The records and the experiment index
([`sim/README.md`](../sim/README.md#current-experiments)) attribute the signature to a
solver artifact, but that attribution is a **hypothesis** carried by those documents;
issue #86 owns the investigation. This report records the outcome as FAIL.

| Record | Failing corners (process_temp_supply) |
|---|---|
| [E5a](#e5a) (EN tied high) | `tt_-40c_3.30v`, `tt_125c_3.30v`, `ff_-40c_3.30v` |
| [E5b](#e5b) (EN released late) | `tt_27c_3.63v`, `tt_125c_3.63v`, `sf_-40c_2.97v` |

### 3.2 Supply: 2.97-3.63 V (3.3 V +/-10 %, DR-001) (final)

| Aspect | Content |
|---|---|
| Ratified target | 2.97-3.63 V, no stretch value (README table; DR-003 row 6, ratified at DR-001's value) |
| Conditions exercised | Supply points 2.97, 3.30, 3.63 V in every PVT-grid record ([E1](#e1), [E2](#e2), [E3](#e3), [E5a](#e5a), [E5b](#e5b), [E6](#e6)). [E4](#e4) sweeps 2.97-3.63 V in 10 mV steps (67 values) at tt and 22-32 C only. [E7](#e7) has no supply axis (current-biased diode-connected PNPs) |
| Recorded outcome | `bias_core` startup from 0 V ([E3](#e3)): PASS at all 45 points including the 2.97 V and 3.63 V endpoints. `bias_core` cold `.op` ([E1](#e1)): FAIL at `tt_27c_2.97v` and `tt_27c_3.63v`; [E4](#e4) diagnoses these (and other off-branch `.op` points) as non-physical solver artifacts rather than a second stable state, and [E3](#e3) supersedes the startup experiment's earlier FAIL record ([E2](#e2)). `temp_core` ([E5a](#e5a), [E5b](#e5b)): FAIL as in 3.1.1; failing entries occur at 2.97, 3.30 and 3.63 V. Device slice ([E6](#e6)): PASS at all 45 points, with MASSIST-condition current worst at ff/-40 C/3.63 V per that README |
| Limits of the evidence | Three supply points; no continuous sweep of the full range for any cell except the diagnostic in [E4](#e4), which is single-process, near-room-temperature and cold-`.op` only. The leaf-cell startup records use one ramp (100 us, per `experiment.json`). Ramp-rate coverage exists only in [E9](#e9) (8 rates, 500 V/s to 1 MV/s, exploratory, on a diagnostic variant with a partly FAIL outcome). **No brown-out record exists.** The [E8](#e8) thresholds are measured against a swept VDD (0 to 3.63 V) rather than at the three supply points |

## 4. Unratified rows (explicit placeholders, evidence gaps)

These rows are **not ratified**. No target is stated or inferred here. The
evidence column names records that bear on each row; none of them is a ratified
bound, and each record itself declares it is "NOT a spec claim" (the
por-comparator and Iq records describe their numbers as inputs to a follow-on
DR-003 amendment, which has not happened). Numbering follows DR-003.

| README row | Placeholder | Evidence on `main` | Gap |
|---|---|---|---|
| Temperature error, untrimmed | [TBD-1] | None. No record measures sensor error versus temperature. [E7](#e7) reports PNP dVBE mismatch only, which DR-003 treats as a partial input rather than a ratifiable number | Evidence gap |
| Sensor output | [TBD] | None | Evidence gap |
| POR thresholds VPOR-up / VPOR-down | [TBD-2] | [E8](#e8): `por_comparator` alone, 15 points per variant (5 process x 3 T), VPOR-up 2.6832-2.7010 V (ideal-bias) and 2.6908-2.7130 V (real `bias_core`); VPOR-down 2.5430-2.5510 V and 2.5353-2.5567 V. Margin vs the 2.97 V rail +269 mV / +257 mV. Comparator cell only, not the assembled block, no Monte Carlo | Unratified; no ratified number; Monte Carlo margin absent |
| POR hysteresis | [TBD-3] | [E8](#e8): 139.7-150.1 mV (ideal-bias), 145.9-156.3 mV (real `bias_core`) over the same 15 points. The record states a ceiling still needs the `[TBD]` `por-digital-min-vdd` input | Unratified; ceiling input missing |
| Iq (block total) | [TBD-4] por-iq / [TBD-5] temp-iq / [TBD-6] iq-total | [E10](#e10): assembled `temp_por_top` as drawn, 45 points per state. por-iq 50.836-120.264 uA (45/45 ok); iq-total 16.424-36.504 uA at the 28/45 `ok` points, **17/45 iq-total points flagged non-physical-branch**; incremental temp-iq is negative at every `ok` point (por-iq includes forced-reset contention) so it is not the sensor's own current. The record proposes no ceiling | Unratified; iq-total and temp-iq incomplete (17/45 excluded); no ceiling |
| Supply-ramp coverage | [TBD] | [E9](#e9): 8 ramp rates x 45 PVT points on a diagnostic variant (209 PASS / 151 FAIL of 360 points, FAILs are almost all `nonphysical` node flags); as-drawn variant 360/360 ERROR in the first run, then not run on the fleet (refused) | Unratified; no as-drawn PVT/ramp result; no brown-out |

## 5. Evidence index

Provenance fields are quoted from each record's header. "Dirty tree" means the
record states the working tree was dirty at run time; such records were **not**
produced from a verified-clean checkout of the committed netlist. Source revisions
`f4f73a5` and `c7b9b94` do **not resolve** to a commit in the current repository
history (likely rewritten or squashed on merge) and are listed as unresolved;
`a9cac4b` and `ee63b45` do resolve. For records whose revision is unresolved or tree
dirty, the frozen netlist snapshot referenced in the record is the artifact that pins
what ran. All records use PDK sky130A at open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` (matches `sim/pdk.json`) and
ngspice-46 / XSCHEM V3.4.7 on Linux, except where noted. E8-E10 are fleet batch runs (fleet ngspice-46) whose records list the host as ngspice-42 / XSCHEM V3.4.4 for netlisting and local probes; see each record's header for its repo state and clean/dirty flag.

<a id="e1"></a>
### E1 - `bias-core-smoke`, cold `.op`, record `20260825-214036-a9cac4b`

- Record: [md](../sim/bias-core-smoke/records/20260825-214036-a9cac4b.md), [json](../sim/bias-core-smoke/records/20260825-214036-a9cac4b.json); manifest [experiment.json](../sim/bias-core-smoke/experiment.json); netlist [snapshot](../sim/bias-core-smoke/netlist-snapshots/20260825-214036-a9cac4b.spice)
- Revision: `a9cac4b` on `feature/issue-17` (resolves); **dirty tree**
- Level: leaf cell (`bias_core`), `.op`
- Conditions: 45-point full grid (5 process x 3 T x 3 V)
- Outcome: **Overall FAIL**; failing points `tt_27c_2.97v` and `tt_27c_3.63v` (supply current recorded negative, `vref` at the rail)
- Limitations: harness bring-up record, "NOT a spec claim"; a cold `.op` does not select the intended branch reliably (see E4)

<a id="e2"></a>
### E2 - `bias-core-startup`, first record `20260825-235846-f4f73a5` (superseded)

- Record: [md](../sim/bias-core-startup/records/20260825-235846-f4f73a5.md), [json](../sim/bias-core-startup/records/20260825-235846-f4f73a5.json); [snapshot](../sim/bias-core-startup/netlist-snapshots/20260825-235846-f4f73a5.spice)
- Revision: `f4f73a5` on `feature/issue-19` (**unresolved in current history**); **dirty tree**
- Level: leaf cell (`bias_core`), transient from 0 V
- Conditions: 45-point full grid
- Outcome: **Overall FAIL**; failing points `sf_125c_3.63v` and `fs_-40c_3.30v`
- Limitations: superseded by E3 (E3's `Supersedes` field points here); kept as committed evidence

<a id="e3"></a>
### E3 - `bias-core-startup`, record `20260826-005156-f4f73a5`

- Record: [md](../sim/bias-core-startup/records/20260826-005156-f4f73a5.md), [json](../sim/bias-core-startup/records/20260826-005156-f4f73a5.json); manifest [experiment.json](../sim/bias-core-startup/experiment.json); testbench [schematic](../sim/bias-core-startup/testbench/tb_bias_core_startup.sch); [snapshot](../sim/bias-core-startup/netlist-snapshots/20260826-005156-f4f73a5.spice)
- Revision: `f4f73a5` on `feature/issue-19` (**unresolved in current history**); **dirty tree**
- Level: leaf cell (`bias_core`), `tran ... uic` supply ramp from 0 V (100 us ramp, 10 ms run)
- Conditions: 45-point full grid
- Outcome: **Overall PASS**, 45/45 points. Recorded `vref` 1.24557-1.25815 V and supply current 7.62936e-07-1.196e-06 A over the grid; corner-sensitivity check PASS (spread 0.012578 V)
- Limitations: one ramp rate; `bias_core` alone; harness windows, not spec limits

<a id="e4"></a>
### E4 - `bias-core-op-branch`, record `20260826-001526-f4f73a5`

- Record: [md](../sim/bias-core-op-branch/records/20260826-001526-f4f73a5.md), [json](../sim/bias-core-op-branch/records/20260826-001526-f4f73a5.json); script [run_op_branch.py](../sim/bias-core-op-branch/run_op_branch.py); [snapshot](../sim/bias-core-op-branch/netlist-snapshots/20260826-001526-f4f73a5.spice)
- Revision: `f4f73a5` on `feature/issue-19` (**unresolved in current history**); **dirty tree**
- Level: leaf cell, solver diagnostic
- Conditions: deliberate non-PVT subset: tt only, 9 temperatures 22-32 C, supply 2.97-3.63 V in 10 mV steps (67 values), 150 `.op` invocations
- Outcome: Overall PASS (diagnostic checks); verdict recorded as "SOLVER ARTIFACT" for all 13 off-branch points
- Limitations: not a PVT or spec record; says nothing about other process corners or temperatures

<a id="e5a"></a>
### E5a - `temp-core-startup`, record `20260826-053032-ee63b45`

- Record: [md](../sim/temp-core-startup/records/20260826-053032-ee63b45.md), [json](../sim/temp-core-startup/records/20260826-053032-ee63b45.json); manifest [experiment.json](../sim/temp-core-startup/experiment.json); testbench [schematic](../sim/temp-core-startup/testbench/tb_temp_core_startup.sch); [snapshot](../sim/temp-core-startup/netlist-snapshots/20260826-053032-ee63b45.spice)
- Revision: `ee63b45` on `feature/issue-22` (resolves); **dirty tree**
- Level: leaf cells (`temp_core` co-instantiated with `bias_core`), transient from 0 V, EN tied high through the ramp
- Conditions: 45-point full grid
- Outcome: **Overall FAIL**, 42/45 PASS; failing points listed in 3.1.1
- Limitations: startup behaviour only (PTAT/CTAT in harness windows), not temperature accuracy; failure cause not established (#86)

<a id="e5b"></a>
### E5b - `temp-core-startup-en-delayed`, record `20260826-054047-ee63b45`

- Record: [md](../sim/temp-core-startup-en-delayed/records/20260826-054047-ee63b45.md), [json](../sim/temp-core-startup-en-delayed/records/20260826-054047-ee63b45.json); manifest [experiment.json](../sim/temp-core-startup-en-delayed/experiment.json); testbench [schematic](../sim/temp-core-startup-en-delayed/testbench/tb_temp_core_startup_en_delayed.sch); [snapshot](../sim/temp-core-startup-en-delayed/netlist-snapshots/20260826-054047-ee63b45.spice)
- Revision: `ee63b45` on `feature/issue-22` (resolves); **dirty tree**
- Level: leaf cells, transient from 0 V, EN held low then released after the supply settles (the DR-002 ordering)
- Conditions: 45-point full grid
- Outcome: **Overall FAIL**, 42/45 PASS; failing points listed in 3.1.1
- Limitations: as E5a

<a id="e6"></a>
### E6 - `native-device-characterization`, record `20260909-232337-c7b9b94`

- Record: [md](../sim/native-device-characterization/records/20260909-232337-c7b9b94.md), [json](../sim/native-device-characterization/records/20260909-232337-c7b9b94.json); [README](../sim/native-device-characterization/README.md); manifest [experiment.json](../sim/native-device-characterization/experiment.json); testbench [schematic](../sim/native-device-characterization/testbench/tb_native_device_char.sch); [snapshot](../sim/native-device-characterization/netlist-snapshots/20260909-232337-c7b9b94.spice)
- Revision: `c7b9b94` on `feature/issue-27`, record states **clean working tree**; revision **unresolved in current history**
- Level: device slice only. DUTs are bare PDK devices, not this design's cells
- Conditions: 45-point full grid
- Outcome: **Overall PASS**; both corner-sensitivity checks PASS
- Limitations: characterizes the device menu (Vth, MASSIST-condition static current, off-state current, assist-onset voltage); not `por_output_chain` as a block and not a spec claim

<a id="e7"></a>
### E7 - `pnp-mismatch`, record `20260825-220116-a9cac4b`

- Record: [md](../sim/pnp-mismatch/records/20260825-220116-a9cac4b.md), [json](../sim/pnp-mismatch/records/20260825-220116-a9cac4b.json); script [run_pnp_mismatch.py](../sim/pnp-mismatch/run_pnp_mismatch.py); testbench [deck](../sim/pnp-mismatch/testbench/tb_pnp_mismatch.spice); [snapshot](../sim/pnp-mismatch/netlist-snapshots/20260825-220116-a9cac4b.spice)
- Revision: `a9cac4b` on `feature/issue-17` (resolves); **dirty tree**
- Level: device slice (PNP pairs, 1x vs 8x array)
- Conditions: local-mismatch Monte Carlo N = 300 at -40/27/125 C, 1 sigma convention; 1 control point, 1 second-seed point, 1 global-process liveness point (N = 30, 27 C); no supply axis
- Outcome: Result PASS (record makes no spec pass/fail claim)
- Limitations: harness-liveness plus distribution of dVBE; not a temperature-accuracy measurement; the three temperature rows share one seed and are not independent estimates

<a id="e8"></a>
### E8 - `por-comparator-thresholds`, four records (issue #102)

- Records (all in `sim/por-comparator-thresholds/records/`): [ideal-bias md](../sim/por-comparator-thresholds/records/20261009-054322-10d3e9f-ideal-bias.md), [json](../sim/por-comparator-thresholds/records/20261009-054322-10d3e9f-ideal-bias.json); [real-bias-core md](../sim/por-comparator-thresholds/records/20261009-054331-79eebd4-real-bias-core.md), [json](../sim/por-comparator-thresholds/records/20261009-054331-79eebd4-real-bias-core.json); [ideal-bias passive-skew md](../sim/por-comparator-thresholds/records/20261009-062844-09eb234-ideal-bias-passive-skew.md), [json](../sim/por-comparator-thresholds/records/20261009-062844-09eb234-ideal-bias-passive-skew.json); [real-bias-core passive-skew md](../sim/por-comparator-thresholds/records/20261009-062845-bf30f6c-real-bias-core-passive-skew.md), [json](../sim/por-comparator-thresholds/records/20261009-062845-bf30f6c-real-bias-core-passive-skew.json); [README](../sim/por-comparator-thresholds/README.md); manifest [experiment.json](../sim/por-comparator-thresholds/experiment.json)
- Level: leaf cell (`por_comparator`), quasi-static constant-rate VDD sweep up to 3.63 V and back (100 V/s primary, 50 V/s half-rate guard); fleet batch runs
- Conditions: main grid process {tt, ss, ff, sf, fs} x {-40, 27, 125} C = 15 points per variant; supplement ll/hh x the same 3 temperatures = 6 points per variant (tt MOS, resistor/capacitor skew only). Two variants, never mixed: `ideal-bias` (ideal 1 uA IBIAS, ideal 1.25 V VREF) and `real-bias-core`
- Outcome (main grid, per the README, 15/15 points per variant with clean single edges, rate-consistent): ideal-bias VPOR-up 2.6832 V (ff, 125 C) to 2.7010 V (ss, -40 C), VPOR-down 2.5430 V (fs, 125 C) to 2.5510 V (ss, -40 C), hysteresis 139.7 mV (sf, 125 C) to 150.1 mV (ss, -40 C). real-bias-core VPOR-up 2.6908 V (sf, -40 C) to 2.7130 V (ss, 27 C), VPOR-down 2.5353 V (sf, -40 C) to 2.5567 V (ss, 27 C), hysteresis 145.9 mV (sf, 125 C) to 156.3 mV (ss, 27 C). Margin `2.97 V - max(VPOR-up)`: +269 mV (ideal-bias), +257 mV (real-bias-core). Passive-skew supplement: VPOR-up 2.6868-2.6990 V (ideal-bias) and 2.6950-2.7110 V (real-bias-core); margins +271 mV and +259 mV; kept separate from the main tables
- Limitations: "NOT a spec claim"; numbers are described by the README as proposals for a follow-on DR-003 amendment that has not been made. Comparator cell only; no mismatch Monte Carlo (the README names comparator offset and divider mismatch as the likely dominant spread), no combined MOS x resistor-skew corners, no parasitics, only 100/50 V/s sweep rates. The README reports 25 refused fleet launches that were re-submitted unchanged; no grid point fell back to a local run

<a id="e9"></a>
### E9 - `supply-ramp-top`, whole-block supply-ramp campaign (issues #98, #101)

- Records (in `sim/supply-ramp-top/records/`): [as-drawn first run md](../sim/supply-ramp-top/records/20261009-024606-285dd08.md), [json](../sim/supply-ramp-top/records/20261009-024606-285dd08.json); [diag-mn1-l20 md](../sim/supply-ramp-top/records/20261009-024607-285dd08.md), [json](../sim/supply-ramp-top/records/20261009-024607-285dd08.json); [as-drawn re-run md](../sim/supply-ramp-top/records/20261009-055755-5346c37.md), [json](../sim/supply-ramp-top/records/20261009-055755-5346c37.json); [local probe](../sim/supply-ramp-top/records/20261009-055755-5346c37-local-probe.md); [fleet refusal](../sim/supply-ramp-top/records/20261009-180056-987e04f-fleet-refusal.md); [checker selftest md](../sim/supply-ramp-top/records/20261009-012246-285dd08-checker-selftest.md), [json](../sim/supply-ramp-top/records/20261009-012246-285dd08-checker-selftest.json); manifest [experiment.json](../sim/supply-ramp-top/experiment.json)
- Level: whole block (`temp_por_top`: `bias_core` + `temp_core` + `por_comparator` + `por_output_chain`, real shared IBIAS node and RESETn -> EN feedback), transient from 0 V; 8 exploratory ramp rates (500 V/s to 1 MV/s) x 45 PVT points = 360 points per variant, each primary rate with a half-rate guard; fleet batch
- Outcome, as-drawn first run (`...-024606-285dd08`): **all 360 points ERROR** (`model_not_found`, no valid model bin for `por_output_chain.XMN1` at L=25 W=0.5 in the pinned PDK); no waveform was retrieved. The as-drawn re-run (`...-055755-5346c37`, after the XMN1 change of #101) has 0 of 360 points with a retrieved waveform because every fleet submission was refused; the fleet-refusal companion records a further 8 refused requests. **No as-drawn PVT/ramp result exists.** The single local probe (tt, 27 C, 3.30 V, 10 kV/s) shows the as-drawn netlist simulates with no model-bin error and is explicitly not a PVT or ramp-rate result
- Outcome, diagnostic variant (`...-024607-285dd08`, XMN1 netlisted at L=20; **not** the committed circuit): 209 PASS / 151 FAIL of 360 points. The transition verdict is PASS (one release, no re-assert) at 358 of 360; the two transition FAILs are at 500 kV/s (`no_release`; `reassert_after_release` with `extra_mid_crossings`). Every FAIL point carries the `nonphysical` node flag (17-24 points per rate, 151 in total), the #86 signature of `temp_core`. Half-rate guard grading includes 30 points at 10 kV/s graded `rate-dependent` for VDD at POR_RAW crossing
- Limitations: exploratory rate set and thresholds, "NOT a spec claim", no ratified ramp envelope (DR-003 Sec8); `ll`/`hh` skew not crossed with ramp rate; no brown-out; no Monte Carlo; PTAT/CTAT left open-circuit; the diagnostic variant is not the as-drawn design. The checker selftest record (Overall PASS) is a synthetic-waveform proof of the checker, not a circuit result

<a id="e10"></a>
### E10 - `iq-top`, assembled `temp_por_top` Iq (issue #107)

- Records (in `sim/iq-top/records/`): [campaign md](../sim/iq-top/records/20261009-191705-df85523.md), [json](../sim/iq-top/records/20261009-191705-df85523.json); [checker selftest md](../sim/iq-top/records/20261009-182935-cf99f67-checker-selftest.md), [json](../sim/iq-top/records/20261009-182935-cf99f67-checker-selftest.json); [later checker selftest md](../sim/iq-top/records/20261009-191705-cb8343e-checker-selftest.md), [json](../sim/iq-top/records/20261009-191705-cb8343e-checker-selftest.json); [README](../sim/iq-top/README.md); manifest [experiment.json](../sim/iq-top/experiment.json)
- Revision: `df85523` on `feature/issue-107`, record states **clean working tree**
- Level: whole block, as drawn; two direct states (por-iq with RESETn forced low by a testbench source; iq-total released) plus derived incremental temp-iq; transient from 0 V, current averaged over 25-30 ms with a checked settling criterion; fleet batch
- Conditions: full 45-point grid per state (5 process x 3 T x 3 V)
- Outcome: por-iq 45/45 `ok`, 50.836-120.264 uA (worst ff, -40 C, 3.63 V; typ tt/27 C/3.30 V 79.443 uA), of which the forced-reset output-stage contention is 46.343-112.162 uA and por-iq less contention is 4.404-8.102 uA. iq-total 28/45 `ok`, 16.424-36.504 uA (worst ff, -40 C, 3.63 V); **17/45 iq-total points are flagged non-physical-branch** (negative settled current, nodes outside the rails; the #86 signature) and excluded from the `ok` statistics, including the typical tt/27 C/3.30 V point. Incremental temp-iq is -83.759 to -33.956 uA at the 28 `ok` points, negative because por-iq includes the contention current; the record states it is not the sensor's own current. The local cross-check of por-iq at tt/27 C/3.30 V matches the fleet; the iq-total local probe returned no waveform (UNRESOLVED). The two checker selftest records are Overall PASS
- Limitations: "EVIDENCE ONLY, NOT a spec claim and NOT a proposed ceiling"; no ceiling proposed; Iq at three supply points only; temp-iq has no clean figure

## 6. Gaps summary

1. Whole-block (`temp_por_top`) simulation: records exist (E9, E10) but the as-drawn supply-ramp PVT matrix has no result (E9: first run all ERROR on a model-bin failure, re-run refused by the fleet); the diagnostic-variant ramp run is 209 PASS / 151 FAIL of 360 points; Iq iq-total has 17/45 non-physical-branch points.
2. `temp_core` startup: both leaf records FAIL (3 corners each) and the same non-physical signature recurs in E9 and E10; cause not established; owned by #86.
3. POR comparator thresholds (E8) are measured on the cell only, with no mismatch Monte Carlo; `por_output_chain` has no cell-level record (only E6 devices and the whole-block runs).
4. Continuous temperature and supply coverage: only three points each (plus the narrow diagnostic E4); E8 sweeps VDD continuously but only for the comparator.
5. Brown-out behaviour: no record. Supply-ramp-rate coverage: exploratory, diagnostic variant only (E9).
6. Provenance: all leaf-cell records were taken from a dirty working tree; `f4f73a5` and `c7b9b94` do not resolve in current history.
7. The six unratified rows (section 4) have no ratified targets. Evidence for the POR threshold, hysteresis, Iq and supply-ramp rows exists in E8-E10 but is incomplete as stated above and is not a spec claim; no evidence exists for the temperature-error and sensor-output rows.
