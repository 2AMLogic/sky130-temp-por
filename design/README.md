# design/ — xschem sources and netlist export

Schematic entry for the temperature-sensor + power-on-reset block, in xschem,
against the sky130 PDK. This directory is the **source of truth for the
block's electrical interface**: `sim/` testbenches and (later) `layout/` LVS
both consume the netlists exported from here.

> **Status: tooling, `bias_core` (issue #6), `temp_core` (issue #7), and
> `por_comparator` (issue #8) have landed.** The remaining two cells and the
> top-level assembly are tracked as siblings in the same decomposition (#5):
> `por_output_chain` (#9, including the POR startup-assist leg), and
> `temp_por_top` (#10, the block-level assembly — only once it lands does
> the ratified top-level pinout below become a real, checkable `.subckt`).
> See [Placeholder status](#placeholder-status).

This is a port of
[`2AMLogic/gf180-temp-por`](https://github.com/2AMLogic/gf180-temp-por)'s own
`design/` onto sky130, per `spec/porting-plan.md` and
[DR-002](../spec/decision-records/DR-002-architecture-carryover.md)
(architecture carryover) / [DR-001](../spec/decision-records/DR-001-supply-flavor.md)
(device-flavor mapping). Per CLAUDE.md, the PDK is the variable, not the
design: start from gf180's own schematics and decision records rather than
from a blank page, and never carry a numeric threshold across without
re-deriving it against sky130 models.

## Top-level pinout (ratified shape, not yet a real cell)

`temp_por_top`, in the port order `spec/porting-plan.md` §2.8 reconciles and
this repo's own decision records fix — **this cell does not exist yet**
(issue #10); the table documents the interface `design/netlist.py` will
assert once it does:

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
design/netlist.py --check` will assert this exact port list once
`temp_por_top.sch` exists; until then it has nothing to check the top-level
pinout against and skips that half of the invariant (see
[Exporting the netlist](#exporting-the-netlist)).

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
├── xtemp  temp_core             PTAT/CTAT sensing core                       issue #7  (this issue)
├── xcmp   por_comparator        threshold comparator + hysteresis            issue #8
└── xpor   por_output_chain      deglitch, pulse, output stage,
                                  + POR startup-assist pull-down               issue #9
```

Internal nets (driver/consumer contract carried from gf180's DR-010, to be
honoured by each sibling cell as it lands):

| Net       | Driver           | Consumers                        | Why |
| --------- | ---------------- | --------------------------------- | --- |
| `IBIAS`   | `bias_core`      | `temp_core`, `por_comparator`, `por_output_chain` | one shared bias core, amortizing Iq and area (DR-005/DR-002). A disabled consumer must present high impedance to this net, never clamp it, per gf180's own DR-010 lockup finding — carried here as a contract for whichever sibling cell lands next. |
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
including the top, once it exists — netlists as a `.subckt`, never as a flat
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
   and order — **once `temp_por_top.sch` exists**; skipped until then (see
   `design/netlist.py`'s own docstring for why this issue defers that cell).
3. **Symbol pins match schematic ports**, per cell, in order — checked for
   every committed cell today, including `bias_core` and `temp_core`.
4. **Every sub-circuit is instantiated in the top level** with the right
   number of nets — once `temp_por_top.sch` exists.

`--check` exits non-zero on any failure and prints the offending diff.

## Using the netlists from a testbench

`design/netlist/` holds one file per cell — `bias_core.spice`,
`temp_core.spice`, and `por_comparator.spice` so far, each a single
`.subckt`, so a testbench can target one on its own:

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

Once `temp_por_top.sch` lands (issue #10), `temp_por_top.spice` will carry
the whole hierarchy (the top cell plus every sub-circuit definition it
instantiates) — include exactly one of `temp_por_top.spice` or a single
sub-circuit file per deck, never both (the former already redefines every
sub-circuit's `.subckt`).

## Working in the GUI

```bash
xschem --rcfile design/xschemrc design/temp_core.sch
```

Conventions for the sibling-cell issues that fill the rest of this hierarchy
in:

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

## Placeholder status

| Cell               | Landed by | Status | Device mapping / sizing note |
| ------------------ | --------- | ------ | ----------------------------- |
| `bias_core`        | #6 | **ported** — [`bias_core.md`](bias_core.md) | Topology and wiring ported mechanically from gf180's ratified `bias_core`; every `W`/`L` carried at the same drawn geometry (so ratio-derived quantities are exact), absolute sizing is first-order/placeholder pending sky130 device characterization. DC operating-point smoke test solves at multiple corners — see `bias_core.md`, "Verification done for this issue". |
| `temp_core`        | #7 (this issue) | **ported** — [`temp_core.md`](temp_core.md) | Topology and wiring ported mechanically from gf180's ratified `temp_core`; every `W`/`L` carried at the same drawn geometry. gf180's 6-bit trim ladder is simplified to a single trim node (`PTAT_TRIM`) per issue #7's scope — see `temp_core.md`, "Trim mechanism". DC operating-point smoke test (alongside `bias_core`) solves at a 3x3 corner/temperature grid — see `temp_core.md`, "Verification done for this issue". |
| `por_comparator`   | #8 | **ported** | Topology and wiring ported mechanically from gf180's ratified `por_comparator`: resistor-divided VDD tap (`RTOP`/`RBOT`/`RHYS`, all `res_xhigh_po`) compared against `VREF` by an NMOS-input 5T OTA, with `POR_RAW`-gated resistor-network positive feedback (`MHSW`) as the hysteresis mechanism (DR-002). Every `W`/`L` and resistor drawn length carried at the same drawn geometry as gf180 (ratio-derived VPOR-rise/VPOR-fall/V_hys expressions are exact); absolute trip points are first-order/placeholder pending sky130 device characterization and a real `bias_core` `VREF` — no numeric threshold carried from gf180 (CLAUDE.md). Informal DC operating-point check (not committed as a `sim/` artifact) confirms `POR_RAW` tracks `SNS` vs. `VREF` in the expected direction and clamps low when `BIAS_OK` is low. |
| `por_output_chain` | #9 | not started | also owns the POR startup-assist pull-down (DR-002) |
| `temp_por_top`     | #10 | not started | block-level assembly; only once this lands does `design/netlist.py --check` have a ratified top-level pinout to assert against |

When a sibling cell lands: follow the same pattern issue #6 established —
port the gf180 schematic device-by-device per the mapping table in that
cell's own `design/<cell>.md` (see `spec/porting-plan.md` §2.2 for the
device menu), remember the bare-micron-number unit convention above, run
`python3 design/netlist.py --cell <cell>` to verify it netlists cleanly, and
commit the regenerated `design/netlist/*.spice` alongside the schematic.
