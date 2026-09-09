# `native-device-characterization` — sky130 `nfet_05v0_nvt` vs `nfet_03v3_nvt`

Issue #27: the first characterization of sky130's near-zero-`Vt` ("native")
NMOS device class this port introduced. No sibling repo has data for this
class, and `spec/porting-plan.md` §2.2/§2.6 explicitly defer it to a
characterization issue. The DUTs are bare PDK devices, **not** this design's
cells — this experiment characterizes the *device menu*, not
`por_output_chain` as a block, and does not change the schematic or re-decide
the device flavor/bin (see `design/por_output_chain.md` and
[Out of scope](../../design/por_output_chain.md) in the parent issue).

Three geometries are characterized, all fixed-`(L,W)` PDK library bins (not
free sizing choices — see `design/por_output_chain.md`'s "Device choice"):

| Label | Device | `L` (µm) | `W` (µm) | Why this bin |
|---|---|---|---|---|
| `n05l25` | `sky130_fd_pr__nfet_05v0_nvt` | 25 | 1 | The bin `MASSIST` is drawn at (`design/por_output_chain.sch`) |
| `n05l8` | `sky130_fd_pr__nfet_05v0_nvt` | 8 | 1 | Next-longest `05v0_nvt` bin, to separate device-class effects from geometry effects |
| `n03l08` | `sky130_fd_pr__nfet_03v3_nvt` | 0.8 | 0.42 | The longest-channel (weakest) bin the entire `03v3_nvt` menu offers — the fair best case for that flavor in the §2.6 comparison |

## Cold-start command

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 sim/bin/corner-run.py sim/native-device-characterization
```

~45–100 minutes wall clock on a single core (45 ngspice invocations, one per
PVT point; per-corner elapsed time ranges from ~14 s to ~280 s — see the raw
logs under `corners/<record-id>/`).

## What each measurement is

- **Vth** (`vth_*`): constant-current threshold voltage, linear region
  (`VDS` = 100 mV), criterion `I_D = 100 nA * (W/L)`. Zero-body-effect
  (source and bulk both grounded) — the right condition for `MASSIST`, whose
  source and bulk are both on `VSS`. A property of the device only: does not
  depend on the supply axis (replicated identically across the three supply
  points of a given process/temperature pair — see `experiment.json`'s
  `notes`).
- **`ion_*`** (the headline number): drain current of a device wired *exactly*
  like `MASSIST` — gate **and** drain at `VDD`, source/bulk at `VSS` — read
  through its own ammeter at `VDS = VGS = ` the corner's supply. This is the
  always-on static current `MASSIST` costs in the released state.
- **`ioff_*`**: off-state/subthreshold reference — same geometry, gate at
  `VSS`, drain still at `VDD`. Not `MASSIST`'s operating point (its gate is
  tied to `VDD` by construction); shows how much of `ion_*` is gate drive vs.
  device-class floor.
- **`vmin1n_*` / `vmin100n_*`**: the assist-onset voltage — the rail voltage
  at which a `MASSIST`-connected device (gate tied to the swept rail) first
  sinks 1 nA / 100 nA, from a `dc` sweep of that rail from 0 → 3.63 V. This is
  the quantitative form of `design/por_output_chain.md`'s *"begins conducting
  from the very first millivolt of VDD"* claim. Also supply-axis-independent
  (fixed 0–3.63 V sweep regardless of corner supply).

Full extraction method, physicality guards (`isup_a`/`isup_b`/`izero_b`/
`ia_flat_n05l25`), and why a `dc` sweep (not a transient ramp) is sound here
are documented in `experiment.json`'s own `notes`.

## Record

**[`records/20260909-232337-c7b9b94.md`](records/20260909-232337-c7b9b94.md)**
(JSON twin: `records/20260909-232337-c7b9b94.json`) — full 45-point PVT matrix
(5 process × 3 temperature × 3 supply), **overall: PASS**. Every corner
converged, every physicality guard held, both corner-sensitivity spread
checks passed (the harness is provably corner-aware, not repeating one point
45 times). PDK: sky130A @ open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
(matches `sim/pdk.json`). Not a `spec/target-spec.md` claim — that file does
not exist yet (`spec/porting-plan.md` §4 item 4).

### Vth (constant-current extraction, linear region, `VDS` = 100 mV)

| Process | Temp (°C) | Vth n05l25 (V) | Vth n05l8 (V) | Vth n03l08 (V) |
|---|---|---|---|---|
| tt | -40 | 0.1955 | 0.1915 | 0.0635 |
| tt | 27 | 0.1255 | 0.1215 | -0.0145 |
| tt | 125 | 0.0205 | 0.0175 | -0.1245 |
| ss | -40 | 0.2185 | 0.2145 | 0.1215 |
| ss | 27 | 0.1485 | 0.1455 | 0.0435 |
| ss | 125 | 0.0445 | 0.0425 | -0.0665 |
| ff | -40 | 0.1725 | 0.1675 | 0.0085 |
| ff | 27 | 0.1015 | 0.0975 | -0.0695 |
| ff | 125 | -0.0045 | -0.0075 | -0.1795 |
| sf | -40 | 0.1515 | 0.1465 | -0.0305 |
| sf | 27 | 0.0815 | 0.0765 | -0.1095 |
| sf | 125 | -0.0245 | -0.0275 | -0.2205 |
| fs | -40 | 0.2395 | 0.2365 | 0.1585 |
| fs | 27 | 0.1695 | 0.1665 | 0.0805 |
| fs | 125 | 0.0645 | 0.0635 | -0.0285 |

**Vth spread**: `n05l25` ranges −24.5 mV (`sf`/125 °C) to +239.5 mV (`fs`/−40 °C),
a 264 mV window (harness's own corner-sensitivity guard requires ≥ 50 mV and
observed 264 mV — PASS). `n03l08` ranges −220.5 mV to +158.5 mV, a wider
423 mV window — consistent with it being a shorter, more process-sensitive
bin. All three geometries go through zero (i.e. some corners are genuinely
depletion-mode, others enhancement-mode) inside the PVT envelope: at 125 °C
every geometry in every process corner except `ss`/`fs` reads negative Vth.
This is the expected behavior of a near-zero-`Vt` device class, not an
artifact — it is exactly why `MASSIST`'s gate-tied-to-`VDD` connection was
chosen: the device conducts across essentially the whole PVT envelope
regardless of sign.

### Assist-onset voltage (rail voltage at which a `MASSIST`-wired device first sinks the stated current)

| Process | Temp (°C) | V@1nA n05l25 (V) | V@100nA n05l25 (V) | V@1nA n05l8 (V) | V@100nA n05l8 (V) | V@1nA n03l08 (V) | V@100nA n03l08 (V) |
|---|---|---|---|---|---|---|---|
| tt | -40 | 0.1525 | 0.3365 | 0.1155 | 0.2635 | 0.0035 | 0.0905 |
| tt | 27 | 0.0715 | 0.2995 | 0.0335 | 0.2125 | 0.0005 | 0.0375 |
| tt | 125 | 0.0125 | 0.2445 | 0.0045 | 0.1415 | 0.0005 | 0.0145 |
| ss | -40 | 0.1755 | 0.3625 | 0.1385 | 0.2875 | 0.0195 | 0.1425 |
| ss | 27 | 0.0945 | 0.3255 | 0.0515 | 0.2375 | 0.0015 | 0.0765 |
| ss | 125 | 0.0185 | 0.2705 | 0.0075 | 0.1645 | 0.0005 | 0.0265 |
| ff | -40 | 0.1305 | 0.3115 | 0.0915 | 0.2395 | 0.0005 | 0.0455 |
| ff | 27 | 0.0505 | 0.2735 | 0.0215 | 0.1885 | 0.0005 | 0.0175 |
| ff | 125 | 0.0095 | 0.2195 | 0.0035 | 0.1215 | 0.0005 | 0.0085 |
| sf | -40 | 0.1095 | 0.2925 | 0.0705 | 0.2185 | 0.0005 | 0.0245 |
| sf | 27 | 0.0355 | 0.2555 | 0.0145 | 0.1685 | 0.0005 | 0.0115 |
| sf | 125 | 0.0075 | 0.2055 | 0.0025 | 0.1075 | 0.0005 | 0.0075 |
| fs | -40 | 0.1965 | 0.3805 | 0.1605 | 0.3085 | 0.0455 | 0.1755 |
| fs | 27 | 0.1145 | 0.3435 | 0.0705 | 0.2575 | 0.0055 | 0.1085 |
| fs | 125 | 0.0245 | 0.2865 | 0.0095 | 0.1825 | 0.0005 | 0.0385 |

**Worst case (slowest onset)** at the `MASSIST` bin (`n05l25`): `fs`/−40 °C —
196.5 mV to reach 1 nA, 380.5 mV to reach 100 nA. Best case: `sf`/125 °C —
7.5 mV / 205.5 mV. `n03l08` reaches 1 nA at ≤ 5.5 mV at every corner except
`fs`/−40 °C (45.5 mV) — substantiating `design/por_output_chain.md`'s
"conducts from the very first millivolt" claim for the drawn flavor, with the
`fs`/−40 °C corner as the one point where "very first millivolt" is closer to
"first ~200 mV" for the 100 nA criterion.

### MASSIST-condition static current (gate AND drain at VDD, source/bulk at VSS) — full 45-point grid

| Process | Temp (°C) | Supply (V) | ion n05l25 (A) | ion n05l8 (A) | ion n03l08 (A) |
|---|---|---|---|---|---|
| tt | -40 | 2.97 | 2.009e-05 | 6.524e-05 | 0.0001865 |
| tt | -40 | 3.30 | 2.483e-05 | 7.932e-05 | 0.0002106 |
| tt | -40 | 3.63 | 3.003e-05 | 9.446e-05 | 0.0002346 |
| tt | 27 | 2.97 | 1.446e-05 | 4.785e-05 | 0.0001635 |
| tt | 27 | 3.30 | 1.775e-05 | 5.79e-05 | 0.0001851 |
| tt | 27 | 3.63 | 2.135e-05 | 6.87e-05 | 0.0002065 |
| tt | 125 | 2.97 | 1.009e-05 | 3.374e-05 | 0.0001371 |
| tt | 125 | 3.30 | 1.225e-05 | 4.048e-05 | 0.0001557 |
| tt | 125 | 3.63 | 1.462e-05 | 4.77e-05 | 0.0001744 |
| ss | -40 | 2.97 | 1.879e-05 | 6.108e-05 | 0.0001618 |
| ss | -40 | 3.30 | 2.325e-05 | 7.44e-05 | 0.0001833 |
| ss | -40 | 3.63 | 2.817e-05 | 8.875e-05 | 0.0002047 |
| ss | 27 | 2.97 | 1.352e-05 | 4.478e-05 | 0.0001419 |
| ss | 27 | 3.30 | 1.662e-05 | 5.429e-05 | 0.0001611 |
| ss | 27 | 3.63 | 2.003e-05 | 6.452e-05 | 0.0001803 |
| ss | 125 | 2.97 | 9.438e-06 | 3.158e-05 | 0.0001191 |
| ss | 125 | 3.30 | 1.148e-05 | 3.795e-05 | 0.0001357 |
| ss | 125 | 3.63 | 1.372e-05 | 4.479e-05 | 0.0001523 |
| ff | -40 | 2.97 | 2.143e-05 | 6.951e-05 | 0.0002122 |
| ff | -40 | 3.30 | 2.644e-05 | 8.435e-05 | 0.0002389 |
| **ff** | **-40** | **3.63** | **3.194e-05** | **0.0001003** | **0.0002655** |
| ff | 27 | 2.97 | 1.542e-05 | 5.099e-05 | 0.0001861 |
| ff | 27 | 3.30 | 1.89e-05 | 6.159e-05 | 0.00021 |
| ff | 27 | 3.63 | 2.27e-05 | 7.297e-05 | 0.0002338 |
| ff | 125 | 2.97 | 1.076e-05 | 3.595e-05 | 0.000156 |
| ff | 125 | 3.30 | 1.304e-05 | 4.306e-05 | 0.0001766 |
| ff | 125 | 3.63 | 1.554e-05 | 5.067e-05 | 0.0001974 |
| sf | -40 | 2.97 | 2.08e-05 | 6.737e-05 | 0.0001954 |
| sf | -40 | 3.30 | 2.562e-05 | 8.165e-05 | 0.0002196 |
| sf | -40 | 3.63 | 3.091e-05 | 9.697e-05 | 0.0002437 |
| sf | 27 | 2.97 | 1.496e-05 | 4.94e-05 | 0.0001717 |
| sf | 27 | 3.30 | 1.83e-05 | 5.96e-05 | 0.0001934 |
| sf | 27 | 3.63 | 2.197e-05 | 7.054e-05 | 0.000215 |
| sf | 125 | 2.97 | 1.043e-05 | 3.482e-05 | 0.0001441 |
| sf | 125 | 3.30 | 1.263e-05 | 4.165e-05 | 0.0001629 |
| sf | 125 | 3.63 | 1.503e-05 | 4.896e-05 | 0.0001817 |
| fs | -40 | 2.97 | 1.94e-05 | 6.314e-05 | 0.0001777 |
| fs | -40 | 3.30 | 2.405e-05 | 7.703e-05 | 0.0002017 |
| fs | -40 | 3.63 | 2.917e-05 | 9.198e-05 | 0.0002255 |
| fs | 27 | 2.97 | 1.397e-05 | 4.631e-05 | 0.0001555 |
| fs | 27 | 3.30 | 1.72e-05 | 5.622e-05 | 0.0001768 |
| fs | 27 | 3.63 | 2.075e-05 | 6.689e-05 | 0.0001982 |
| fs | 125 | 2.97 | 9.755e-06 | 3.268e-05 | 0.0001302 |
| fs | 125 | 3.30 | 1.188e-05 | 3.932e-05 | 0.0001487 |
| fs | 125 | 3.63 | 1.421e-05 | 4.645e-05 | 0.0001672 |

**Worst corner (bold, every geometry): `ff` / −40 °C / 3.63 V.** Fast process
corner, cold, max supply — the expected worst case for a device whose gate is
permanently tied to `VDD` (more current = more `VOV` at higher `VDD`, and
`ff`/cold is the highest-mobility, lowest-`Vt` corner combination reached by
this matrix). Best case (least current): `ss` / 125 °C / 2.97 V, for the
opposite reason.

| Bin | Worst-case `ion` | Corner | Nominal (`tt`/27 °C/3.3 V) | Best-case |
|---|---|---|---|---|
| `n05l25` (`MASSIST`'s drawn bin) | **31.94 µA** | `ff`/−40 °C/3.63 V | 17.75 µA | 9.44 µA (`ss`/125 °C/2.97 V) |
| `n05l8` | 100.3 µA | `ff`/−40 °C/3.63 V | 57.9 µA | 31.58 µA (`ss`/125 °C/2.97 V) |
| `n03l08` | 265.5 µA | `ff`/−40 °C/3.63 V | 185.1 µA | 119.1 µA (`ss`/125 °C/2.97 V) |

`n05l25` (`MASSIST`'s own drawn bin) is confirmed to be the *lowest*-current
bin of the three characterized — consistent with `design/por_output_chain.md`
already choosing the longest-channel bin available. `n03l08`, the alternative
flavor's best (weakest) available bin, costs roughly **8×** `n05l25`'s
current at every corner: `nfet_03v3_nvt`'s entire menu is short-channel
(`L` ≤ 0.8 µm), so there is no bin of that flavor competitive with `n05l25` on
static current — this is the number that decides §2.6 on static-current
grounds, at the geometry each flavor can actually be drawn at, not a
hypothetical matched `W`/`L` neither menu offers.

### Off-state leakage reference (`VGS` = 0, same drain bias)

Not `MASSIST`'s operating point — for reference only, showing how much of
`ion_*` above is gate drive vs. device-class floor. Worst case (highest
leakage) per bin, full 45-point data in the record's JSON:

| Bin | Worst-case `ioff` | Corner |
|---|---|---|
| `n05l25` | 6.73 nA | `sf`/125 °C/3.63 V |
| `n05l8` | 23.3 nA | `sf`/125 °C/3.63 V |
| `n03l08` | 5.24 µA | `sf`/125 °C/3.63 V |

`ioff` is 3–5 orders of magnitude below `ion` at every corner for `n05l25`/
`n05l8` (confirming `ion` is genuinely gate-driven, not leakage-dominated) but
only ~1.5 orders of magnitude below `ion` for `n03l08` — consistent with that
bin's near-zero/negative Vth at hot corners.

## Against the README's DRAFT `Iq (block total) < 20 µA` row (stretch `< 5 µA`)

**`MASSIST`'s own static current alone — a single leg, not the block total —
already fails the DRAFT budget at its worst corner, and consumes most of the
budget even at the nominal corner:**

- Worst corner (`ff`/−40 °C/3.63 V): **31.94 µA** > 20 µA DRAFT ceiling (and
  > 5 µA stretch ceiling) — **FAIL**, on this one leg alone.
- Nominal corner (`tt`/27 °C/3.3 V): **17.75 µA** — under the 20 µA DRAFT
  ceiling but at ~89 % of it, from a single always-on leg, before any other
  block current (deglitch filter, one-shot, trip detector, release NAND,
  `temp_core`) is added. Also > 5 µA stretch ceiling.
- Best corner (`ss`/125 °C/2.97 V): 9.44 µA — still > 5 µA stretch ceiling.

**This is a finding, not a blocker** (`sim/README.md`'s house convention: a
FAIL a full PVT sweep actually finds is kept, not loosened). Two caveats
against over-reading it, both already on record:

1. `spec/porting-plan.md` §2.7 separately flags the README's DRAFT row itself
   as *"likely a mislabeled carryover"* — in gf180's own ratified spec, the
   `<20 µA`/`<5 µA` pair is `temp-iq` (the sensor's incremental current), not
   the block total; the block total (`iq-total`) is a separately ratified
   `<21 µA` figure, and `por-iq` (the released, sensor-disabled state
   `MASSIST` actually lives in) is a third, independently re-cost `<3.0 µA`
   row. Against *that* correctly-labeled `por-iq` figure, `MASSIST` alone
   (17.75–31.94 µA) is 6×–10× over budget at every corner in this matrix, not
   just the worst one — a sharper finding than the DRAFT row comparison
   above, but one this issue reports against the row that actually exists in
   this repo today, per its own Scope; the §2.7 relabeling and a corrected
   `por-iq` ceiling are `spec/target-spec.md` work (§4 item 4), out of scope
   here.
2. This experiment characterizes the *device*, wired exactly as `MASSIST` is
   wired, in isolation — it is a lower bound on, not a measurement of,
   `por_output_chain`'s actual quiescent current, which also includes the
   release NAND's own below-floor leakage and any other always-on paths.

**Standing of the `nfet_05v0_nvt` choice**: on the evidence here, the
*device-class and flavor* choice stands — `n05l25` is confirmed as the
lowest-static-current bin available in either flavor's menu (≈8× cheaper than
`nfet_03v3_nvt`'s best competing bin), and no bin of the alternative flavor
would improve on it. What does **not** stand, on this evidence, is the DRAFT
Iq budget itself (whichever labeling is used) against a device that is
*always on by construction* — that is a sizing/topology question (a smaller
`MASSIST`, a switched keeper, or a corrected/relabeled Iq ceiling), not a
flavor question, and is explicitly out of scope for this issue (see
`design/por_output_chain.md`'s dated subsection below and file a decision
record per this issue's own "Out of scope" list if a resizing is pursued).

## Reproducibility

- PDK pin: `sim/pdk.json` (`c6d73a35f524070e85faff4a6a9eef49553ebc2b`) —
  matched exactly by the installed PDK for this record (not a mismatch
  fallback).
- Testbench: [`testbench/tb_native_device_char.sch`](testbench/tb_native_device_char.sch).
- Manifest: [`experiment.json`](experiment.json) — full measurement
  expressions, bounds, and rationale for every physicality/structural guard
  are documented inline in its `notes`.
- Netlist snapshot: `netlist-snapshots/20260909-232337-c7b9b94.spice`.
- Raw per-corner logs (exact deck + ngspice stdout/stderr for all 45 points):
  `corners/20260909-232337-c7b9b94/`.
