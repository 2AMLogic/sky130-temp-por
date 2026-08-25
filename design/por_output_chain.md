# `por_output_chain` — deglitch, one-shot, push-pull `RESETn` drive, and the POR startup-assist pull-down (sky130 port)

Sky130 port of
[gf180-temp-por's `design/por_output_chain.sch`](https://github.com/2AMLogic/gf180-temp-por/blob/main/design/por_output_chain.md)
(issue #12 there), landed by issue #9 here as sub-issue 4 of 5 of the
T1-item-1 decomposition (see #5), depending on `bias_core` (issue #6) and
`por_comparator` (issue #8). Topology per
[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md),
carried into this repo by
[DR-002](../spec/decision-records/DR-002-architecture-carryover.md); device
mapping per `spec/porting-plan.md` §2.2 and
[DR-001](../spec/decision-records/DR-001-supply-flavor.md).

**This is a mechanical, first-order port, not a characterized design.** See
[Scope and what this is not](#scope-and-what-this-is-not) before reading
anything below as a verified number.

## What this cell is

Unchanged in shape from gf180's `por_output_chain`: `POR_RAW` (the raw,
hysteretic threshold decision from `por_comparator`) feeds a current-starved
differential deglitch filter (`MDGPI`/`MDGNI` into `CDG`, restored by two
ratio-skewed inverters `MG1P`/`MG1N`/`MG2P`/`MG2N`), which gates a
current-starved one-shot timer (`MPT`/`MTSW`/`MDIS`/`CTIM`), whose expiry is
read by a two-stage nA-limited trip detector (`MDAPI`/`MDANT`,
`MDBNI`/`MDBPT`, plus the release latch `MRLK`) that is one input to a
release NAND (`MNAP1`/`MNAP2`/`MNAN1`/`MNAN2`) driving a push-pull output
stage (`MOP`/`MON`) through a startup-assist keeper (`MAST`). `RESETn`
releases only when the one-shot has expired **and** the deglitched rail is
good — this cell, not `por_comparator`, owns the final release gate
(DR-002).

Per `design/README.md`'s verified finding (issue #6/#9, confirmed against
`2AMLogic/gf180-temp-por@main`): the POR startup-assist pull-down lives
**inside** this cell, not as a separate DR-002 leaf cell. Concretely, it is
the release NAND's own below-floor default: with `TRIP` and `PGDG` both at
their dead-circuit low default, a NAND's two *parallel* PMOS pull-ups beat
its *series* NMOS pull-down stack by a wide leakage-ratio margin, pinning
`RSTB` to `VDD`, which turns `MON` fully on and `MOP` fully off — `RESETn`
asserted, with no static current in the settled state and no dedicated
always-on device. `MAST` latches that state once `RESETn` is already low, so
the assist survives even a `POR_RAW` driven high below the comparator's own
floor.

This port adds one thing gf180's own schematic does not have: `MASSIST`, an
independent, always-on near-zero-`Vt` pull-down gated directly from
`VDD`/`VSS` (see [Device mapping](#device-mapping-sky130-devicemappingmd-2-2-dr-002) below) —
see [Why `MASSIST` exists](#why-massist-exists-and-why-its-not-in-gf180s-own-schematic).

Everything else below is a direct translation of gf180's own
`design/por_output_chain.md` topology description onto sky130 devices; read
that document for the full circuit-theory argument (why a NAND and not a
NOR, why the trip detector is two current comparators and not a starved
inverter, why the output pair is drawn 20:1) — none of that *architecture*
is device-specific, so it is not re-derived here. What **is** re-derived
here, because it is device-specific, is the `MASSIST` device choice below.

## Interface

| Pin | Dir | Meaning |
| --- | --- | --- |
| `VDD`, `VSS` | inout | 3.3 V nominal supply pair on sky130 5V I/O-class devices (`g5v0d10v5`), 2.97–3.63 V ([DR-001](../spec/decision-records/DR-001-supply-flavor.md)), matching `bias_core`/`por_comparator` |
| `IBIAS` | in | shared bias-mirror node from `bias_core`. This cell's own `MBD` is the local mirror diode — ungated and always on, since this cell has no enable pin to gate it with. Per [DR-010](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-010-shared-ibias-disabled-consumer-contract.md), at least one always-on diode-connected leg must stay on the shared `IBIAS` node; `MBD` is it for this cell |
| `POR_RAW` | in | raw, hysteretic threshold decision from `por_comparator`, **active high** = "rail is above VPOR↑ and the comparator's decision is authoritative" (matches `por_comparator`'s own polarity convention, issue #8). Low — including undriven-low below the comparator's own operating floor — is the fail-safe sense |
| `RESETn` | out | reset, **active low**, **push-pull** (DR-002). Held low from the first millivolt of `VDD`, through the shared core's operating floor (where `POR_RAW` is undefined by construction), by this cell's own below-floor default — **not** gated by `POR_RAW`. Drives both the top-level pad and `temp_core.EN` once `temp_por_top` (#10) assembles the hierarchy |

## Device mapping (`spec/porting-plan.md` §2.2 / DR-002)

| Role | gf180 device | sky130 device | Notes |
| --- | --- | --- | --- |
| Deglitch / one-shot / trip-detector / output-stage MOS | `pfet_03v3`/`nfet_03v3` | `sky130_fd_pr__pfet_g5v0d10v5`/`nfet_g5v0d10v5` | Same 4-terminal (D,G,S,B) pin order as `bias_core`/`por_comparator`'s own devices — mechanical port, every drawn `W`/`L` unchanged |
| Deglitch/one-shot capacitors (`CDG`, `CTIM`) | `cap_mim_2f0_m3m4_noshield` | `sky130_fd_pr__cap_mim_m3_1` | Same choice as `bias_core`; `MF` parameter carries gf180's own `m` multiplicity (`CTIM`: `MF=4`) |
| Startup-assist pull-down (`MASSIST`, new in this port — see below) | none (gf180's own cell has no equivalent device) | `sky130_fd_pr__nfet_05v0_nvt` | See [Why `MASSIST` exists](#why-massist-exists-and-why-its-not-in-gf180s-own-schematic) |

### Why `MASSIST` exists, and why it's not in gf180's own schematic

`spec/porting-plan.md` §1.2/§2.2/§2.6 (this repo's own porting plan, issue
#1) records that gf180's own
[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md)
originally scoped the startup-assist leg as *"native/zero-Vt if available,
else a minimally-biased standard-Vt divider"* — gf180mcu's own native-device
availability was **unconfirmed** at that authoring time. gf180's own actual
`por_output_chain.sch` shows it took the "else" branch: the release-NAND
leakage-divider mechanism described above, built entirely from ordinary-`Vt`
`nfet_03v3`/`pfet_03v3` devices, with no native/zero-`Vt` device anywhere in
the cell. sky130's near-zero-`Vt` devices are **confirmed** available
(`nfet_03v3_nvt`, `nfet_05v0_nvt`) — per porting-plan.md §1.2, *"a strictly
better starting position, not a like-for-like swap"* — and this issue's own
device-mapping table (curated from that plan) directs this port to use one.
`MASSIST` is that device: an additional, independent below-floor assist leg
with its gate tied directly to `VDD` and source to `VSS`, so it begins
conducting from the very first millivolt of `VDD` — before `IBIAS` exists,
before `MBD`'s mirror diode has any current to mirror, and independently of
whatever state the release-NAND leakage divider is in. It is deliberately
**not** gated by `RESETn` (unlike `MAST`): a near-zero-`Vt` device has no
meaningful off state to gate into, so `MASSIST` is a genuinely always-on
leakage path by construction, layered *on top of* the existing NAND-based
mechanism rather than replacing it.

**Device choice** (`nfet_05v0_nvt` over `nfet_03v3_nvt`, recorded inline per
this issue — porting-plan.md §2.6 defers that choice itself to a future
characterization issue): two reasons, one anticipated by the porting plan
and one found empirically while sizing this device.

1. `nfet_05v0_nvt` matches this design's own 5 V-class `g5v0d10v5` device
   family (DR-001) rather than mixing gate-oxide classes on the same
   3.3 V-nominal rail.
2. **Discovered empirically against the installed sky130A PDK while sizing
   this device, not assumed from naming convention**: sky130's native/
   near-zero-`Vt` devices are **fixed-geometry library cells**, not
   continuously-scalable primitives like the `g5v0d10v5` MOS or
   `res_xhigh_po` used everywhere else in this design. Each flavor ships
   only a small, discrete menu of pre-characterized `(L, W)` bins —
   ngspice's automatic bin-selection model lookup rejects any other pair
   outright with `could not find a valid modelname` (confirmed empirically;
   see [Verification done for this issue](#verification-done-for-this-issue)).
   `nfet_03v3_nvt`'s entire menu (from
   `sky130_fd_pr__nfet_03v3_nvt__tt.corner.spice`) is short-channel
   (`L` ≤ 0.8 µm); `nfet_05v0_nvt`'s menu (from
   `sky130_fd_pr__nfet_05v0_nvt__tt.corner.spice`) includes one genuinely
   long-channel bin, `L = 25 µm, W = 1 µm`, that `nfet_03v3_nvt` has no
   equivalent of. `MASSIST` is drawn at that bin — the longest-channel
   geometry the chosen flavor's own fixed menu offers — so that once
   `RESETn` is legitimately released, `MOP`'s active drive overpowers it by
   a wide margin, the same weak-keeper-vs-strong-driver ratio argument
   `MAST` already makes against the release NAND.

**Known trade-off, explicitly not resolved here**: because `MASSIST` is
always on by construction, it costs a small continuous static current in the
released state that this port has not characterized or budgeted against a
real `por-iq` figure. That trade-off, and the `nfet_03v3_nvt`-vs-
`nfet_05v0_nvt` choice itself, is exactly the "genuinely new
characterization work" porting-plan.md §2.2/§2.6 already flags as owned by a
future issue — not resolved here. This port's own scope is the mechanical
topology substitution CLAUDE.md calls for, not first characterization of a
device class gf180 never used.

## Sizing

**Every drawn `W`/`L` for the devices gf180's own `por_output_chain` already
has is carried over unchanged** (bare micron numbers per this repo's own
sky130 unit convention — see `design/README.md`), same convention as
`bias_core`/`por_comparator`. `CDG` (11 µm × 11 µm) and `CTIM` (4 × 28 µm ×
28 µm, `MF=4`) are carried as **first-order placeholder timing elements** —
per CLAUDE.md ("thresholds do not port"), no reset-pulse-width or
deglitch-dwell **duration** from gf180's own `design/por_output_chain.md` is
a sky130 target; only the topology (a current-starved capacitor is what
makes a fixed-width pulse buildable in a sub-µA budget) carries. `MASSIST`
(new in this port) is sized at the longest-channel bin its device menu
offers, per [Device mapping](#device-mapping-sky130-devicemappingmd-2-2-dr-002) above — a
menu constraint, not a free sizing choice.

## Verification done for this issue

Non-goals for issue #9 explicitly exclude layout, DRC/LVS, PVT corner
verification, Monte Carlo, characterization-grade sizing, actual
reset-pulse-width/dwell derivation, and re-litigating the
`nfet_03v3_nvt`/`nfet_05v0_nvt` choice beyond picking one. What **is**
verified here, as evidence the port is wired correctly rather than merely
textually plausible:

- `python3 design/netlist.py --cell por_output_chain` exports
  `design/netlist/por_output_chain.spice` with no xschem ERC/export errors.
- `python3 design/netlist.py --check` passes: all four committed netlists
  (`bias_core`, `temp_core`, `por_comparator`, `por_output_chain`) reproduce
  byte-for-byte and the symbol-pins-match-schematic-ports invariant holds
  for each.
- **`MASSIST`'s fixed-geometry device menu was confirmed empirically, not
  assumed**: an initial draft sized it at an arbitrary weak-leg geometry
  (10 µm / 0.5 µm, matching this cell's other weak-reference-leg devices)
  and ngspice rejected it outright at `.op` time with `could not find a
  valid modelname` — `sky130_fd_pr__nfet_05v0_nvt` (and
  `sky130_fd_pr__nfet_03v3_nvt`) are binned, fixed-`(L,W)` library cells, not
  continuously-scalable primitives. The device menu was read directly from
  the installed PDK's own corner file
  (`$PDK_ROOT/sky130A/libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_05v0_nvt__tt.corner.spice`),
  and `MASSIST` was re-sized to the `L=25 µm, W=1 µm` bin that menu actually
  offers (see [Device mapping](#device-mapping-sky130-devicemappingmd-2-2-dr-002) above) — after
  which the smoke tests below solve cleanly.
- **A DC operating-point + transient smoke test** (`bias_core` and
  `por_output_chain` instantiated together sharing `IBIAS`, exactly as the
  interface contract requires; `VDD` = 3.3 V, sky130's `tt`/27 °C corner;
  `POR_RAW` driven by a pulse source: low until 200 µs, high for 5 ms, low
  again):
  - `.op` with `POR_RAW` = 0: `V(RESETn)` = 6.5×10⁻¹⁰ V (asserted/low), as
    expected below the comparator's operating floor / with `POR_RAW` low.
  - Transient: `RESETn` releases (crosses `VDD`/2 rising) 1.92 ms after
    `t=0` (≈1.72 ms after `POR_RAW` rises at 200 µs) — a nonzero,
    one-shot-shaped delay, not an instantaneous pass-through — and
    reasserts (falls back to ≈0 V) shortly after `POR_RAW` drops again at
    5.2 ms. Qualitatively exactly the assert → delayed-release →
    reassert-on-drop behavior DR-002's topology calls for.
- **A below-floor smoke test**, isolating the mechanism this issue's own
  title names: `VDD` ramped `0 → 3.3 V` over 3 ms (`PULSE` source), `POR_RAW`
  held at a constant `DC 0` throughout (the fail-safe/undriven-low sense),
  `bias_core` and `por_output_chain` instantiated together as above. No
  solver failures across the ramp. `max(V(RESETn))` over the entire 3 ms
  ramp = **1.45 mV** — `RESETn` never leaves its asserted (near-`VSS`) band
  at any point of the ramp from 0 V. **This is a solvability/sanity check,
  not a characterized target** — no PVT-grid record exists for this cell,
  and no floor-voltage claim is made; the qualitative result (near-zero,
  monotonically bounded, no glitch to the released state) is evidence the
  release-NAND-plus-`MASSIST` below-floor mechanism is wired correctly, not
  a claim about a sky130 valid-low-floor spec value.

## Scope and what this is not

Per issue #9's non-goals: **not** layout, DRC/LVS, PVT corner verification,
Monte Carlo, characterization-grade sizing, actual reset-pulse-width/dwell
derivation, or the `nfet_03v3_nvt`-vs-`nfet_05v0_nvt` characterization
question beyond picking one and recording why (see
[Why `MASSIST` exists](#why-massist-exists-and-why-its-not-in-gf180s-own-schematic)
above). Re-deriving the real pulse width, deglitch dwell, and valid-low
floor against sky130 models and a real `IBIAS`/`POR_RAW` from `bias_core`/
`por_comparator` is expected follow-on work
(`spec/porting-plan.md` §2.3/§2.4/§4 item 2), not a defect in this port — do
not read any voltage, duration, or current figure in this document as a
ratified or even provisional target; `spec/target-spec.md` does not exist
yet in this repo (`spec/porting-plan.md` §4 item 4).
