# Porting plan: gf180-temp-por → sky130-temp-por

- **Status**: DRAFT — this is a planning document, not a ratified spec. No
  row in this document is a target-spec value; it is an input to the future
  spec-ratification issue named in §4.
- **Date**: 2026-08-20
- **Assembled by**: Loom Builder agent, issue #1
- **Decision records produced by this document**:
  [DR-001 (supply flavor)](decision-records/DR-001-supply-flavor.md),
  [DR-002 (architecture carryover)](decision-records/DR-002-architecture-carryover.md)

This document is the first deliverable CLAUDE.md calls for: "the first
deliverable is a porting plan, not a schematic." It answers three questions
for `2AMLogic/gf180-temp-por` → `2AMLogic/sky130-temp-por`: what carries over
from gf180's architecture and spec structure (§1), what must be re-derived
against sky130 device models because it depends on device thresholds and
their corners (§2), and what the POR/sensor testbench matrix must cover
before design work starts (§3). It closes by reconciling against this
repo's own README draft target-spec table (§2.8) and naming the next issues
this plan unblocks (§4).

## §0. Source material

**gf180-temp-por** (read via `gh api`, 2026-08-20):

- `spec/target-spec.md` — the ratified wave-1 target-spec table (355 lines),
  with per-row value tags (`[DR-n]`/`[P]`/`[TBD-#n]`), binding-corner notes,
  and a statistical-basis tag (`[3σ]`/`[CWC]`).
- `spec/decision-records/DR-001` through `DR-028` — **28 files, re-listed
  directly against the GitHub API rather than assumed from the issue's
  citation**. One quirk worth recording so a later reader doesn't treat it
  as a citation error in this document: the directory contains **two**
  `DR-011-*.md` files (`DR-011-brownout-falling-slew-limit.md` and
  `DR-011-temp-accuracy-mismatch-not-met.md`) and **no** `DR-012`. Both
  `DR-011` records are cited below by their full slugs to disambiguate.
- `spec/decision-records/TEMPLATE.md` — the DR format, ported into this
  repo's own `spec/decision-records/TEMPLATE.md` verbatim (with one
  addition — see below).

**sky130-bandgap** (this repo's own filesystem sibling,
`/home/ubuntu/GitHub/sky130-bandgap`): a mature sister canary block on this
same PDK, sharing this block's bandgap-style shared-reference-core
architecture (`temp_core`'s CTAT/PTAT sensing and `por_comparator`'s
threshold reference are both drawn from the same class of vertical-PNP/
resistor bandgap core a stand-alone bandgap block builds). Its
`spec/topology-survey.md`, `spec/decision-records/DR-001-supply-flavor-scope.md`,
`spec/decision-records/DR-005-ratify-target-spec.md`, and its `sim/pdk.json`
+ `sim/pnp-characterization/`, `sim/resistor-flavor-characterization/`, and
`sim/mos-matching-characterization/` directories are cited throughout as a
**second, in-PDK precedent** — one that has already resolved the sky130
device-menu and corner-grid questions this plan needs, on the exact device
classes this block also needs. `spec/decision-records/TEMPLATE.md` there
adds a "Spec lines affected" section beyond gf180's own template; this
repo's `TEMPLATE.md` (§0 above) adopts that addition so all three PDK-family
repos share one DR shape.

**This repo**: `README.md`'s draft target-spec table (reconciled in §2.8),
and `CLAUDE.md`'s standing instructions (device thresholds must be
re-derived, never carried numerically; ramp-rate coverage belongs in the
testbench matrix from the start).

## §1. Circuit carryover

### §1.1 What carries over unchanged (architecture-level)

These are gf180-temp-por decisions argued from device *physics* or
*interface/protocol shape*, not from a gf180mcu-specific numeric value. Each
is adopted here, mapped onto sky130's device menu, in this repo's own
[DR-002](decision-records/DR-002-architecture-carryover.md):

