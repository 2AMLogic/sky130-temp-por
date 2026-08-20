# DR-001: Supply/device flavor — sky130 3.3 V I/O-class devices (g5v0d10v5 at 3.3 V), not 1.8 V core

- **Status**: proposed (input to a future spec-ratification issue — this
  record does not itself create or ratify `spec/target-spec.md`)
- **Date**: 2026-08-20
- **Decided by**: Loom Builder agent, issue #1 (porting plan)

## Context

This repo's README carries a draft target-spec table with the "Supply" row
marked "confirm against sky130 flavors (1.8 V core vs 3.3/5 V devices)" — an
open question CLAUDE.md flags as needing resolution before design starts,
since it gates device-model selection for every subsequent design step.

`gf180-temp-por` resolved the analogous question for gf180mcu in its own
[DR-001](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-001-supply-flavor.md):
it pinned the 3.3 V gf180mcu core flavor over 5 V, reasoning from (a) the
release-margin arithmetic between the POR threshold and the worst-case-low
rail, and (b) the observation that a 5 V choice would force thick-oxide
devices throughout the signal path, contradicting the block's area-driven
selection rationale. That reasoning is architecture-level (it is about
margin structure, not a specific mV number), so the *pattern* carries; the
specific gf180mcu device names and the "3.3 V vs 5 V" framing do not, because
sky130's device menu is shaped differently (see below).

Sky130 does not offer a discrete "3.3 V core" family the way gf180mcu offers
`nfet_03v3`/`pfet_03v3`. Its menu (confirmed against
`sky130_fd_pr` in the installed PDK, `/home/ubuntu/.volare/volare/sky130/…`,
and against the sibling `sky130-bandgap` repo's device-menu survey,
`spec/topology-survey.md`) is:

- `sky130_fd_pr__nfet_01v8` / `pfet_01v8` (+ `_lvt`/`_hvt`) — 1.8 V core
  devices.
- `sky130_fd_pr__nfet_g5v0d10v5` / `pfet_g5v0d10v5` — 5 V-gate / 10.5 V-drain
  dual-gate-oxide "medium voltage" I/O devices; the gate never exceeds 5 V
  even when a 3.3 V ±10 % rail is applied drain-source, so this family
  covers both 3.3 V and 5 V rail operation from one device.
- `sky130_fd_pr__pnp_05v5_*` — the vertical PNP used for VBE/ΔVBE sensing,
  available independent of which MOS family is chosen.
- `sky130_fd_pr__res_generic_po` / `res_high_po` / `res_xhigh_po` — resistor
  flavors, likewise independent of the MOS choice.
