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
| Leaf cell | `bias_core` startup/branch selection ([E1](#e1)-[E4](#e4)); `temp_core` co-instantiated with `bias_core`, startup only ([E5a](#e5a), [E5b](#e5b)) | No record for `por_comparator`, `por_output_chain` as cells, or any POR trip/hysteresis measurement |
| Whole block | none | No record exercises `temp_por_top` (the schematic and netlist exist under `design/`, no `sim/` campaign uses them) |

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
| Limits of the evidence | Three temperature points sample the endpoints and the midpoint of the range; they do not establish compliance across the continuous -40...+125 C envelope. Only device-slice and leaf-cell coverage exists; there is no whole-block (`temp_por_top`) run. No record measures temperature error, PTAT/CTAT slope, or any POR behaviour versus temperature, so nothing here shows the *block function* is correct across the range. The `bias_core` first-record FAILs and `temp_core` FAILs below are open as recorded |

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
| Limits of the evidence | Three supply points; no continuous sweep of the full range for any cell except the diagnostic in [E4](#e4), which is single-process, near-room-temperature and cold-`.op` only. **No supply-ramp-rate sweep, brown-out, or POR threshold/hysteresis record exists** (see 4); the startup records use one ramp (100 us, per `experiment.json`) and do not characterize the block's behaviour across ramp rates. No whole-block run |

## 4. Unratified rows (explicit placeholders, evidence gaps)

These rows are **not ratified**. No target is stated or inferred here, and the
campaigns in section 5 are not cited as evidence for them. Numbering follows DR-003.

| README row | Placeholder | Evidence on `main` | Gap |
|---|---|---|---|
| Temperature error, untrimmed | [TBD-1] | None. No record measures sensor error versus temperature. [E7](#e7) reports PNP dVBE mismatch only, which DR-003 treats as a partial input rather than a ratifiable number | Evidence gap |
| Sensor output | [TBD] | None | Evidence gap |
| POR thresholds VPOR-up / VPOR-down | [TBD-2] | None. No POR trip-point record exists | Evidence gap |
| POR hysteresis | [TBD-3] | None | Evidence gap |
| Iq (block total) | [TBD-4] por-iq / [TBD-5] temp-iq / [TBD-6] iq-total | None as an Iq claim. The `isup` figures in [E3](#e3) (bias_core only) and the static-current table in [E6](#e6) (bare devices) are sub-cell harness quantities, not a por-iq / temp-iq / iq-total measurement | Evidence gap |
| Supply-ramp coverage | [TBD] | None. All startup records use a single ramp | Evidence gap |

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
ngspice-46 / XSCHEM V3.4.7 on Linux, except where noted.

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

## 6. Gaps summary

1. Whole-block (`temp_por_top`) simulation: none.
2. `temp_core` startup: both records FAIL (3 corners each); cause not established; owned by #86.
3. POR comparator and output-chain cells: no cell-level records; only the native-device slice (E6).
4. Continuous temperature and supply coverage: only three points each (plus the narrow diagnostic E4).
5. Supply-ramp-rate sweep and brown-out behaviour: no record.
6. Provenance: all leaf-cell records were taken from a dirty working tree; `f4f73a5` and `c7b9b94` do not resolve in current history.
7. The six unratified rows (section 4) have no ratified targets and no evidence.