| Carries over | gf180 source | Why it's architecture-level, not threshold-level |
|---|---|---|
| ΔVBE/VBE (PTAT/CTAT) bandgap-style temp-sensor core, plain (not chopped), single-point 25 °C gain trim on the PTAT path | [DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md) | Argued against resistor-only and MOSFET-subthreshold alternatives on BJT VBE's tighter, physics-set mismatch vs. resistor tolerance/MOS-Vt mismatch — a device-class comparison, not a gf180mcu number. |
| Bandgap-referenced POR comparator (absolute-voltage reference vs. a VDD tap) with resistor-network positive-feedback hysteresis | [DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md) | Argued against a VBE-stack (uncancelled tempco) and a VDD-fraction divider (cannot detect an absolute voltage) — both structural rejections independent of process node. |
| One shared bias/reference core between the temp sensor and POR comparator, plus a separate, non-precision POR-only startup-assist leg that predates it | [DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md) | Resolves a chicken-and-egg constraint (POR must work before anything else is biased) that exists on any PDK; the six-step startup ordering is a sequencing argument, not a voltage number. |
| Hysteresis (comparator's job) vs. deglitch (output chain's job, separate time-domain filter) — explicit ownership split | [DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md) | A functional-decomposition argument: hysteresis is not a time filter and a time filter is not a static threshold band, on any process. |
| Fixed-width reset pulse via a current-starved-capacitor one-shot; no oscillator/counter/config interface | [DR-003](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-003-por-reset-pulse.md), [DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md) | Argued from Iq-budget class (oscillator+counter is a materially higher-Iq architecture) and absence of a consumer requiring programmability — neither is gf180mcu-specific. |
| `RESETn` active-low, push-pull drive; below-floor requirement (a pull-down that works with no bias, handing off to comparator-driven control only once the shared core's floor is cleared) | [DR-004](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-004-reset-polarity-drive.md) | Active-low degrades to "asserted" passively near 0 V on any single-rail process; open-drain's external-pull-up dependency is rejected for the same reason on any process. |
| Pinout shape: `VDD`, `VSS`, `PTAT`, `CTAT`, `RESETn` (5 pads), no trim/config pins in wave 1 | [DR-001](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-001-supply-flavor.md), [DR-002](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-002-temp-interface.md), [DR-004](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-004-reset-polarity-drive.md) | Follows from the interface decisions above, not from a device number. |
| Trim mechanism: metal-strap short-out ladder on the PTAT gain resistor (fuse/OTP-ready hook-up point), no POR trim node in wave 1 | DR-005 stance; mechanism filled by gf180 issue #9 | A layout/process-portable mechanism (a mask-level metal strap), not a device threshold. |
| Analog-only wave-1 interface (`PTAT`+`CTAT` pads); accuracy judged at the pin voltage via the sensor's V(T) transfer function; digital-via-SAR explicitly deferred as stretch | [DR-002](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-002-temp-interface.md) | A scope decision (what wave 1 ships), independent of device thresholds. |
| Iq accounting structure: `por-iq` (always-on state, `RESETn` asserted, sensor disabled, includes whatever shared-core current is live for the threshold decision) + `temp-iq` (incremental, sensor enabled) + `iq-total` (independently verified, not assumed equal to the sum of the two ceilings) | [DR-007 amendment A7](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md), reinforced by [DR-018](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-018-por-iq-recost.md) | An accounting-rule structure (which state each row is quoted in, and that the total must be independently measured rather than reconstructed), not a µA number. |
| Target-spec table structure: value tags (`[DR-n]`/`[P]`/`[TBD-#n]`), a named binding corner per row, and a statistical-basis tag (`[3σ]` mismatch-inclusive Monte Carlo vs. `[CWC]` corner-worst-case) per row | [DR-007](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md) | A documentation/traceability convention, portable to any PDK — adopted directly for this repo's own future `spec/target-spec.md` (§4). |
| DR record format itself (Status/Date/Decided by, Context, Decision, Alternatives considered, Consequences) | `TEMPLATE.md` | A process convention; ported verbatim into this repo's own `spec/decision-records/TEMPLATE.md`, with the "Spec lines affected" section `sky130-bandgap`'s template already added for this PDK family. |

### §1.2 What needs re-deciding for sky130 (not merely re-numbering)

| gf180 decision | Why it needs a fresh sky130 decision, not a value swap |
|---|---|
| Supply/device flavor: gf180mcu 3.3 V core ([DR-001](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-001-supply-flavor.md)) | Sky130 has no discrete "3.3 V core" family to map `nfet_03v3` onto — resolved here in [DR-001](decision-records/DR-001-supply-flavor.md), §2.1. |
| Startup-assist leg device: "native/zero-Vt if available, else a minimally-biased standard-Vt divider" ([DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md)) | gf180mcu's native-device availability was *unconfirmed* at authoring time; sky130's is *confirmed* (`nfet_03v3_nvt`/`nfet_05v0_nvt`, per `sky130-bandgap/spec/topology-survey.md`). This is a strictly better starting position, not a like-for-like swap, and the choice between the two native flavors is new (§2.6). |
| Corner-grid shape: 9 process corners (`tt, ff, ss, fs, sf, res_ff, res_ss, bjt_ff, bjt_ss`) ([DR-006](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-006-sim-harness-port.md)) | Sky130's corner library is shaped differently: PNP `Is`/`Bf`/`Nf` ride on the **same** `tt/ff/ss/sf/fs` sections as MOS (no separate `bjt_ff`/`bjt_ss` axis), while resistor/cap value skew is its **own** orthogonal `ll`/`hh` axis. A straight rename does not produce a correct grid — §3.1 works this out from `sky130-bandgap/sim/pdk.json`, the one place this has already been verified against the installed PDK. |
| Sim-harness port source (`gf180-bandgap` → `gf180-temp-por`, [DR-006](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-006-sim-harness-port.md)) | This repo's analogous harness-port source is `sky130-bandgap`, not `gf180-bandgap` — a different repo with its own runner/corner conventions (§3.1). Porting it is future work (§4), not decided by this document. |
| Numeric ramp-rate envelope (1 V/s…1 V/µs) and brownout dip parameters (VPOR↓,min, `T_dip,min`, falling-slew limit) ([DR-007](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md), [DR-011-brownout-falling-slew-limit](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-brownout-falling-slew-limit.md), [DR-027](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-027-por-brownout-tdip-recost.md)) | These bind at specific process corners of specific gf180mcu devices (startup-assist leg headroom, shared-core settling, comparator response time) — they are exactly the numbers CLAUDE.md says must never carry. The *shape* of the sweep that finds them carries (§3.4); the numbers do not. |
| All VPOR↑/VPOR↓/hysteresis/Iq/pulse-width numeric targets | [DR-007](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md), measured in `target-spec.md` §§3–5 | Device-threshold-dependent by definition; §2 below. |

### §1.3 A caution this plan takes from gf180's own history: the *same* topology already missed a target once

Two of gf180's ratified `[P]` targets were **measured against the adopted
topology on gf180mcu itself and found not met** under mismatch:
`temp-accuracy-untrimmed` (±3 °C target, measured ±19.2…19.6 °C at 3σ — 6.5×
over) and `temp-accuracy-trimmed` (±1.5 °C target, measured ±7.1…7.7 °C at
3σ — 4.9× over), per
[DR-011-temp-accuracy-mismatch-not-met](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md).
Likewise `por-iq`'s original <1 µA target needed a 3× recost to <3.0 µA once
measured on the real assembly
([DR-018](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-018-por-iq-recost.md)).
Adopting the same topology here ([DR-002](decision-records/DR-002-architecture-carryover.md))
does **not** imply these targets are achievable on sky130 either — that is
an open, re-derivable question, not a presumption this plan makes in either
direction. §2.8 flags this explicitly against the README's draft accuracy
row.

## §2. What must be re-derived for sky130

Everything in this section is threshold/device-dependent and therefore
`[TBD]` until a future characterization issue produces `sim/` evidence. No
number from gf180-temp-por's `target-spec.md` is repeated here as a sky130
value.

### §2.1 Supply-flavor choice — resolved in this plan

Per [DR-001](decision-records/DR-001-supply-flavor.md): sky130 3.3 V
I/O-class devices (`sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5`, gate
≤5 V, operated at 3.3 V ±10 % ⇒ 2.97–3.63 V), not the 1.8 V core family.
This is a genuinely new decision (§1.2), not a carryover, and is captured as
this plan's own decision record rather than asserted inline here.

### §2.2 Device menu and where its characterization data already exists

| Role | gf180mcu device (not carried) | sky130 device (this repo) | Existing characterization to reuse |
|---|---|---|---|
| VBE/ΔVBE sensing element | vertical PNP (`nfet_03v3`-flavor process) | `sky130_fd_pr__pnp_05v5_*` | `sky130-bandgap/sim/pnp-characterization/`, `sim/pnp-mismatch/` — same device family, same PDK pin. Must still be re-run/re-read against this block's own emitter-area/current ratio and bias point, not assumed to transfer verbatim. |
| PTAT-gain and POR-divider resistors | poly/nwell resistor flavors | `sky130_fd_pr__res_generic_po`/`res_high_po`/`res_xhigh_po` | `sky130-bandgap/sim/resistor-flavor-characterization/`, `sim/res-array-head-resistance/` — same flavors; `sky130-bandgap/spec/topology-survey.md` already records `res_xhigh_po`'s stronger, opposite-sign TC vs. `res_high_po`'s more linear one, relevant to which flavor is chosen for absolute-TC-cancellation legs vs. ratio-tracking legs here. |
| Comparator / output-chain MOS | `nfet_03v3`/`pfet_03v3` | `sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5` | `sky130-bandgap/sim/mos-matching-characterization/`, `sim/mos-mirror-sizing-extended/` — same family; comparator-specific offset/mismatch still needs its own testbench (§3.2), not reuse of a mirror-sizing result. |
| POR startup-assist leg | native/zero-Vt if available (unconfirmed at gf180 DR-005 authoring time) | `sky130_fd_pr__nfet_03v3_nvt` or `nfet_05v0_nvt` (confirmed available) | No existing characterization in `sky130-bandgap` (it does not need a startup-assist leg — a bandgap has no analogous "before anything is biased" POR requirement). This is genuinely new characterization work, owned by a future issue (§4), not reusable from the sibling repo. |

### §2.3 POR trip points (VPOR↑/VPOR↓) and hysteresis

Must be characterized from: the resistor-divider ratio setting the VDD tap,
the comparator's offset/mismatch (from the MOS-matching characterization
above), and the reference voltage the divider is compared against (drawn
from the shared bandgap-style core). gf180's own margin-arithmetic
*pattern* carries (§1.1's "bandgap-referenced comparator" row): whatever
VPOR↑ sky130 lands on must leave comfortable margin against the worst-case
low rail set by [DR-001](decision-records/DR-001-supply-flavor.md) (2.97 V).
No specific volt figure carries.

Hysteresis is not an independently free parameter — gf180's own
[DR-007 amendment A2](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md)
*constructs* VPOR↓ from VPOR↑ and V_hys, and caps V_hys specifically to keep
VPOR↓,min from dropping below a downstream digital domain's minimum
operating voltage (`por-digital-min-vdd`, itself integrator-supplied and
marked `[TBD]` in gf180's own ratified table). This construction — not any
of its numbers — carries: sky130's hysteresis ceiling must likewise be set
against a re-derived VPOR↑,min and an (also-TBD) `por-digital-min-vdd` for
this repo, not asserted as a bare "≥100 mV" floor with no ceiling. §2.8
flags this against the README draft.

Also carrying as methodology, not value: gf180's post-layout finding
([DR-021](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-021-por-hysteresis-quasi-static-scope.md),
`sim/` fix in gf180 issue #206) that a fixed-*duration* ramp deck
accidentally makes the supply axis double as a ramp-rate axis, confounding
hysteresis with a rate-dependent reference-displacement term. The fix —
derive the ramp from a constant `dVDD/dt` and add a second, half-rate
quasi-staticity-guard segment whose result must track the primary segment
within a bound — should be built into this repo's own harness from day one
(§3.6), not rediscovered after a post-layout failure.

### §2.4 Brownout behavior

gf180's own characterization work found the falling-**slew rate**, not the
dip's depth or duration, is the actual discriminator for whether reset
re-asserts during a brownout
([DR-011-brownout-falling-slew-limit](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-brownout-falling-slew-limit.md)) —
a dip well above VPOR↓,min but *fast enough* failed identically to one below
it. The falling-slew limit was then re-cost once against post-layout
parasitics
([DR-019](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-019-brownout-falling-slew-postlayout-recost.md)),
and the minimum-dip-duration bound (`T_dip,min`) was separately re-cost
against the *real* delivered bias current of the assembled circuit rather
than an idealized estimate
([DR-027](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-027-por-brownout-tdip-recost.md)).
None of these numeric bounds carries to sky130 — the mechanism they
characterize (a slew-rate-dependent mirror-bank starvation, tied to sky130's
own bias-core devices) must be independently characterized. The **three-axis
shape** of the sweep that found this (depth × duration × falling-slew-rate,
not depth-and-duration alone) carries directly into §3.4.

Separately, gf180's `por-brownout` row also confirmed a **structurally
distinct** failure mode: a VDD-level glitch (rather than a `POR_RAW`-domain
dip) is not rejected by the deglitch dwell at all, because the dwell can
only ever filter a disturbance presented at `POR_RAW`
([DR-014](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-014-por-glitch-vdd-level-immunity.md)),
and the boundary at which a VDD-level glitch is instead a rail collapse the
block's own logic cannot survive was separately characterized
([DR-017](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-017-por-glitch-representative-depth.md)).
This scoping distinction — two structurally different disturbance classes
needing two separate testbench axes — carries into §3.5.

### §2.5 Temperature-sensing-element characterization

Per [DR-002](decision-records/DR-002-architecture-carryover.md)'s adopted
core: the PTAT slope (`K₀`, mV/K), CTAT slope and 27 °C intercept, the
output headroom bound, supply sensitivity, and — critically, per §1.3 —
whether the plain (unchopped), single-point-trim architecture actually
clears the accuracy target under sky130's own PNP/resistor/amplifier
mismatch, must all be independently measured. gf180's own attribution
breakdown
([DR-011-temp-accuracy-mismatch-not-met](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md))
found amplifier input-offset mismatch, the gain-mirror ratio, and PNP ΔVBE
mismatch each individually busting the ±3 °C budget on gf180mcu — a
breakdown methodology (attribute the miss to named error terms, not just
report the aggregate) that carries directly into this repo's own future
accuracy-Monte-Carlo testbench, even though the individual term sizes do
not.

### §2.6 Supply-flavor-adjacent: startup-assist native-device choice

New question, not present in gf180's own decision set (its native-device
availability was unconfirmed, so it never had to choose *between* two native
flavors): `nfet_03v3_nvt` vs. `nfet_05v0_nvt`. Owned by a future
characterization issue against each device's threshold-voltage spread,
minimum reliable operating voltage, and off-state leakage in the
[DR-001](decision-records/DR-001-supply-flavor.md) 3.3 V rail context — not
resolved by this plan.

### §2.7 Iq budget

The accounting *structure* carries (§1.1: `por-iq`/`temp-iq`/`iq-total`,
each in a defined state, `iq-total` independently verified). The numbers do
not, and per §1.3, gf180's own first-order estimate for `por-iq` needed a 3×
recost once measured against the real assembled shared-core current draw
([DR-018](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-018-por-iq-recost.md)).
This is a general risk to flag for sky130, not a specific prediction: any
Iq figure produced before block-level (not sub-cell) measurement should be
treated as provisional.

### §2.8 Reconciliation against this repo's README draft target-spec table

| README draft row | Disposition |
|---|---|
| Operating temperature −40…+125 °C | **Holds.** Device-independent range, matches gf180 [DR-002](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-002-temp-interface.md)/[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md). |
| Temperature error, untrimmed ±3 °C / ±1.5 °C trimmed | **Flag — do not carry as presumptively achievable.** This exact target, on this exact topology, was measured **not met** on gf180mcu itself under 3σ mismatch (6.5× and 4.9× over budget respectively, [DR-011-temp-accuracy-mismatch-not-met](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md)). Sky130's own PNP/resistor/amplifier mismatch must be characterized (§2.5) before this row can be ratified either way — it may hold, miss, or need a recost through its own decision record, exactly as gf180's did. |
| Sensor output: analog PTAT+CTAT pads / digital SAR stretch | **Holds.** Device-independent interface scope, [DR-002](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-002-temp-interface.md). |
| POR thresholds VPOR↑/VPOR↓: "re-derive against sky130 models" | **Confirmed correct as drafted** — cannot be carried, per §2.3. The README's own placeholder is accurate; this plan adds the *pattern* (margin arithmetic vs. the [DR-001](decision-records/DR-001-supply-flavor.md) rail) that governs the re-derivation. |
| POR hysteresis "≥100 mV" (no upper bound) | **Needs adjustment.** gf180's ratified table has a min/typ/max structure (100/150/250 mV) with the max specifically *constructed* from VPOR↑ and a downstream digital floor ([DR-007 amendment A2](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md)); this repo's draft has only a floor. Recommend adding an upper-bound row once VPOR↑ and `por-digital-min-vdd` are re-derived (§2.3) — an unbounded hysteresis is not a safe target to carry forward even structurally. |
| Supply: "confirm against sky130 flavors (1.8 V core vs 3.3/5 V devices)" | **Resolved by this plan.** [DR-001](decision-records/DR-001-supply-flavor.md): 3.3 V I/O-class devices (`g5v0d10v5` family), 2.97–3.63 V. |
| Iq (block total) "< 20 µA / < 5 µA" | **Needs adjustment — likely a mislabeled carryover.** In gf180's ratified table, `<20 µA`/`<5 µA` is `temp-iq` (the sensor's *incremental* current above `por-iq`, [DR-007 amendment A7](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md)), not the block total — the block total (`iq-total`) is a separately ratified `<21 µA` figure, with `por-iq` itself a third, independently re-cost `<3.0 µA` row (§2.7). This repo's draft row is titled "Iq (block total)" but carries the *sensor-only* numbers. Recommend the same three-row split when a real target-spec table is built (§4), not a single conflated row — and, per §2.7, none of the three numbers should be carried forward even once split correctly. |
| Supply-ramp coverage: "ramp-rate sweep in the POR testbench matrix" | **Holds as a structural requirement**, elaborated in §3.3–3.4 below. No numeric envelope is asserted here. |

## §3. Testbench matrix

CLAUDE.md: "PVT corners on every recorded result... supply-ramp-rate
coverage belongs in the testbench matrix from the start, because the
block's whole job is correct behavior across temperature and supply ramp."
This section defines the grid shape and sweep axes; it does not set pass/fail
numeric bounds, which are downstream of §2's re-derivation work.

### §3.1 PVT corner grid

Gf180-temp-por's grid was 9 process corners
(`tt, ff, ss, fs, sf, res_ff, res_ss, bjt_ff, bjt_ss`) × 3 temperatures
(−40/27/125 °C) × 3 supplies (2.97/3.30/3.63 V) = 81 points
([DR-006](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-006-sim-harness-port.md)).
Sky130's corner library is shaped differently — confirmed against the
installed PDK via `sky130-bandgap/sim/pdk.json` (that repo's own
reproducibility pin, verified empirically against
`libs.tech/combined/sky130.lib.spice`'s actual `.lib` sections, not assumed
from naming convention):

- **`tt`, `ff`, `ss`, `sf`, `fs`** — the standard MOS corners. These **also**
  gate the vertical PNP's `Is`/`Bf`/`Nf` parameters through the same
  `corners/<name>/nonfet.spice` includes — sky130 has **no separate
  `bjt_ff`/`bjt_ss` axis** the way gf180mcu's grid does. A straight rename
  of gf180's 9-corner list would be wrong twice: it would invent a
  nonexistent axis and miss the real one below.
- **`ll`, `hh`** — a **separate, orthogonal** resistor/capacitor-value skew
  axis. All five MOS/BJT corners above (`tt`/`ff`/`ss`/`sf`/`fs`) give
  byte-identical resistor values (confirmed empirically in
  `sky130-bandgap/sim/pdk.json`'s own notes: all five `.lib` sections
  include the same `parameters_res_nom.spice`) — resistor-value process
  sensitivity **only** shows up on the `ll`/`hh` axis, which instead swaps
  in `parameters_res_low.spice`/`parameters_res_high.spice`. `hl`/`lh`
  (resistor tied to the *other* axis's cap corner) also exist in the PDK but
  are not part of `sky130-bandgap`'s own pinned default grid.
- Local-mismatch sections (`tt_mm`, etc., `MC_MM_SWITCH=1`) and global
  process-Monte-Carlo sections (`MC_PR_SWITCH=1`) exist as a **separate**
  mechanism from the deterministic corner axis — not a corner to sweep
  point-by-point, but the mechanism §3.2's `[3σ]` rows use.

**Recommended default grid for this repo** (mirroring gf180
[DR-006](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-006-sim-harness-port.md)'s
own reasoning that the safe grid must be the default, not opt-in, because
passive-device skew directly moves the PTAT gain ratio and the POR
divider): **5 MOS/BJT corners × 2 resistor/cap-skew corners (`ll`, `hh`) ×
3 temperatures × 3 supplies = 90 points**, once the harness is ported (§4) —
larger than gf180's 81-point grid, and a different *shape*, not a
renumbering of the same axes. This should be re-confirmed against
whichever `open_pdks`/PDK version this repo's own harness pins (mirroring
`sky130-bandgap/sim/pdk.json`'s own reproducibility-pin pattern) before
being treated as final, exactly as `sky130-bandgap` itself treats its own
`process_corners` list as "verified against the installed PDK," not assumed.

Supply points: 2.97/3.30/3.63 V — this specific *range* does carry
unchanged from gf180's grid, but only because both repos independently
land on the same 3.3 V ±10 % nominal (gf180 [DR-001](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-001-supply-flavor.md),
this repo's own [DR-001](decision-records/DR-001-supply-flavor.md)) — it is
a coincidence of both repos choosing the same nominal voltage, not a
device-independent fact, and must be re-derived, not assumed, if
[DR-001](decision-records/DR-001-supply-flavor.md) is ever superseded.

### §3.2 Statistical basis

Carries as methodology from gf180
[DR-007 amendment A5](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md):
every accuracy and threshold row (mismatch-dominated: temperature accuracy,
both POR threshold edges, hysteresis) must be evaluated **[3σ]** — process
*plus* local mismatch, Monte Carlo, N ≥ 500, at the row's own binding point
— using sky130's `tt_mm`-class mismatch sections (already in production use
in `sky130-bandgap/sim/pnp-mismatch/`, confirming the mechanism is available
and working on this PDK). Budget/limit rows (Iq, pulse width, ramp envelope,
area) are **[CWC]** — worst point of the deterministic corner grid, mismatch
not modeled. A row with no stated statistical basis is not ratifiable, per
the same reasoning that drove gf180's own amendment.

### §3.3 Supply ramp-rate sweep

Structural requirement (README, CLAUDE.md); the numeric envelope is
`[TBD]` per §2. The **shape** of the sweep carries from gf180's own history:

- Multiple rates spanning the full slow-to-fast envelope, **not just the two
  endpoints** — gf180's release-edge chatter (a shared-`IBIAS`-node
  relaxation loop between the POR output stage and the temperature sensor's
  enable pin) was only found by sweeping mid-envelope rates across the full
  corner grid, and was root-caused twice before the actual mechanism was
  identified
  ([DR-015](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-015-por-ramp-rate-chatter-root-cause.md)
  superseded by
  [DR-016](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-016-por-ramp-rate-chatter-release-latch.md)).
  A single-rate smoke test would not have surfaced it.
- Each rate swept across the **full** §3.1 grid, not a reduced "obviously
  worst" corner subset — gf180's own binding-corner predictions were wrong
  for two POR rows until the full 81-point grid was actually run
  ([DR-009](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-009-por-reset-pulse-binding-corner.md)):
  a topology-specific reason can flip which corner binds, and a predicted
  binding corner is a prediction, not evidence, until measured.
- Pass/fail criterion shape (device-independent): `RESETn` low from 0 V
  throughout the ramp, released once and only once, no glitch, no double
  pulse — carries directly from gf180's own `por-ramp-rate` row definition.
- **Testbench-construction technique**, not just the sweep shape: derive the
  ramp from a constant `dVDD/dt` (not a fixed duration), and include a
  second, half-rate quasi-staticity-guard segment whose measured result must
  track the primary segment within a bound. This is the fix gf180 needed
  *after* a fixed-duration deck confounded its supply and ramp-rate axes and
  produced a spurious hysteresis failure
  ([DR-021](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-021-por-hysteresis-quasi-static-scope.md),
  fixed in gf180 issue #206) — building it in from day one avoids
  rediscovering the same confound on sky130's own harness.

### §3.4 Brownout / dip matrix

Per §2.4: a **three-axis** sweep — dip depth × dip duration × falling-slew
rate — not depth-and-duration alone. gf180's own single-axis (depth/duration
only) testbench passed at first and then was shown by a dedicated falling-slew
characterization to fail across most of the grid at faster (but still
envelope-inside) slew rates
([DR-011-brownout-falling-slew-limit](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-brownout-falling-slew-limit.md)) —
a testbench that never varied slew rate would have shipped a false pass.
Sweep boundaries (how deep, how long, how fast) are themselves `[TBD]`,
re-derived from sky130's own bias-core mirror-bank slew capability (§2.4,
§2.6) and the shared-node dynamics of whichever startup-assist device is
chosen.