- `sky130_fd_pr__nfet_03v3_nvt` / `nfet_05v0_nvt` — **native (near-zero-Vt)
  devices**. gf180-temp-por's own DR-005 flagged native-device availability
  in gf180mcu as *unconfirmed* ("if native devices are unavailable... the
  fallback is a minimally-biased standard-Vt divider"). Sky130 explicitly
  has this family, per `sky130-bandgap/spec/topology-survey.md`.

Sky130-bandgap — the sibling canary block on this same PDK, which shares the
same bandgap-style shared-reference-core architecture this block's temp
sensor and POR precision comparator are built from (see
[DR-002](DR-002-architecture-carryover.md)) — independently resolved the
identical class of question in its own
`spec/decision-records/DR-001-supply-flavor-scope.md`: it pinned the 3.3 V
I/O-device flavor (`g5v0d10v5` at 3.3 V ±10 %) as its wave-1 target,
deferring a 1.8 V core (Banba-style) variant as a *structurally distinct*
future block rather than a variant of the same core. Its later
`DR-005-ratify-target-spec.md` confirms 3.3 V as the ratified primary flavor,
explicitly matching gf180-bandgap's own precedent.

## Decision

**Pin the sky130 3.3 V I/O-device flavor as this block's supply.** VDD
nominal = 3.3 V, ±10 % ⇒ 2.97–3.63 V. Primary signal-path devices —
`temp_core`, `por_comparator`, `por_output_chain`, and the shared
bias/reference core — use `sky130_fd_pr__nfet_g5v0d10v5` /
`pfet_g5v0d10v5`, operated at the 3.3 V point of their rating (gate ≤5 V,
drain-source within the 3.3 V ±10 % window, well inside the 10.5 V drain
rating). The vertical-PNP sensing elements
(`sky130_fd_pr__pnp_05v5_*`) and resistor references
(`res_generic_po`/`res_high_po`/`res_xhigh_po`) are available regardless of
MOS flavor and are used as [DR-002](DR-002-architecture-carryover.md)
describes. The POR-only startup-assist leg
([DR-002](DR-002-architecture-carryover.md)) uses sky130's confirmed native
devices, `nfet_03v3_nvt` or `nfet_05v0_nvt` — which characterization
(future issue) should choose between. 1.8 V core devices
(`nfet_01v8`/`pfet_01v8`) are not used in the analog signal path in wave 1.

**Why 3.3 V and not 1.8 V**, reasoning from margin structure (the pattern
gf180 DR-001 established, not its numbers):

- Sky130 has no "3.3 V-class core" family to split the difference the way
  gf180mcu's `nfet_03v3` did — the only devices below the I/O family are the
  1.8 V-only core devices.
- A bandgap-referenced comparator with a resistor-divided VDD tap, hysteresis
  network, and enough headroom for a stacked VBE/diode reference needs margin
  that a 1.8 V rail (worst-case-low 1.62 V) leaves little of, once a VBE
  (~0.6–0.7 V), comparator overdrive, and a hysteresis band are stacked —
  consistent with `sky130-bandgap`'s own topology survey treating its 1.8 V
  variant (Banba-style) as a *structurally distinct, harder* core reserved
  for a future block, not a drop-in variant of the 3.3 V primary.
- This block's stated job — supervising the rail that powers the rest of a
  chip built on a shuttle-seat canary process — is most useful against the
  rail sky130 multi-project shuttles (Caravel-class harnesses) standardize
  their I/O/analog domain on, which is 3.3 V, not 1.8 V.
- Choosing the 3.3 V I/O-device flavor lets this block's future
  device-characterization work reuse `sky130-bandgap`'s existing
  `sim/pnp-characterization/`, `sim/resistor-flavor-characterization/`, and
  `sim/mos-matching-characterization/` records — same devices, same 3.3 V
  rail, same PDK version pin (see `spec/porting-plan.md` §2.2) — instead of
  starting characterization from zero.

## Alternatives considered

- **1.8 V core-only flavor** — rejected. No 3.3 V-class core family exists
  in sky130 to bridge the gap the way gf180mcu's `nfet_03v3` did; headroom
  for a stacked-VBE bandgap-referenced comparator plus hysteresis is tight at
  1.8 V, and this repo's own sibling (`sky130-bandgap`) treats its 1.8 V
  variant as a structurally distinct topology (Banba-class), not a
  same-core variant — the same distinction would apply here.
- **Full 5 V/5.5 V-rated operation** (running `g5v0d10v5` at its rated edge
  rather than 3.3 V) — rejected, mirroring gf180 DR-001's rejection of its
  5 V flavor: nothing in this repo's spec or CLAUDE.md calls for a 5 V-rail
  canary, sky130 shuttle-seat chips predominantly standardize on 3.3 V I/O,
  and the same `g5v0d10v5` device family already covers both points — a 5 V
  choice would only widen the re-derivation surface (thresholds, VBE-stack
  margins, resistor ratios) against a rail with no stated consumer.
- **Dual-flavor (design both 1.8 V and 3.3 V variants in wave 1)** —
  rejected, mirroring `sky130-bandgap` DR-001's identical rejection: doubles
  the design and verification surface (two schematics, two Iq budgets, two
  PVT testbench suites) for a canary block whose purpose is the fastest path
  to measured silicon and a klayout-tools friction-protocol proof, not
  multi-flavor coverage.

## Spec lines affected

This repo has no ratified `spec/target-spec.md` yet (see
`spec/porting-plan.md` §4, "recommended next issues"). Once created, its
"Supply" row should read: **3.3 V nominal, ±10 % ⇒ 2.97–3.63 V**, on
`sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5`, citing this record —
replacing the README draft's "confirm against sky130 flavors" placeholder.
Every threshold-, hysteresis-, and Iq-dependent row inherits this as its
device-flavor precondition, per `spec/porting-plan.md` §2.

## Consequences

- Unblocks a future device-characterization issue with a named device list
  (`sky130_fd_pr__pnp_05v5_*`, `res_generic_po`/`res_high_po`/`res_xhigh_po`,
  `nfet_g5v0d10v5`/`pfet_g5v0d10v5`, `nfet_03v3_nvt`/`nfet_05v0_nvt`) instead
  of an open flavor question.
- Makes `sky130-bandgap`'s existing PNP/resistor/MOS-matching characterization
  records directly relevant reference material for this block's own
  characterization work (same PDK pin, same devices, same rail) — see
  `spec/porting-plan.md` §2.2.
- **Narrows, does not ratify**: this record pins the device-flavor input to
  design work. It sets no VPOR, hysteresis, or Iq numeric target — those
  remain open, owned by the future characterization and ratification issues
  named in `spec/porting-plan.md` §4.
- If future characterization shows the 1.8 V core flavor is in fact
  sufficient (e.g., worst-case-low headroom holds against a re-derived
  threshold), this decision must be **superseded** by a new record, not
  silently reinterpreted.
