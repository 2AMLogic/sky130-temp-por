# Chipalooza Challenge #4 proposal — temperature sensor + POR supervisor (sky130)

Analog-IP proposal for [Open Circuit Design's Chipalooza Challenge
#4](https://opencircuitdesign.com/chipalooza/) (Sky130 / ChipFoundry). This
document is written to be sendable verbatim once the design clears its
sign-off bar; it contains no personal or institutional identifiers.
Designer CVs and the test-equipment list, if this design is ever submitted,
are separate email attachments outside this repository, per the challenge's
submission process (see [2AMLogic/gf180-temp-por's own Challenge #3
proposal](https://github.com/2AMLogic/gf180-temp-por/blob/main/docs/chipalooza/challenge-3-proposal.md)
for the sibling repo's version of that same process, on a different PDK and
a more mature design).

**Rules status (as of this writing, 2026-08-25): Challenge #4's own rules
page (`rules-4.html`) is not yet published** — the organizers' calendar puts
launch at 2026-11-09. Per
[2AMLogic/2am#542](https://github.com/2AMLogic/2am/issues/542) (the epic
this issue is a phase of), this document assumes the structure common to
the two *published* briefs (`rules-2.html`/`rules-3.html`): a template
wrapper cell in a fixed slot; a harness-supplied bandgap-referenced bias
voltage and up to two bandgap-referenced current sources; 24 digital
control inputs; 12 digital test outputs; 4 shared (multiplexed) analog
lines; 0–4 dedicated pads; an SPI control interface; deliverables of
schematic + pre-layout sim → layout + post-layout sim over PVT → final
DRC/LVS in-repo, verifiable with open-source EDA; a standard open license
(preferably Apache 2.0). When `rules-4.html` publishes, a follow-up issue
must re-check every assumption in this document against the real brief
before any submission — this document is **not** a claim that Challenge
#4's actual rules match this assumption, only the best available structure
to design against today.

**Honesty note, stated once here rather than repeated on every row.** This
repository is at **schematic-only maturity**: `design/` carries a complete,
netlist-checked schematic hierarchy (issues #6–#10), but `sim/` and
`layout/` are both **empty** — placeholder `README.md` files only, no
testbenches, no PVT sweeps, no GDS, no DRC/LVS reports. Per this issue's own
acceptance criteria and CLAUDE.md's "no claim without a testbench," every
row in §4's spec table is re-derived **only from what `sim/` actually
contains today**, which is nothing. This is not a defect this document
introduces or a spec being relaxed to pass — it is an honest snapshot of
where the block actually is on the maturity ladder
(`README.md` § "Target specification": *"Current position: pre-spec"*,
now updated by `design/README.md` to *"schematic complete, verification and
layout remain"*). Where a cell's own design document (`design/*.md`)
records an **informal, uncommitted, spot-corner solvability check** (e.g. a
DC operating point that converges, or a handful of PVT points spot-checked
by hand), this document cites it explicitly and labels it exactly as its
source does — a sanity check that the topology is wired correctly, **not**
simulation evidence for any spec row, and never conflated with a "met"
verdict.

---

## 1. Type of IP block

A combined SoC housekeeping macro: an analog PTAT/CTAT temperature sensor
integrated with a power-on-reset supervisor, sharing one on-chip
bias/reference core. (Same category as the sibling
[gf180-temp-por](https://github.com/2AMLogic/gf180-temp-por) block this
repo is a deliberate PDK port of — see `CLAUDE.md`, `spec/porting-plan.md`.)

## 2. I/O list, including test ports

### 2.1 Rails — reconciling this block's single-3.3 V interface against the harness's generic rail assumption

This block's **ratified pinout** (`design/README.md`, confirmed live and
asserted by `python3 design/netlist.py --check` on every run) is a
**single 3.3 V supply** — `VDD`/`VSS` — not a split 1.8 V-digital /
3.3 V-analog pair. Per
[DR-001](../../spec/decision-records/DR-001-supply-flavor.md), every active
device in the design (mirror/error-amp/output-stage MOS, the vertical
PNPs, the resistor references) uses sky130's `g5v0d10v5` I/O-class device
family operated at the 3.3 V ±10 % point of its rating (2.97–3.63 V steady
state); **no `nfet_01v8`/`pfet_01v8` 1.8 V core device is used anywhere in
the signal path** (DR-001, "Decision"). This is a genuine, block-specific
divergence from the epic's own generic Phase-4 assumption ("Sky130's 1.8V/
3.3V rails," per 2AMLogic/2am#542) — recorded here rather than silently
asserted:

| Harness rail (assumed common structure) | This block's use |
|---|---|
| 1.8 V digital | **Not consumed.** No device in this design is 1.8 V-class. If the harness forces a 1.8 V digital supply pin onto every wrapper slot regardless of whether a design uses it, this block's corresponding pad should be left unconnected — it needs no current from it. |
| 3.3 V analog | **This block's only supply**, `VDD`/`VSS`. Powers the bias/reference core, the temperature-sensing core, the POR comparator and hysteresis network, and the output stage alike — a single-supply design, not split rail-by-function. |

If Challenge #4's real (unpublished) brief instead *forces* a specific
voltage onto the analog rail that differs from 3.3 V ±10 %, or requires the
block to accept the harness's 1.8 V rail for any function, that is a
rail-flavor change requiring a new decision record superseding DR-001 —
not something this document can resolve pre-publication.

### 2.2 Harness-supplied bandgap bias voltage / current sources — not consumed

Not needed from the harness. This block already carries its own internal
reference and bias generator, `bias_core`, always-on
(`design/bias_core.md`): an internal reference (`VREF`, informal spot-check
value ≈1.256 V at `tt`/27 °C — **not a committed sim/ number**, see §4) and
a shared bias current (`IBIAS`, informal spot-check ≈0.85–0.94 µA across a
`tt`/`ff`/`ss` × −40/27/125 °C spot check — again, not committed `sim/`
evidence), both generated on-die and distributed internally to `temp_core`
and `por_comparator`/`por_output_chain` (`design/README.md` → "Internal
nets"). No harness-supplied bandgap voltage or current source is required.
Both nodes are useful bring-up/debug test points and are offered as shared
analog lines below (§2.6) rather than left purely internal.

### 2.3 Digital control inputs — 0 of 24 used

No digital control input exists in the current wave-1 design
(`design/README.md` § "Top-level pinout (ratified)": *"No trim/config/
programming pins... in wave 1"*). Unlike gf180-temp-por's own Challenge #3
proposal, which could propose bonding out a 6-bit `TRIM<5:0>` switch ladder
because gf180's `temp_core` schematic actually instantiates six switch
transistors, **this sky130 port's trim mechanism has no switches to
bond**: issue #7 deliberately collapsed gf180's 6-bit binary-weighted trim
ladder to a single net, `PTAT_TRIM`, left floating/untrimmed in the
schematic with no switch transistors instantiated at all
(`design/temp_core.md` § "Trim mechanism (simplified for this port)" —
*"Sizing the physical strap-ladder itself... is layout scope, deferred to a
future issue"*). Proposing a digital `TRIM<N:0>` bus here would describe a
control interface that does not exist in the schematic today; this
document does not do that. Adding real trim control (either a rebuilt
switch ladder bonded to pads, or a fuse/OTP array per `spec/target-spec.md`
§`temp-trim-strategy`'s eventual home) is future schematic work, tracked
generically by issue #4's T1/bronze ladder, not proposed here.

All 24 control-input slots remain unused.

### 2.4 Digital test outputs — 0 of 12 used today; 2 proposed, not yet wired

| Signal | Purpose | Status |
|---|---|---|
| `POR_RAW` | `por_comparator`'s raw hysteretic threshold decision, active high, **before** the deglitch filter and one-shot timer (`design/README.md` internal-nets table; `design/por_output_chain.md` interface table). Bonding this out would let a bench measurement separate the comparator's threshold behavior from the output chain's timing behavior — exactly the kind of fault-localization test point gf180-temp-por's own Challenge #3 proposal used it for. | **Internal net today; not routed to a pad.** Would need a schematic change (add a top-level port, thread it through `temp_por_top`'s assembly) before it can be bonded. |
| `BIAS_OK` | `bias_core`'s "reference/bias core is up and settled" flag, active high, rail-to-rail (`design/bias_core.md`). Useful at bring-up to confirm the always-on core is alive independent of the POR decision. | **Internal net today; not routed to a pad.** Same schematic-change caveat as `POR_RAW`. |

`RESETn` (§2.5) is the block's one *functional* digital output; it is not
counted against this 12-slot budget, matching the convention gf180-temp-por's
own proposal used. 10 test-output slots remain unused beyond the two
proposed above (12 if neither proposed addition is made before schematic
review).

### 2.5 Dedicated (non-shared, low-resistance) pads — 3 of 4 used

| Signal | Why dedicated, not shared/multiplexed |
|---|---|
| `PTAT`, `CTAT` | Existing ratified analog outputs ([DR-002](../../spec/decision-records/DR-002-architecture-carryover.md)). Neither `temp_core` nor `temp_por_top` includes an output buffer (`design/temp_core.md`: *"No output buffer in this cell... a consuming testbench must specify a high-impedance load"*) — any shared-bus multiplexer's `Ron`/leakage/charge-injection would add offset error directly on top of an as-yet-uncharacterized temperature-accuracy budget (§4.1), so these should stay dedicated, low-resistance pads. |
| `RESETn` | Existing ratified reset output ([DR-002](../../spec/decision-records/DR-002-architecture-carryover.md)), active-low, push-pull, with a below-floor pull-down default (`design/por_output_chain.md` § "What this cell is" — the release-NAND leakage-divider default plus the always-on `MASSIST` leg). A multiplexer in this path would degrade drive strength and risk missing an early-release event during bring-up — this must be a dedicated pad, matching gf180-temp-por's own DR-004-equivalent reasoning for the same pin. |

1 dedicated-pad slot remains unused.

### 2.6 Shared (multiplexed) analog lines — 0 of 4 used today; 2 proposed, not yet wired

| Signal | Purpose | Status |
|---|---|---|
| `VREF` | `bias_core`'s internal reference — the value `por_comparator`'s divider is ratioed against (`design/bias_core.md`, `design/README.md` internal-nets table). Bonding it out as a shared/muxed test point (not a dedicated pad, since it does not feed the accuracy-critical signal path directly) would let bring-up verify the reference independently of the threshold decision it drives. | **Internal net today; not routed to a pad.** |
| `IBIAS` | `bias_core`'s shared bias-current node, distributed to all three consumer cells with a one-driver/three-consumer, no-switch/no-clamp/no-added-load contract (`design/README.md` internal-nets table). Probing a sub-µA current node through a shared/muxed pad changes its own loading — this tap should be treated as coarse/qualitative (presence/rough magnitude) only, an open item for schematic review to size correctly (e.g. a buffered mirror copy rather than a direct tap), exactly the caveat gf180-temp-por's own proposal recorded for the analogous pin. | **Internal net today; not routed to a pad.** |

4 shared-analog-line slots remain unused.

### 2.7 Pinout summary

| Bucket | Used today | Proposed (schematic change needed) | Budget |
|---|---:|---:|---:|
| Rails | 1 (3.3 V single supply; no 1.8 V rail consumed) | — | 1.8 V + 3.3 V (assumed) |
| Harness bandgap bias voltage | 0 (internal reference used instead) | — | n/a |
| Harness bandgap current sources | 0 (internal bias used instead) | — | ≤2 |
| Digital control inputs | 0 | 0 (no switch ladder exists to bond — see §2.3) | ≤24 |
| Digital test outputs | 0 (+ `RESETn` functional) | 2 (`POR_RAW`, `BIAS_OK`) | ≤12 |
| Dedicated pads | 3 (`PTAT`, `CTAT`, `RESETn`) | 0 | ≤4 |
| Shared analog lines | 0 | 2 (`VREF`, `IBIAS`) | ≤4 |

Total pads today: the ratified wave-1 five (`VDD`, `VSS`, `PTAT`, `CTAT`,
`RESETn`). Every proposed addition above (`POR_RAW`, `BIAS_OK`, `VREF`,
`IBIAS`) requires a schematic change — a new top-level port threaded
through `temp_por_top`'s assembly and re-verified with `python3
design/netlist.py --check` — that has **not been made** as of this
document. None of the wave-1 ratified pads would be dropped by adding
them. This block comfortably fits the assumed slot budget either way (5
pads used today; 9 if every proposed addition lands, still well inside
24 in / 12 out / 4 shared / 4 dedicated).

## 3. Functional description

This block provides two closely coupled SoC housekeeping functions from
one shared bias/reference core (`design/README.md` § "Hierarchy";
[DR-002](../../spec/decision-records/DR-002-architecture-carryover.md)):

- **Temperature sensing** (`temp_core`): a ΔVBE/VBE bandgap-style sensing
  core built on an 8:1 emitter-area vertical-PNP pair, outputting two
  ratiometric analog voltages — `PTAT` (positive-temperature-coefficient)
  and `CTAT` (negative-temperature-coefficient, `XQ1`'s own `VEB`) — over
  the intended −40…+125 °C range. A single-node, un-switched 25 °C gain
  trim point (`PTAT_TRIM`) exists in the schematic for a future
  metal-strap/switch mechanism (`design/temp_core.md`); no trim ladder is
  wired in wave 1. `temp_core` is enabled only after POR releases
  (`RESETn` also drives `temp_core.EN`), keeping it out of the startup
  chicken-and-egg problem entirely.
- **Power-on reset supervision** (`por_comparator` + `por_output_chain`):
  a resistor-divided-`VDD` comparator, referenced against `bias_core`'s
  `VREF`, with resistor-network positive-feedback hysteresis, produces a
  raw threshold decision (`POR_RAW`). A current-starved deglitch filter, a
  current-starved one-shot pulse timer, and a push-pull output stage turn
  that decision into `RESETn` — active low, held low from the first
  millivolt of `VDD` by a below-floor default mechanism (a release-NAND
  leakage-divider default, backed by an always-on near-zero-`Vt`
  `MASSIST` pull-down added in this port,
  `design/por_output_chain.md` § "Why `MASSIST` exists") — released once
  and, by design, re-assertable on a sufficiently deep/long/slow supply
  dip via the same comparator path (brownout), without a separate detector
  circuit. **None of this brownout/ramp-rate/deglitch behavior has been
  simulated yet** (§4.2) — the mechanism exists in the schematic; its
  numeric envelope is entirely unmeasured.
- **Shared core** (`bias_core`): always-on, generates the reference
  voltage, the shared bias current, and a "core settled" flag (`BIAS_OK`)
  that is intended to gate the comparator's decision once
  `por_comparator` consumes it (per the DR-002 startup-ordering contract;
  `por_comparator`'s own wiring of `BIAS_OK` was verified informally, not
  via a committed testbench — `design/README.md` cell-status table).

`temp_por_top` (issue #10) is **assembly only**: it instantiates the four
leaf cells (`xbias`/`xtemp`/`xcmp`/`xpor`) and names the internal nets
between them, adding no devices of its own (`design/README.md` §
"Hierarchy"). Every W/L, trip point, and timing element lives in a leaf
cell, and every one of them is a first-order placeholder pending sky130
device characterization (`design/README.md`: *"absolute thresholds,
timings and sizings in the leaf cells are still first-order placeholders
pending sky130 device characterization"*).

The block's electrical interface in this repository today is exactly the
five pads listed in §2.5's dedicated-pad table plus `VDD`/`VSS`: `VDD`,
`VSS`, `PTAT`, `CTAT`, `RESETn`. §2 proposes additions to make it a
better-instrumented bring-up part without changing that ratified
interface; none of those additions has been implemented yet.

## 4. Target specification at the challenge rails

**What this table is, and is not.** Every "Measured (`sim/`)" cell below
is derived **only** from what `sim/` actually contains, per this issue's
own acceptance criteria. `sim/` is empty — a placeholder `README.md` only
(`sim/README.md`: *"Empty until the first work lands here"*) — so every
"Measured" cell reads **"none"**, and every row's status is
**"Unmet — no simulation evidence yet"**, honestly, not as a defect this
document introduces. The "Target (draft)" column carries values from this
repo's own `README.md` draft target-spec table and `spec/porting-plan.md`
§2.8's reconciliation of it — **these are explicitly unratified drafts**,
not a ratified `spec/target-spec.md` (this repo does not have one yet,
`spec/porting-plan.md` §4 item 4), and several are flagged by
`porting-plan.md` §2.8 itself as needing structural correction (not just a
number swap) before they could ever be ratified — those flags are carried
into the table below rather than silently repeated. Where a cell's own
design document records an informal, uncommitted spot-corner check, it is
cited in the Evidence column exactly as that document labels it: a
solvability sanity check, never a "met" claim.

### 4.1 Temperature sensor

| Parameter | Target (draft, unratified) | Measured (`sim/`) | Status | Evidence |
|---|---|---|---|---|
| Operating temperature range | −40…+125 °C | none | Unmet — no simulation evidence yet | — |
| Temperature error, untrimmed | ±3 °C | none | Unmet — no simulation evidence yet. **Caution carried from `spec/porting-plan.md` §1.3/§2.5**: this identical target, on this identical topology, was measured **not met** on gf180mcu itself under 3σ mismatch (6.5× over budget) — carrying the topology to sky130 is not a presumption this target is achievable here either. | `design/temp_core.md` records an untrimmed 9-point spot check (`tt`/`ff`/`ss` × −40/27/125 °C) showing `V(PTAT)` rising and `V(CTAT)` falling monotonically with temperature, PTAT slope ≈4.7 mV/°C at `tt` matching the first-order device-ratio prediction within a few percent — **explicitly labeled by that document as "a solvability/sanity check, not a characterized target," no accuracy or mismatch claim made** |
| Temperature error, 1-point trim | ±1.5 °C (stretch) | none | Unmet — no simulation evidence yet. No trim ladder exists in the schematic to even exercise this row (§2.3, §3) | — |
| PTAT slope | not yet ratified | none | Unmet — no simulation evidence yet | Same informal spot check as above — first-order ratio prediction ≈4.66 mV/°C is close to the ≈4.7 mV/°C spot-check slope, evidence the topology is wired correctly, not a slope-accuracy claim |
| CTAT slope | not yet ratified | none | Unmet — no simulation evidence yet | Same informal spot check — `V(CTAT)` values reported in `design/temp_core.md`'s 9-point table |
| PTAT/CTAT output headroom | not yet ratified | none | Unmet — no simulation evidence yet | — |
| Supply sensitivity of reported temperature | not yet ratified | none | Unmet — no simulation evidence yet | — |
| Quiescent current, temperature sensor (incremental, `temp-iq`) | <20 µA (target), <5 µA (stretch) — draft row flagged by `porting-plan.md` §2.8 as likely mislabeled "block total" in the README when it is actually the sensor-*incremental* figure in gf180's own accounting structure | none | Unmet — no simulation evidence yet | `design/temp_core.md`'s 9-point spot check reports the *shared* `IBIAS` node's total current (0.73–0.94 µA range, dominated by `bias_core`), not an isolated `temp_core`-incremental figure — not usable as evidence for this specific row |

### 4.2 Power-on reset supervisor

| Parameter | Target (draft, unratified) | Measured (`sim/`) | Status | Evidence |
|---|---|---|---|---|
| VPOR↑ — release threshold, rising `VDD` | "re-derive against sky130 models" (README draft explicitly declines to guess a number; correct as drafted per `porting-plan.md` §2.3/§2.8) | none | Unmet — no simulation evidence yet | — |
| VPOR↓ — assert threshold, falling `VDD` | not yet derived | none | Unmet — no simulation evidence yet | — |
| Hysteresis, `V_hys` | "≥100 mV" floor only in the README draft — `porting-plan.md` §2.8 flags this as needing an added **ceiling**, constructed from a re-derived VPOR↑ and a (also not-yet-defined) downstream digital minimum-operating-voltage, mirroring gf180's own min/typ/max structure, not carried as a bare floor | none | Unmet — no simulation evidence yet | — |
| Supply ramp-rate envelope | "ramp-rate sweep in the POR testbench matrix" (structural requirement per README/CLAUDE.md; no numeric envelope drafted) | none | Unmet — no simulation evidence yet | — |
| Brownout (dip depth × dwell × falling-slew, three-axis per `porting-plan.md` §2.4/§3.4) | not yet derived | none | Unmet — no simulation evidence yet | `design/por_output_chain.md` records a DC + transient smoke test (`POR_RAW` pulsed low→high→low against `bias_core`+`por_output_chain` only, not the full assembly) showing a qualitative assert → delayed-release → reassert-on-drop sequence, and a separate 0→3.3 V ramp with `POR_RAW` held low showing `RESETn` stays asserted (max 1.45 mV) throughout — **both explicitly labeled "a solvability/sanity check, not a characterized target"** by that document; no PVT grid, no brownout-shaped waveform, no ramp-rate sweep |
| Reset pulse width, `t_pulse` | not yet derived | none | Unmet — no simulation evidence yet. `design/por_output_chain.md` itself flags `CDG`/`CTIM` as "first-order placeholder timing elements... no reset-pulse-width or deglitch-dwell duration... is a sky130 target" | Same informal transient smoke test above (single corner, single trial) |
| Reset-valid floor, `V_RSTVALID` | not yet derived | none | Unmet — no simulation evidence yet | Same informal below-floor ramp smoke test above |

### 4.3 Quiescent current

| Parameter | Target (draft, unratified) | Measured (`sim/`) | Status | Evidence |
|---|---|---|---|---|
| POR quiescent current, `por-iq` (per `porting-plan.md` §1.1/§2.7's carried accounting structure — a row this repo's own README draft does not separately break out) | not yet derived | none | Unmet — no simulation evidence yet. `porting-plan.md` §2.7 flags gf180's own analogous first-order estimate needed a 3× recost once measured against the real assembly — no presumption this figure is easy on sky130 either | — |
| Total block quiescent current, `iq-total` (independently measured, not assumed = sum of `por-iq` + `temp-iq`, per the same carried structure) | <20 µA / <5 µA (draft, mislabeled per §4.1's note) | none | Unmet — no simulation evidence yet | Informal spot checks in `design/bias_core.md` (≈0.94 µA at `tt`/27 °C) and `design/temp_core.md` (0.73–0.94 µA across a 9-point spot check) both measure the shared `bias_core`+`temp_core` sub-assembly only, at unloaded outputs, with no `por_comparator`/`por_output_chain` current included and no PVT grid — **not usable as an `iq-total` figure** |

### 4.4 Physical

| Parameter | Target (draft, unratified) | Measured (`layout/`) | Status | Evidence |
|---|---|---|---|---|
| Total assembled footprint (`temp_por_top`, post-layout, DRC-clean, LVS-matched) | not yet drafted in this repo | none | Unmet — no layout exists. `layout/README.md`: *"Empty until the first work lands here"* | — |

## 5. Test-plan outline (measurement on the packaged part)

This test plan is written against §2's *proposed* instrumented interface
(the two proposed test outputs and two proposed shared analog lines,
neither wired yet); steps that depend on a proposed-but-unwired signal are
marked. Assumes the block is bonded on a package on a daughterboard, on a
test board that can source/sweep `VDD`, apply controlled dips, and provide
a temperature-controlled environment for the die — mirroring
[gf180-temp-por's own Challenge #3 test-plan structure](https://github.com/2AMLogic/gf180-temp-por/blob/main/docs/chipalooza/challenge-3-proposal.md#5-test-plan-outline-measurement-on-the-packaged-part),
the most directly comparable sibling block.

1. **Bring-up.** Power `VDD` at nominal (3.3 V) via a bench supply. Confirm
   `BIAS_OK` (proposed digital test output, §2.4 — needs wiring first)
   asserts before `RESETn` releases, validating the shared core comes up
   independently of the POR decision.
2. **POR threshold sweep (`VPOR↑`/`VPOR↓`/hysteresis).** Ramp `VDD` at a
   controlled, constant `dVDD/dt` across the 2.97–3.63 V window. Capture
   both `POR_RAW` (proposed test output — separates the comparator's
   threshold decision from the output chain's timing) and `RESETn`
   (dedicated pad, wired today). Repeat at temperature extremes
   (−40 °C, +125 °C) in a chamber. This is the first test in this plan
   that would produce the actual §4.2 VPOR↑/VPOR↓/hysteresis numbers — none
   exist yet even in simulation.
3. **Reset pulse width.** Oscilloscope on `RESETn` (wired today); measure
   at nominal `VDD`/25 °C and at PVT extremes reachable on the bench, and
   after a triggered dip (below).
4. **Brownout / dip response.** Using a programmable supply or a
   pass-transistor dip injector, sweep dip depth, dwell, and falling slew
   rate independently — the three-axis shape `spec/porting-plan.md`
   §2.4/§3.4 calls for, carried from gf180-temp-por's own finding that
   falling *slew rate*, not depth or duration alone, was the actual
   discriminator on that PDK. No simulation prediction exists yet to
   compare silicon against.
5. **Temperature accuracy.** In a temperature chamber, sweep −40…+125 °C
   at fixed `VDD`; measure `PTAT`/`CTAT` (dedicated pads, wired today) with
   a precision DAQ referenced against a calibrated RTD/thermocouple. No
   trim step is included — §2.3 records that no trim ladder exists in the
   schematic to exercise.
6. **Supply sensitivity.** At fixed temperature, sweep `VDD` across
   2.97–3.63 V and re-measure `PTAT`/`CTAT`.
7. **Quiescent current.** Source-meter on `VDD`, measured separately in
   the `RESETn`-asserted/sensor-disabled state and the
   `RESETn`-released/sensor-enabled state.
8. **Fault localization.** For any bench discrepancy, use `POR_RAW`,
   `BIAS_OK`, `VREF`, and `IBIAS` (all proposed test points, §2.4/§2.6 —
   none wired yet) to localize a failure to the bias core, the comparator,
   or the output chain, rather than only observing the packaged `RESETn`
   pin.

This plan describes what *would* be measured once the block reaches the
brief's sign-off bar; it is not evidence of anything today. The pre-layout
simulation work that would need to precede any of it — establishing a PVT
corner grid, a mismatch-Monte-Carlo mechanism, and a supply-ramp-rate
testbench matrix on sky130 (`spec/porting-plan.md` §3, `CLAUDE.md`'s own
standing instruction) — has not started; see "Next steps" below.

## 6. Category note — one combined block, not two

Mirroring gf180-temp-por's own Challenge #3 proposal §6: this is one
combined block by design, not by grouping. The temperature sensor and the
POR supervisor share a single always-on bias/reference core (`bias_core`),
which supplies both the sensing amplifier's bias current and the
comparator's reference/tail current, plus a "core settled" gate
(`BIAS_OK`) both functions' correctness depends on
([DR-002](../../spec/decision-records/DR-002-architecture-carryover.md)).
That sharing is the source of this block's area/Iq efficiency case — one
reference and one bias generator instead of two — and it also means the
shared core's own settling/loading behavior will need to be part of
whatever future temperature-accuracy or POR-threshold Monte Carlo this
repo eventually runs, not characterized in isolation.

## Licensing

This repository is Apache License 2.0 (`LICENSE`), matching the challenge's
stated preference for a standard open license (per the published briefs'
common structure). All modifiable sources — schematics (`design/*.sch`),
exported netlists (`design/netlist/`), the (currently empty) testbench and
simulation harness location (`sim/`), the (currently empty) layout and
DRC/LVS report location (`layout/`), and the decision-record history behind
every ratified value (`spec/decision-records/`) — are public in this
repository under that same license. No separate licensing action would be
needed for a future submission.

## Verification flow (open-source EDA)

- **Schematic entry / simulation**: [xschem](https://xschem.sourceforge.io/)
  (verified against 3.4.7 in this repo, `design/README.md`) +
  [ngspice](https://ngspice.sourceforge.io/), against the open
  [SkyWater sky130](https://github.com/google/skywater-pdk) PDK.
  `PDK_ROOT`/`PDK` are resolved inline by both `design/xschemrc` and
  `design/netlist.py`'s own `find_pdk()`, falling back to the volare
  default (`~/.volare/sky130A`) — no PDK path is ever baked into a
  schematic or netlist.
- **Layout / DRC / LVS**: [klayout-tools](https://github.com/2AMLogic/klayout-tools)
  (`klt`), a headless, scriptable KLayout-based flow, once `layout/` has
  content to check — nothing exists there yet (§4.4).
- No proprietary EDA tool is used anywhere in this design's flow, or is
  expected to be needed for any future step.

## Next steps — what this document does and does not claim

**This document satisfies this issue's (2AMLogic/sky130-temp-por#16)
required acceptance criteria**: a brief-conformant proposal document, I/O
mapped honestly against the assumed slot budget (§2, including the rail
reconciliation the issue's curation note specifically asked for), a
functional description (§3), and a spec table whose every row states a
met/unmet verdict against real `sim/` evidence — currently "unmet, no
evidence" across the board (§4), not fabricated or inferred from schematic
inspection alone.

**It does not claim the brief's full sign-off bar** — post-layout PVT
simulation and DRC/LVS-clean GDS in-repo — which is out of scope for this
issue's closure by its own curation note, and is already tracked
generically by
[issue #4](https://github.com/2AMLogic/sky130-temp-por/issues/4) (the
T1/bronze design-evidence-tier tracker; item 1, design sources, is now
✅ as of issue #10, one delta this document's authoring pass should prompt
a re-derivation of on #4 — items 2–10 remain ❌). Reaching that bar needs,
in order: a ported/built PVT-corner and mismatch-Monte-Carlo sim harness
(`spec/porting-plan.md` §3.1/§3.2, itself the single largest not-yet-filed
item in that plan's §4 recommended-next-issues list), a supply-ramp-rate
and brownout testbench matrix across all four functional cells plus the
top-level assembly (§3.3–§3.6, CLAUDE.md's own standing instruction that
this is the block's whole job), then layout, then post-layout
re-simulation of that same matrix, then DRC/LVS. That is a multi-issue body
of engineering work, not a single-session extension of this proposal —
consistent with this issue's own "Tracked separately" acceptance-criteria
section. The first concrete increment — porting a PVT-corner/mismatch-
Monte-Carlo sim harness from `sky130-bandgap`, per `spec/porting-plan.md`
§4 item 1 — is filed as
[2AMLogic/sky130-temp-por#17](https://github.com/2AMLogic/sky130-temp-por/issues/17),
scoped deliberately to that one prerequisite rather than the whole
downstream matrix, and cross-referencing (not duplicating) issue #4's
generic T1/bronze tracking.

---

*Full evidence trail: [`design/README.md`](../../design/README.md) (schematic
hierarchy, cell status, ratified pinout), [`design/*.md`](../../design/)
(per-cell design rationale and informal spot checks — none are committed
`sim/` evidence), [`spec/porting-plan.md`](../../spec/porting-plan.md) (the
re-derivation and testbench-matrix plan this design still owes),
[`spec/decision-records/`](../../spec/decision-records/) (every
architecture/device-flavor decision's history), [`sim/`](../../sim/) and
[`layout/`](../../layout/) (both empty as of this document — see
`sim/README.md`/`layout/README.md`).*