Additionally: any deglitch-dwell-derived timing bound must be measured
against the **real** delivered bias current of the fully assembled circuit,
not an idealized fractional-nominal assumption — gf180's own `T_dip,min`
needed re-costing (10 µs → 30 µs) once measured against the actual delivered
`IBIAS` rather than an assumed 0.5× nominal
([DR-027](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-027-por-brownout-tdip-recost.md)).
This repo's own brownout-dwell testbench should be block-assembly-level from
the start, not a standalone sub-cell test that gets re-verified later.

### §3.5 Glitch immunity — two structurally distinct axes

Per §2.4: the POR output chain's deglitch dwell only ever filters a
disturbance presented at the internal `POR_RAW` node; it structurally cannot
reject a disturbance injected directly at `VDD`
([DR-014](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-014-por-glitch-vdd-level-immunity.md)).
The testbench matrix must therefore carry **two separate** glitch-injection
axes, not one "glitch test":

1. A `POR_RAW`-referenced dip/glitch, exercising the deglitch dwell directly.
2. A `VDD`-level glitch, swept across depth × duration, characterizing the
   separate boundary between "the dwell's designed job is visibly working"
   and "the rail is simply too low for the block's own logic to hold state"
   — gf180's own boundary characterization found this a sharp, corner- and
   process-independent depth threshold with no duration dependence across
   nearly four decades of duration
   ([DR-017](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-017-por-glitch-representative-depth.md)).

