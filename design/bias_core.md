# `bias_core` — shared bias / reference core (sky130 port)

Sky130 port of
[gf180-temp-por's `design/bias_core.sch`](https://github.com/2AMLogic/gf180-temp-por/blob/main/design/bias_core.md)
(issue #11 there), landed by issue #6 here as sub-issue 1 of 5 of the
T1-item-1 decomposition (see #5). Topology per
[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md)
("Shared infrastructure"), carried into this repo by
[DR-002](../spec/decision-records/DR-002-architecture-carryover.md); device
mapping per `spec/porting-plan.md` §2.2 and
[DR-001](../spec/decision-records/DR-001-supply-flavor.md).

**This is a mechanical, first-order port, not a characterized design.** See
[Scope and what this is not](#scope-and-what-this-is-not) before reading
anything below as a verified number.

## What this cell is

Unchanged in shape from gf180's `bias_core`: the **always-on** shared
bias/reference core for the whole block — no enable pin, no off state, live
from the first millivolt of rail. It owns its own startup kick and the
`BIAS_OK` settle flag. Everything below is a direct translation of gf180's
own `design/bias_core.md` topology description onto sky130 devices; read
that document for the full circuit-theory argument (amplifier-forces-V(NA)=
V(NB), the three-leg-vs-Kuijk rejection, the compensation argument for
routing wide-gate loads off `PB` instead of `PG`) — none of that reasoning
is device-specific, so it is not re-derived here.

## Interface

| Pin | Dir | Meaning |
| --- | --- | --- |
| `VDD`, `VSS` | inout | 3.3 V nominal supply pair on sky130 5V I/O-class devices (`g5v0d10v5`), 2.97–3.63 V ([DR-001](../spec/decision-records/DR-001-supply-flavor.md)) |
| `IBIAS` | out | shared bias-mirror node. Convention carried from gf180: `bias_core` **sources** current **into** this pin; compliance `V(IBIAS) <= VDD - 0.2 V`. Will feed `temp_core`, `por_comparator` and `por_output_chain` once those land (issues #7–#9). |
| `VREF` | out | absolute reference `por_comparator`'s divider will compare against. **Value not ratified** — see [Scope](#scope-and-what-this-is-not). |
| `BIAS_OK` | out | "shared core is up and settled", active high. Will gate the POR release decision once `por_comparator` exists ([DR-002](../spec/decision-records/DR-002-architecture-carryover.md) startup ordering). |

## Device mapping (`spec/porting-plan.md` §2.2 / DR-001)

| Role | gf180 device | sky130 device | Notes |
| --- | --- | --- | --- |
| Core mirror, error amp, output stage MOS | `pfet_03v3`/`nfet_03v3` | `sky130_fd_pr__pfet_g5v0d10v5`/`nfet_g5v0d10v5` | 4-terminal (D,G,S,B), same pin order as gf180's devices — confirmed by inspecting both PDKs' xschem symbols. |
| VBE/ΔVBE sensing (8:1 ratio pair + reference) | `pnp_10p00x10p00` | `sky130_fd_pr__pnp_05v5_W3p40L3p40` | 3-terminal (C,B,E); sky130 only ships **two** fixed emitter sizes (`W0p68L0p68` small, `W3p40L3p40` large — no continuously-sized PNP), so `W3p40L3p40` (the larger unit) is used throughout, mirroring gf180's single-fixed-unit convention. Built as **eight parallel `X` instances** for the 8x leg (`XQ8A..XQ8H`), not one instance with a scaled `m`/`mult` — confirmed from `sky130_fd_pr__pnp_05v5_W3p40L3p40`'s own `.model.spice`, `mult` only scales the mismatch terms, not `Is`, the identical quirk gf180's `pnp_10p00x10p00` has. |
| Bias-setting / ratio resistors (`R1`, `R2`, `RT`, `RZ`) | `ppolyf_u_3k` | `sky130_fd_pr__res_xhigh_po` | 3-terminal (`M`,`P`,`B` — bulk tied to `VSS`), same pin geometry/order as gf180's `ppolyf_u_3k` symbol. `res_xhigh_po` is the highest-sheet flavor (~2000 Ω/sq, per `sky130-bandgap/spec/topology-survey.md`), chosen for the same reason gf180 chose `ppolyf_u_3k` over the lower-sheet `ppolyf_u`: `VREF` depends only on the **ratio** `R2/R1`, not on either resistor's absolute value or TC, so the higher-sheet flavor's area saving is free here. `res_xhigh_po`'s stronger, opposite-sign TC (vs. `res_high_po`) is exactly why the topology-survey flags it as safe **only** for ratio-tracking legs — which is what every resistor in this cell is. |
| Miller compensation caps (`CC`, `COK`) | `cap_mim_2f0_m3m4_noshield` | `sky130_fd_pr__cap_mim_m3_1` | 2-terminal, same pin geometry as gf180's `cap_mim_analog` symbol. Density formula (`~2 fF/µm² + perimeter term`) is the same order as gf180's 2f0 density. |

## Sizing

**Every drawn `W`/`L` (and resistor `r_width`/`r_length`) is carried over
unchanged from gf180's ratified `bias_core`** — this is deliberate, not an
oversight:

- The topology's **ratio-derived** quantities are exactly preserved by
  construction: `R2/R1` = 4104.0/350.0 = 11.7257 (identical to gf180's
  ratio, since both numerator and denominator use the same drawn `W` on the
  same resistor flavor), `RT/R1` = 17.5/350.0 = 0.05, the mirror ratios
  (`XMPIB`/`XMBP` = 40/2 = 20:1, etc.), and the 8:1 PNP emitter-count ratio.
  None of these depend on sky130's actual device electricals.
- The **absolute** currents, `VREF`'s settled value, startup margins and
  loop compensation all depend on sky130's actual PNP `Is`/`BF`, MOS
  transconductance and threshold, and resistor sheet resistance — none of
  which have been characterized against sky130 models in this repo yet
  (`spec/porting-plan.md` §4 item 2, not yet filed). This cell's pass
  condition, per issue #6, is a **reproducible, correctly-wired topology**,
  not a characterized one.

## Verification done for this issue

Non-goals for issue #6 explicitly exclude PVT corner verification,
Monte Carlo, and characterization-grade sizing (those are T1 items 2–9,
follow-on work once all 5 decomposition sub-issues land). What **is**
verified here, as evidence the port is wired correctly rather than merely
textually plausible:

- `python3 design/netlist.py --cell bias_core` exports
  `design/netlist/bias_core.spice` with no xschem ERC/export errors.
- `python3 design/netlist.py --check` passes: the exported netlist is
  reproducible and the symbol-pins-match-schematic-ports invariant holds.
- **A DC operating-point smoke test** (`XDUT VDD VSS IBIAS VREF BIAS_OK
  bias_core`, `VDD` = 3.3 V, sky130's `tt`/27 °C corner) solves — ngspice
  needed its `gmin`-stepping fallback to clear a singular-matrix warning at
  `V(NB)` on the first attempt, which is expected for a ΔVBE loop with a
  degenerate zero-current solution (the same class of startup problem
  gf180's own `bias_core.md` documents at length) — and settles to
  `VREF` ≈ 1.256 V, `BIAS_OK` asserted (rail-high), `IBIAS` at compliance
  (open-circuit, so it rails to `VDD` with no load), and a total supply draw
  ≈ 0.94 µA. Spot-checked (not a full corner sweep — that is out of scope
  here) at `tt`/`ff`/`ss` × −40/27/125 °C: `VREF` stays inside a
  1.2477–1.2574 V band and `BIAS_OK` reads asserted at every point checked,
  with no solver failures. **These numbers are a solvability/sanity check,
  not a characterized target** — no PVT-grid record exists for this cell,
  and none is claimed.

## Scope and what this is not

Per issue #6's non-goals: **not** layout, DRC/LVS, PVT corner verification,
Monte Carlo, or characterization-grade sizing. Re-sizing once sky130 device
characterization lands (`spec/porting-plan.md` §4 item 2) is expected
follow-on work, not a defect in this port — do not read any voltage or
current figure in this document as a ratified or even provisional target;
`spec/target-spec.md` does not exist yet in this repo (`spec/porting-plan.md`
§4 item 4).
