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

## Startup and branch selection (issue #19)

The first **full** PVT record for this cell
(`sim/bias-core-smoke/records/20260825-214036-a9cac4b.md`, a cold `.op` at
each of 45 points) came back `overall: FAIL` on two points — `tt_27c_2.97v`
and `tt_27c_3.63v` — with `VREF` railed near `VDD` and a *negative* milliamp
supply current. [Issue
#19](https://github.com/2AMLogic/sky130-temp-por/issues/19) investigated
whether that was a second stable state this cell's startup kick fails to
break out of. **It is not.** The two experiments that answer it are
`sim/bias-core-op-branch/` (the diagnosis) and `sim/bias-core-startup/` (the
replacement characterization); the summary below is theirs, not a new claim.

### What the reported "solution" actually is

At `tt`/27 °C/2.97 V the cold `.op` reports, on the same deck, node voltages
that no version of this circuit can produce:

| Node | Cold `.op` at 2.97 V (off-branch) | Cold `.op` at 3.30 V (intended branch) |
| --- | --- | --- |
| `VREF` | 2.9655 V (≈ `VDD`) | 1.2562 V |
| supply current | **−5.387 mA** (V1 *sinking* current) | +0.936 µA |
| `PG` (mirror gate) | 0.1061 V — every mirror PFET hard on | 2.2643 V |
| `NB` | **−6.96 × 10⁸ V** | 0.6302 V |
| `EC` (8× PNP emitter node) | **−6.96 × 10⁸ V** | 0.5756 V |
| `NBTOP` | +4.583 V — *above* the 2.97 V rail | 0.6330 V |
| `BIAS_OK` | 2.9700 V (**asserted**) | 3.2999 V (asserted) |

Two of those are impossible rather than merely surprising:

- **The supply sinks 5.4 mA.** `V1` is the only energy source and every other
  element in the cell is passive (MOS, PNP, poly resistors, MIM caps), so any
  real DC solution must *dissipate* power.
- **`NB`/`EC` sit 7 × 10⁸ V below ground**, on a 2.97 V rail, with no charge
  pump, inductor or second supply anywhere in the cell.

That is a *false convergence*, not an equilibrium: the ΔVBE sensing nodes are
driven so far into the PNP model's reverse region that the branch
conductances underflow, ngspice's per-node convergence test is satisfied by a
residual that has nothing to do with a solution, and the mirror gate `PG`
collapses toward ground, which is what pulls `VREF`, `IBIAS` and `NBTOP` up
to the rail and puts milliamps through the mirror legs. Note that `BIAS_OK`
reads **asserted** in this state — the settle flag cannot be used to
distinguish branches.

### Why it is the solver's path, not the circuit

Holding the circuit, the deck and the corner fixed and changing *only the
numerics* moves the result. Over a 10 mV supply sweep from 2.97 V to 3.63 V
at `tt`/27 °C (67 points per variant):

- **KLU** (`sim/spiceinit`'s own setting, i.e. what produced the smoke
  record) lands off-branch at 4 of 67 supply points: 2.97, 3.31, 3.35 and
  3.63 V.
- **The built-in sparse solver**, with nothing else changed, lands
  off-branch at 3 *entirely different* points: 3.25, 3.48 and 3.59 V. The
  two sets are disjoint — every one of KLU's four flagged points is fine
  under sparse, and vice versa.
- The off-branch points are **isolated single-step islands** (3.31 V
  off-branch with 3.30 V and 3.32 V both fine), not the contiguous region
  bounded by a bifurcation that a real second equilibrium would produce.
- Disabling gmin stepping (source stepping instead) recovers the intended
  branch at both flagged corners. A designer `.nodeset` seed recovers only
  one of the two (2.97 V yes, 3.63 V no) — worth knowing before trusting a
  seeded `.op`.
- The failure is **not** 27 °C-specific either: sweeping temperature at
  2.97 V, 27 °C and 30 °C land off-branch while 22/24/25/26/28/29/32 °C do
  not. Scatter on this axis too.

A linear solver cannot add or remove an equilibrium of a circuit; it can only
change the arithmetic path taken to one. So the branch a cold `.op` reports
here is a property of the continuation, not of `bias_core`. On the intended
branch, meanwhile, `VREF` moves a total of 0.2 mV across the whole
2.97–3.63 V range — one smooth, well-behaved solution, with no second
physical solution anywhere on the axis.

### What the cell actually does from 0 V

`sim/bias-core-startup/` replaces the cold `.op` with a physical power-up — a
supply ramp from 0 V integrated forward (`tran … uic`), which starts from the
same all-zero state silicon does — across the same full 45-point PVT matrix.
Record `20260826-005156-f4f73a5` is **45/45 PASS**: the on-die kick chain
(`XKS0`–`XKS4` → `XKPD`/`XKICK`) breaks the degenerate zero-current state at
every point, `VREF` settles between 1.2456 V and 1.2582 V, `BIAS_OK` asserts
rail-high, and the settled supply current stays between 0.76 µA and 1.20 µA
(positive at every corner). As everywhere else in this document, those are
solvability/branch-selection numbers, **not** a characterized or ratified
target.

One caveat worth carrying forward, because it was measured rather than
assumed: the *first* run of that experiment
(record `20260825-235846-f4f73a5`, kept and superseded rather than deleted)
used ngspice's default `reltol=1e-3` and came back 43/45 — two corners ended
their ramp reporting a **negative** settled supply current, with no warning
in the log. The same two decks with nothing changed but `.option reltol=1e-4`
land on the intended branch. So a transient is not automatically immune to
the same silent false convergence; the tolerance is part of the claim, and
the supply-current-sign guard is what catches it.

**Practical consequence for anyone simulating this cell**: do not read a bare
`.op` as evidence about which branch `bias_core` selects — ramp the supply
from 0 V at `reltol=1e-4`, and keep a physicality guard on the measurement.
`sim/README.md` §"Branch selection" states the rules for the block as a whole
(they apply equally to `temp_core`, which has the same ΔVBE loop and its own
kick; `design/temp_core.md`'s own cold-`.op` spot check was retired and
replaced by a full-PVT `tran … uic` transient record for the same reason,
per issue #22).

## Scope and what this is not

Per issue #6's non-goals: **not** layout, DRC/LVS, PVT corner verification,
Monte Carlo, or characterization-grade sizing. Re-sizing once sky130 device
characterization lands (`spec/porting-plan.md` §4 item 2) is expected
follow-on work, not a defect in this port — do not read any voltage or
current figure in this document as a ratified or even provisional target;
`spec/target-spec.md` does not exist yet in this repo (`spec/porting-plan.md`
§4 item 4).