Neither axis's numeric bound carries; the requirement to test them as two
distinct conditions does.

### §3.6 Post-layout re-verification

Structural requirement, not optional: gf180's post-layout extraction moved
both the brownout falling-slew margin (ratified bound failed 5/81 points
post-layout, requiring the
[DR-019](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-019-brownout-falling-slew-postlayout-recost.md)
recost) and the worst-case hysteresis corner (11 mV over ceiling at one
point, root-caused and scoped by
[DR-021](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-021-por-hysteresis-quasi-static-scope.md)).
Every row in §3.1–§3.5's matrix must be re-run against the post-layout
netlist before any claim is finalized — a schematic-only pass is not
sufficient evidence, on either PDK.

Also carried, as a measurement-convention lesson rather than a value: area
must be measured as the assembled top cell's own bounding-box footprint, not
the sum of unassembled sub-cell boxes or a raw drawn-polygon count
([DR-022](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-022-area-post-layout-measurement.md)) —
apply this convention verbatim once this repo has a top-cell layout to
measure.

## §4. Recommended next issues (not filed by this document)

This porting plan is itself the gate CLAUDE.md calls for before schematic
work starts; it does not open the follow-on issues, which belong to the
repo's normal curation flow. For the record, the gaps this plan surfaces
are:

1. **Sim-harness port** from `sky130-bandgap` (mirroring gf180
   [DR-006](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-006-sim-harness-port.md)'s
   own port from `gf180-bandgap`) — establishes the §3.1 corner grid and
   §3.2 mismatch-Monte-Carlo mechanism as running infrastructure, and is a
   prerequisite for every characterization issue below. **DONE** (issue
   #17): `sim/bin/{corner-run.py,sim_common.py,pdk-env.sh}`, `sim/pdk.json`,
   `sim/spiceinit`, `sim/xschemrc` ported from `sky130-bandgap`'s own
   harness and re-verified against this repo's own installed PDK (exact
   `open_pdks` commit match, not assumed). The ported default
   process-corner grid is the precedent's own flat 7-entry list
   (`tt/ss/ff/sf/fs/ll/hh`, `sim/pdk.json`), **not** the 90-point
   MOS×resistor cross product this section's own text above describes —
   that cross product does not exist in the harness being ported (traced at
   issue #17 curation time: `Corner.process` is a single string field,
   every `.lib` line takes exactly one corner name) and remains future work
   for whichever issue builds the full PVT/mismatch testbench matrix (item
   2 below). `sim/bias-core-smoke/` (schematic-driven, full 45-point
   tt/ss/ff/sf/fs × 3 temp × 3 supply grid) and `sim/pnp-mismatch/` (bespoke
   Monte Carlo script; both `MC_MM_SWITCH=1` local mismatch and
   `MC_PR_SWITCH=1` global process Monte Carlo confirmed non-degenerate
   against this repo's own PNP topology — the real 1-vs-8-parallel array
   `bias_core`/`temp_core` use, not sky130-bandgap's small/large
   device-size pair) are the first two experiments proving the ported
   harness runs against this repo's own `design/netlist/*.spice`, not just
   `sky130-bandgap`'s. `sim/bias-core-smoke`'s own committed record also
   surfaced a genuine `bias_core` finding (spurious high-current DC
   solution at `tt`/27 °C at both supply extremes) the harness's own
   full-grid sweep found and a prior spot check could not — filed as
   [issue #19](https://github.com/2AMLogic/sky130-temp-por/issues/19),
   downstream circuit-behavior work, not part of this item.
2. **Device characterization** against the §2.2 device list — PNP
   VBE/mismatch, resistor flavor tempco/tolerance, `g5v0d10v5` MOS
   threshold spread, and (new work, §2.6) native-device characterization for
   the startup-assist leg.
3. **Schematic entry**, against the [DR-002](decision-records/DR-002-architecture-carryover.md)
   hierarchy (`bias_core`, `por_startup_assist`, `por_comparator`,
   `por_output_chain`, `temp_core`, `temp_buffer`).
4. **A ratified `spec/target-spec.md`** for this repo, structured per §1.1's
   carried table conventions (value tags, binding corner, statistical
   basis), populated from the characterization work above rather than from
   this plan's own (deliberately numberless) analysis.

This document does not itself create `spec/target-spec.md` — creating a
ratifiable numeric table before any sky130 characterization evidence exists
would repeat exactly the mistake CLAUDE.md warns against (asserting a
threshold-dependent number with no testbench behind it).
