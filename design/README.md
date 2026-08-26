# design/ — xschem sources and netlist export

Schematic entry for the temperature-sensor + power-on-reset block, in xschem,
against the sky130 PDK. This directory is the **source of truth for the
block's electrical interface**: `sim/` testbenches and (later) `layout/` LVS
both consume the netlists exported from here.

> **Status: the hierarchy is complete at schematic level.** Tooling,
> `bias_core` (issue #6), `temp_core` (issue #7), `por_comparator` (issue
> #8), `por_output_chain` (issue #9, including the POR startup-assist
> pull-down) and now the top-level assembly `temp_por_top` (issue #10) have
> all landed — every sibling of decomposition #5. The ratified top-level
> pinout below is therefore a real, checkable `.subckt`, and `python3
> design/netlist.py --check` asserts it on every run. What remains is
> verification and layout, not schematic entry: absolute thresholds,
> timings and sizings in the leaf cells are still first-order placeholders
> pending sky130 device characterization (CLAUDE.md: thresholds do not
> port). See [Cell status](#cell-status).

This is a port of
[`2AMLogic/gf180-temp-por`](https://github.com/2AMLogic/gf180-temp-por)'s own
`design/` onto sky130, per `spec/porting-plan.md` and
[DR-002](../spec/decision-records/DR-002-architecture-carryover.md)
(architecture carryover) / [DR-001](../spec/decision-records/DR-001-supply-flavor.md)
(device-flavor mapping). Per CLAUDE.md, the PDK is the variable, not the
design: start from gf180's own schematics and decision records rather than
from a blank page, and never carry a numeric threshold across without
re-deriving it against sky130 models.

## Top-level pinout (ratified, and asserted on every export)

`temp_por_top`, in the port order `spec/porting-plan.md` §2.8 reconciles and
this repo's own decision records fix. This is the live `.subckt` port list
of [`netlist/temp_por_top.spice`](netlist/temp_por_top.spice) — `design/netlist.py`
asserts this exact list, in this exact order, on every `--check` run:

| Pin      | Dir   | Meaning                                              | Source |
| -------- | ----- | ---------------------------------------------------- | ------ |
| `VDD`    | inout | Supply, 3.3 V nominal ±10 % (2.97–3.63 V steady state), sky130 5V I/O-class devices (`g5v0d10v5`) | [DR-001](../spec/decision-records/DR-001-supply-flavor.md) |
| `VSS`    | inout | Ground                                                | DR-001 |
| `PTAT`   | out   | Analog PTAT output                                    | [DR-002](../spec/decision-records/DR-002-architecture-carryover.md) |
| `CTAT`   | out   | Analog CTAT output                                    | DR-002 |
| `RESETn` | out   | Reset, **active low**, **push-pull**                  | DR-002 |

No trim/config/programming pins and no digital temperature interface in
wave 1 — both carried unchanged from gf180's own DR-002/DR-003-equivalent
architecture decisions (`spec/porting-plan.md` §1.1). `python3
design/netlist.py --check` fails if this port list or its order ever drifts
— changing the pinout means changing the decision record first, not the
assertion (see [Exporting the netlist](#exporting-the-netlist)).

## Hierarchy

Five cells, matching gf180-temp-por's **actual** convention (not the 6-block
description in an earlier draft of
[DR-002](../spec/decision-records/DR-002-architecture-carryover.md) — see
#5/#6 for the verified correction: gf180's own `design/` has 5 xschem
sources, and two DR-005 leaves — the shared core's startup kick and the POR
startup-assist pull-down — are deliberately *not* separate cells):

```
temp_por_top                     top level, the ratified pad interface        issue #10
├── xbias  bias_core             shared bias / reference core                 issue #6
├── xtemp  temp_core             PTAT/CTAT sensing core                       issue #7
├── xcmp   por_comparator        threshold comparator + hysteresis            issue #8
└── xpor   por_output_chain      deglitch, pulse, output stage,
                                  + POR startup-assist pull-down               issue #9
```

`temp_por_top` is **assembly only**: it instantiates those four cells, names
the nets between them, and adds no devices of its own (`design/temp_por_top.sch`
carries the same table as an in-schematic note). Every W/L, trip point and
timing element lives in a leaf cell.

Internal nets (driver/consumer contract carried from gf180's DR-010, honoured
by every cell in the hierarchy — see `design/temp_por_top.sch`'s own note for
how each one is wired at the top level):

| Net       | Driver           | Consumers                        | Why |
| --------- | ---------------- | --------------------------------- | --- |
| `IBIAS`   | `bias_core`      | `temp_core`, `por_comparator`, `por_output_chain` | one shared bias core, amortizing Iq and area (DR-005/DR-002). A disabled consumer must present high impedance to this net, never clamp it, per gf180's own DR-010 lockup finding. Preserved structurally by the assembly: the top level wires `IBIAS` as a plain shared net (one driver, three consumers) with no switch, clamp or added load; the only consumer with an enable is `temp_core`, which leaves `IBIAS` high-Z when `EN` is low ([`temp_core.md`](temp_core.md), `EN` row). |
| `VREF`    | `bias_core`      | `por_comparator`                 | absolute reference; the threshold is a voltage, not a rail fraction |
| `BIAS_OK` | `bias_core`      | `por_comparator`                 | gates the authoritative release decision (DR-002 startup ordering) |
| `POR_RAW` | `por_comparator` | `por_output_chain`               | hysteresis is the comparator's job; deglitch/pulse/drive are the output chain's |
| `RESETn`  | `por_output_chain` | top-level pad, `temp_core.EN`  | the sensor is enabled only after POR releases, keeping it out of the startup chicken-and-egg problem |

## Exporting the netlist

```bash
python3 design/netlist.py            # regenerate design/netlist/*.spice
python3 design/netlist.py --check    # verify committed netlists are current
python3 design/netlist.py --cell temp_core -v
```

Requirements: `xschem` on `PATH` (this repo has been verified against 3.4.7)
plus the sky130A PDK installed — `design/xschemrc` resolves it via
`PDK_ROOT`/`PDK` env vars, falling back to the volare default
(`~/.volare/sky130A`) if unset, exactly as `design/netlist.py`'s own
`find_pdk()` does (see both files' docstrings — this is issue #6's chosen
option (b): inline PDK discovery rather than a `sim/harness/pdk.py`-style
shared module, deferred to `spec/porting-plan.md` §4 item 1). No PDK path is
ever baked into a netlist or into this directory.

> **sky130 device-parameter unit convention.** `sky130_fd_pr__*` primitive
> subcircuits (MOS, resistor, cap) take `W`/`L` (and `r_width`/`r_length`) as
> **bare micron-scale numbers**, not SPICE's usual meter-with-suffix
> convention — i.e. `W=8` (eight microns), never `W=8u` (which ngspice reads
> as 8×10⁻⁶ **meters**, six orders of magnitude too small, and which fails
> outright for the resistor primitives with a `NaN`-producing model
> expression rather than silently misbehaving). This differs from gf180mcu's
> own device library, which does use the `u`-suffixed convention — a
> PDK-to-PDK gotcha worth stating explicitly since it is exactly the kind of
> thing a mechanical device-symbol port silently gets wrong. Confirmed
> empirically against both a standalone `sky130_fd_pr__res_xhigh_po` deck and
> `design/netlist/bias_core.spice` itself (issue #6): the bare-number form
> solves; the `u`-suffixed form either produces `NaN`s (resistor) or fails
> model lookup outright (MOS).

Under the hood, per cell:

```bash
xschem -x -q -n -s -r --rcfile design/xschemrc -o <outdir> design/<cell>.sch
```

`-x` batch (no X11), `-q` quit when done, `-n -s` netlist as SPICE, `-r` no
readline. `design/xschemrc` sets `top_is_subckt 1`: **every** cell —
`temp_por_top` included — netlists as a `.subckt`, never as a flat
simulation deck. Cells here are blocks that testbenches instantiate; the
deck belongs to the testbench.

`netlist.py` then rewrites the absolute paths xschem records in its
`sch_path`/`sym_path` comments to repo-relative form and prepends a
provenance header, making the export **deterministic**: the same sources
produce byte-identical netlists on any machine.

### What `--check` verifies

1. **Committed netlists are current** — regenerating into a temp directory
   reproduces `design/netlist/*.spice` byte-for-byte.
2. **The top-level pinout matches the ratified interface** — exact port list
   and order, `VDD VSS PTAT CTAT RESETn` (live since `temp_por_top` landed
   in issue #10).
3. **Symbol pins match schematic ports**, per cell, in order — checked for
   every committed cell, `temp_por_top` included.
4. **Every sub-circuit is instantiated in the top level** with the right
   number of nets — all four leaf cells, each connected with exactly as many
   nets as it has ports.

`--check` exits non-zero on any failure and prints the offending diff.

## Using the netlists from a testbench

`design/netlist/` holds one file per cell. The four leaf files —
`bias_core.spice`, `temp_core.spice`, `por_comparator.spice` and
`por_output_chain.spice` — are each a single `.subckt`, so a testbench can
target one on its own:

```spice
.include design/netlist/bias_core.spice
xdut VDD VSS IBIAS VREF BIAS_OK bias_core

.include design/netlist/por_comparator.spice
xcmp VDD VSS IBIAS VREF BIAS_OK POR_RAW por_comparator
```

`temp_core` consumes `bias_core`'s `IBIAS` output, so a testbench exercising
`temp_core` includes both and shares the net:

```spice
.include design/netlist/bias_core.spice
.include design/netlist/temp_core.spice
xbias VDD VSS IBIAS VREF BIAS_OK bias_core
xdut   VDD VSS IBIAS EN PTAT CTAT temp_core
```

`por_output_chain` likewise consumes `bias_core`'s `IBIAS` output (and, in a
full assembly, `por_comparator`'s `POR_RAW`):

```spice
.include design/netlist/bias_core.spice
.include design/netlist/por_output_chain.spice
xbias VDD VSS IBIAS VREF BIAS_OK bias_core
xdut  VDD VSS IBIAS POR_RAW RESETn por_output_chain
```

`temp_por_top.spice` (issue #10) carries the **whole hierarchy** — the top
cell plus every sub-circuit definition it instantiates — so a block-level
testbench includes exactly that one file and drives only the five ratified
pads:

```spice
.include design/netlist/temp_por_top.spice
xdut VDD VSS PTAT CTAT RESETn temp_por_top
```

Include exactly one of `temp_por_top.spice` **or** a set of single-cell
files per deck, never both: the former already defines every sub-circuit's
`.subckt`, and redefining one is an ngspice error.

## Working in the GUI

```bash
xschem --rcfile design/xschemrc design/temp_core.sch
```

Conventions this hierarchy was built to, and that any later edit to it must
keep:

- **PDK devices are referenced as `sky130_fd_pr/<device>.sym`** (e.g.
  `sky130_fd_pr/nfet_g5v0d10v5.sym`, `sky130_fd_pr/pnp_05v5.sym`,
  `sky130_fd_pr/res_xhigh_po.sym`), resolved against the PDK's own xschem
  library (sourced by `design/xschemrc`). Never write an absolute PDK path
  into a schematic.
- **Project cells are referenced by bare name** (`bias_core.sym`), resolved
  against `design/`.
- **Remember the unit convention** above — bare micron numbers on `W`/`L`,
  no `u` suffix, for every `sky130_fd_pr__*` instance.
- **Do not hand-edit `design/netlist/*.spice`.** Edit the schematic and
  re-run the export; `--check` will catch it if you forget.
- **Keep symbol pins and schematic ports in the same order.** When you add a
  port, add it to both the `.sch` and the `.sym`.
- Re-run `python3 design/netlist.py` and commit the regenerated netlists
  with the schematic change, so the netlist in the tree always matches the
  sources.

## Cell status

| Cell               | Landed by | Status | Device mapping / sizing note |
| ------------------ | --------- | ------ | ----------------------------- |
| `bias_core`        | #6 | **ported** — [`bias_core.md`](bias_core.md) | Topology and wiring ported mechanically from gf180's ratified `bias_core`; every `W`/`L` carried at the same drawn geometry (so ratio-derived quantities are exact), absolute sizing is first-order/placeholder pending sky130 device characterization. DC operating-point smoke test solves at multiple corners — see `bias_core.md`, "Verification done for this issue". |
| `temp_core`        | #7 | **ported** — [`temp_core.md`](temp_core.md) | Topology and wiring ported mechanically from gf180's ratified `temp_core`; every `W`/`L` carried at the same drawn geometry. gf180's 6-bit trim ladder is simplified to a single trim node (`PTAT_TRIM`) per issue #7's scope — see `temp_core.md`, "Trim mechanism". Full-PVT `tran … uic` cold-start branch-selection evidence (alongside `bias_core`, `EN` both immediate and DR-002-delayed) supersedes the original cold-`.op` spot check — see `temp_core.md`, "Branch selection: full-PVT transient evidence (issue #22)". |
| `por_comparator`   | #8 | **ported** | Topology and wiring ported mechanically from gf180's ratified `por_comparator`: resistor-divided VDD tap (`RTOP`/`RBOT`/`RHYS`, all `res_xhigh_po`) compared against `VREF` by an NMOS-input 5T OTA, with `POR_RAW`-gated resistor-network positive feedback (`MHSW`) as the hysteresis mechanism (DR-002). Every `W`/`L` and resistor drawn length carried at the same drawn geometry as gf180 (ratio-derived VPOR-rise/VPOR-fall/V_hys expressions are exact); absolute trip points are first-order/placeholder pending sky130 device characterization and a real `bias_core` `VREF` — no numeric threshold carried from gf180 (CLAUDE.md). Informal DC operating-point check (not committed as a `sim/` artifact) confirms `POR_RAW` tracks `SNS` vs. `VREF` in the expected direction and clamps low when `BIAS_OK` is low. |
| `por_output_chain` | #9 | **ported** — [`por_output_chain.md`](por_output_chain.md) | Topology and wiring ported mechanically from gf180's ratified `por_output_chain`: deglitch filter, current-starved one-shot, nA-limited trip detector, and a release NAND + push-pull output stage whose below-floor leakage-divider default **is** the POR startup-assist pull-down (DR-002) — verified in shape against gf180's own schematic, not a separate leaf cell. Adds one device beyond gf180's own cell: `MASSIST`, a `sky130_fd_pr__nfet_05v0_nvt` near-zero-`Vt` pull-down gated directly from `VDD`/`VSS`, satisfying this issue's own device-mapping table (gf180's own DR-005 scoped a native/zero-`Vt` leg as availability-contingent and its own PDK never confirmed one; sky130's is confirmed) — see `por_output_chain.md`, "Why `MASSIST` exists". CDG/CTIM (deglitch dwell / one-shot pulse-width capacitors) are first-order placeholder timing elements, not committed durations (CLAUDE.md). DC + transient smoke tests (assert/delayed-release/reassert behavior, and a 0→3.3 V below-floor ramp with `POR_RAW` held low) solve cleanly — see `por_output_chain.md`, "Verification done for this issue". |
| `temp_por_top`     | #10 | **assembled** | Block-level assembly, ported from gf180's own `temp_por_top.sch`: instantiates the four leaf cells (`xbias`/`xtemp`/`xcmp`/`xpor`) and names the internal nets per the table above — **no devices of its own**. `IBIAS` is wired as a plain shared net (one driver, three consumers, no switch/clamp/added load), preserving gf180's DR-010 liveness contract structurally; `RESETn` drives both the pad and `temp_core.EN`, so the sensor comes up only after POR releases. `design/netlist.py --check` now asserts the ratified 5-pad port list, the symbol/schematic port agreement for all five cells, and that each leaf is instantiated with the right net count. Absolute trip points, timings and sizings remain whatever the leaf cells say they are — this issue changed no electrical value (CLAUDE.md: thresholds do not port). |

When editing a cell — or adding one: follow the same pattern issue #6
established — port the gf180 schematic device-by-device per the mapping
table in that cell's own `design/<cell>.md` (see `spec/porting-plan.md` §2.2
for the device menu), remember the bare-micron-number unit convention above,
run `python3 design/netlist.py --cell <cell>` to verify it netlists cleanly,
and commit the regenerated `design/netlist/*.spice` alongside the schematic.
A change to any leaf cell's port list is also a change to `temp_por_top` —
`--check` will fail until the assembly is rewired to match.
