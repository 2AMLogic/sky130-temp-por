# `temp_core` — PTAT/CTAT temperature-sensing core (sky130 port)

Sky130 port of
[gf180-temp-por's `design/temp_core.sch`](https://github.com/2AMLogic/gf180-temp-por/blob/main/design/temp_core.md)
(issue #9 there), landed by issue #7 here as sub-issue 2 of 5 of the
T1-item-1 decomposition (see #5), depending on `bias_core` (issue #6).
Topology per
[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md)
("plain, not chopped, single-point 25 °C gain trim"), carried into this repo
by [DR-002](../spec/decision-records/DR-002-architecture-carryover.md);
device mapping per `spec/porting-plan.md` §2.2 and
[DR-001](../spec/decision-records/DR-001-supply-flavor.md).

**This is a mechanical, first-order port, not a characterized design.** See
[Scope and what this is not](#scope-and-what-this-is-not) before reading
anything below as a verified number.

## What this cell is

Unchanged in shape from gf180's `temp_core`: a ΔVBE/VBE bandgap-style
temperature-sensing core, deliberately left uncompensated so the PTAT term
is published raw. An 8:1 emitter-area vertical-PNP pair (`XQ1` : 1x,
`XQ8A..XQ8H` : 8x in parallel) sets `DVBE = (kT/q)*ln(8)`; an error amplifier
forces `V(NA) = V(NB)` so the branch current is `I = DVBE/R1` (PTAT by
construction); a matched third mirror leg drops that same current through
`R2` (fixed) + `R2TRIM` (the wave-1 single-point trim leg — see
[Trim mechanism](#trim-mechanism-simplified-for-this-port) below) into `VSS`,
giving `V(PTAT) = ((R2+R2TRIM)/R1)*(kT/q)*ln(8)`. `V(CTAT)` is `XQ1`'s own
`VEB` (the same node the branch-A leg drives), tapped out through a series
isolation resistor (`XRISO`) so pad capacitance never loads the loop node
directly. The cell has its own startup-kick/enable-gating band (current-
referenced dead-loop detector, the same class of mechanism `bias_core` uses)
and disable clamps so a disabled cell floats cleanly rather than leaking.
Everything below is a direct translation of gf180's own `design/temp_core.md`
topology description onto sky130 devices; read that document for the full
circuit-theory argument — none of the *architecture* is device-specific, so
it is not re-derived here.

## Interface

| Pin | Dir | Meaning |
| --- | --- | --- |
| `VDD`, `VSS` | inout | 3.3 V nominal supply pair on sky130 5V I/O-class devices (`g5v0d10v5`), 2.97–3.63 V ([DR-001](../spec/decision-records/DR-001-supply-flavor.md)), matching `bias_core` |
| `IBIAS` | in | shared bias-mirror node from `bias_core`. Per [DR-010](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-010-shared-ibias-disabled-consumer-contract.md) (carried from gf180, documented on `bias_core`'s own interface too): this pin is **high-Z, never clamped**, when the cell is disabled — a clamp here would starve the shared node for the entire pre-POR window |
| `EN` | in | enable, active high. Intended to be driven from `RESETn` once `temp_por_top` exists (issue #10), so the sensor is enabled only after POR releases (DR-002 startup ordering) — wired here per issue #7's own guidance even though the driving `RESETn` signal is not yet a committed cell. `EN` low: mirror gate `PG` to `VDD`, local bias node `NBG` to `VSS`, `PTAT`/`CTAT` pulled to `VSS`, `IBIAS` left high-Z |
| `PTAT` | out | analog PTAT output ([DR-002](../spec/decision-records/DR-002-architecture-carryover.md)). No output buffer in this cell (gf180's own `temp_buffer` is a separate, not-yet-ported cell) — a consuming testbench must specify a high-impedance load |
| `CTAT` | out | analog CTAT output (DR-002) = `VEB` of `XQ1`, tapped through `XRISO` |

## Device mapping (`spec/porting-plan.md` §2.2 / DR-001)

| Role | gf180 device | sky130 device | Notes |
| --- | --- | --- | --- |
| Amplifier, mirror, startup-kick, enable-gating MOS | `pfet_03v3`/`nfet_03v3` | `sky130_fd_pr__pfet_g5v0d10v5`/`nfet_g5v0d10v5` | Same 4-terminal (D,G,S,B) pin order as `bias_core`'s own devices, matching gf180's own pin layout — mechanical port. |
| VBE/ΔVBE sensing (8:1 ratio pair) | `pnp_10p00x10p00` | `sky130_fd_pr__pnp_05v5_W3p40L3p40` | Same choice as `bias_core` (issue #6): built as **eight parallel `X` instances**, not one `m`/`mult`-scaled instance — `mult` only scales sky130's PNP mismatch terms, not `Is`. |
| PTAT-gain resistor (`R1`, `R2`, `R2TRIM`), Miller-comp resistor (`RZ`), CTAT isolation (`RISO`) | `ppolyf_u` | `sky130_fd_pr__res_xhigh_po` | Same flavor `bias_core` uses for its own `R1`/`R2`/`RT`; `VREF`-independent ratio-tracking legs, so the flavor's absolute-TC spread cancels in-ratio. |
| Miller compensation cap (`CC`) | `cap_mim_2f0_m3m4_noshield` | `sky130_fd_pr__cap_mim_m3_1` | Same choice as `bias_core`. |

## Trim mechanism (simplified for this port)

gf180's own `temp_core` carries a **6-bit binary-weighted** trim ladder
(`R2T5..R2T0`) on the PTAT gain resistor, shorted segment-by-segment by
metal-strapped `nfet` switches — a metal-1 mask option, fuse/OTP-ready for
later, per gf180's own comment: *"a layout/process-portable mechanism, not a
device threshold"* (`spec/porting-plan.md` §1.1). Per issue #7's own scope
("represent as a trim node in the schematic; the physical strap-ladder
itself is layout scope"), this port collapses that to the **one net** a
layout-time metal strap would actually land on:

```
PTAT --[ R2 ]-- PTAT_TRIM --[ R2TRIM ]-- VSS
```

`R2` carries gf180's `R2F` value; `R2TRIM` carries the **sum** of gf180's
six segments (`R2T5+R2T4+R2T3+R2T2+R2T1+R2T0`), so the total (untrimmed)
`R2+R2TRIM` matches gf180's total gain resistor exactly, and the full trim
**range** a layout-time strap could remove is preserved — just as one
segment instead of six. `PTAT_TRIM` is left floating (untrimmed) in this
schematic; no switch transistors are instantiated. Sizing the physical
strap-ladder itself (bit count, granularity, the actual trim code) is layout
scope, deferred to a future issue.

## Sizing

**Every drawn `W`/`L` is carried over unchanged from gf180's ratified
`temp_core`** (bare micron numbers per this repo's own sky130 unit
convention — see `design/README.md`), same convention as `bias_core`
(issue #6):

- Ratio-derived quantities are exactly preserved by construction: the 8:1
  PNP emitter-count ratio, `RZ`/`R1`, and (per the simplified trim mechanism
  above) `(R2+R2TRIM)/R1` = (2652.6+450.88)/119.47 = 25.966, identical to
  gf180's own untrimmed `R2(nominal)/R1` ratio.
- The **absolute** PTAT slope, CTAT intercept, startup margins and
  compensation all depend on sky130's actual PNP `Is`/`BF`, MOS
  transconductance/threshold and resistor sheet resistance — none of which
  have been characterized against sky130 models in this repo yet
  (`spec/porting-plan.md` §2.5/§4 item 2). Per §1.3: this exact topology, on
  gf180mcu itself, measured **outside** its own accuracy targets under
  3-sigma mismatch
  ([DR-011-temp-accuracy-mismatch-not-met](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md)) —
  carrying the topology here is not a presumption it clears sky130's
  (not-yet-derived) accuracy target either.

## Verification done for this issue

Non-goals for issue #7 explicitly exclude layout, DRC/LVS, PVT corner
verification, Monte Carlo, characterization-grade sizing, and the physical
trim-strap ladder. What **is** verified here, as evidence the port is wired
correctly rather than merely textually plausible:

- `python3 design/netlist.py --cell temp_core` exports
  `design/netlist/temp_core.spice` with no xschem ERC/export errors.
- `python3 design/netlist.py --check` passes: both committed netlists
  (`bias_core`, `temp_core`) reproduce byte-for-byte and the
  symbol-pins-match-schematic-ports invariant holds for each.
- **A DC operating-point smoke test**, `temp_core` instantiated alongside
  `bias_core` (`Xbias VDD VSS IBIAS VREF BIAS_OK bias_core`, `Xdut VDD VSS
  IBIAS EN PTAT CTAT temp_core`, `IBIAS` shared between them exactly as the
  interface contract requires), `VDD` = 3.3 V, `EN` = `VDD` (enabled),
  `PTAT`/`CTAT` unloaded — solves at every point of a `tt`/`ff`/`ss` ×
  −40/27/125 °C spot-check (9 points; ngspice needed its `gmin`-stepping
  fallback at several points and hit one singular-matrix warning at
  `ss`/125 °C that still converged — expected for a ΔVBE loop with a
  degenerate zero-current startup solution, the same class of behavior
  `bias_core.md` documents). No solver failures (only the one
  singular-matrix warning, at a point that still solved). Untrimmed
  (`PTAT_TRIM` floating) results:

  | Corner | Temp (°C) | `V(PTAT)` | `V(CTAT)` | `V(BIAS_OK)` | `V(IBIAS)` shared node |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | tt | −40 | 1.099 V | 0.782 V | 3.300 V | 0.913 V |
  | tt | 27  | 1.414 V | 0.658 V | 3.300 V | 0.849 V |
  | tt | 125 | 1.877 V | 0.466 V | 3.300 V | 0.760 V |
  | ff | −40 | 1.099 V | 0.782 V | 3.300 V | 0.886 V |
  | ff | 27  | 1.414 V | 0.658 V | 3.300 V | 0.821 V |
  | ff | 125 | 1.876 V | 0.466 V | 3.300 V | 0.732 V |
  | ss | −40 | 1.100 V | 0.783 V | 3.300 V | 0.940 V |
  | ss | 27  | 1.414 V | 0.659 V | 3.300 V | 0.877 V |
  | ss | 125 | 1.877 V | 0.466 V | 3.300 V | 0.789 V |

  `V(PTAT)` rises and `V(CTAT)` falls monotonically with temperature at
  every corner checked (consistent with PTAT/CTAT by construction);
  `V(PTAT)`'s slope (≈4.7 mV/°C at `tt`) is within a few percent of the
  first-order prediction from the carried device ratios
  (`(R2+R2TRIM)/R1 * d(kT/q*ln8)/dT` ≈ 4.66 mV/°C), and `V(BIAS_OK)` reads
  asserted (rail-high) at every point. **These numbers are a
  solvability/sanity check, not a characterized target** — no PVT-grid
  record exists for this cell, and none is claimed; the close match to the
  first-order prediction is evidence the topology is wired correctly, not a
  claim about sky130 accuracy.

## Scope and what this is not

Per issue #7's non-goals: **not** layout, DRC/LVS, PVT corner verification,
Monte Carlo, characterization-grade sizing, or the physical trim-strap
ladder (see [Trim mechanism](#trim-mechanism-simplified-for-this-port)
above). Re-sizing once sky130 device characterization lands
(`spec/porting-plan.md` §4 item 2) is expected follow-on work, not a defect
in this port — do not read any voltage, slope or current figure in this
document as a ratified or even provisional target; `spec/target-spec.md`
does not exist yet in this repo (`spec/porting-plan.md` §4 item 4).
