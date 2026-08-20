# DR-002: Adopt gf180-temp-por's shared-core / two-tier POR architecture as sky130's starting topology

- **Status**: proposed (input to a future schematic-entry issue — this
  record adopts a starting topology, it does not verify it against sky130
  models)
- **Date**: 2026-08-20
- **Decided by**: Loom Builder agent, issue #1 (porting plan)

## Context

`gf180-temp-por`'s
[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md)
(the architecture survey, decided by issue #3) is the topology-selection
gate for the whole gf180 block. After considering and rejecting
resistor-ratio-only and MOSFET-subthreshold temperature sensing, a
VBE-stack POR threshold, and a subthreshold-divider used as the *precision*
threshold (rather than as a coarse assist), it recommended six
architecture-level choices — enumerated in `spec/porting-plan.md` §1.1, each
argued from device physics (BJT VBE tempco/mismatch, a divider's inability
to detect an absolute voltage, oscillator/counter Iq cost) rather than from
gf180mcu-specific numbers. `spec/porting-plan.md` §1 finds none of the six
choices is threshold- or device-value-specific; each is a topology-shape
decision.

Sky130 offers every device class the recommendation depends on: a vertical
PNP (`sky130_fd_pr__pnp_05v5_*`), resistor flavors
(`res_generic_po`/`res_high_po`/`res_xhigh_po`), MOS devices for the
comparator and output stage (`nfet_g5v0d10v5`/`pfet_g5v0d10v5`, per
[DR-001](DR-001-supply-flavor.md)), and — unlike gf180mcu, whose native-device
availability gf180 DR-005 flagged as *unconfirmed* — a **confirmed**
native/near-zero-Vt device family (`nfet_03v3_nvt`/`nfet_05v0_nvt`) for the
startup-assist role DR-005's Decision → Shared infrastructure describes.

## Decision

**Adopt gf180-temp-por DR-005's topology, unchanged in shape, as this
repo's starting architecture for wave 1**, mapped onto sky130's device menu
per [DR-001](DR-001-supply-flavor.md):

1. **Temperature sensor**: ΔVBE/VBE core on `sky130_fd_pr__pnp_05v5_*`
   vertical PNPs (a CTAT term from one diode-connected PNP's VBE, a PTAT
   term from ΔVBE across an emitter-area/current-ratioed pair), PTAT gain set
   by a `res_generic_po`/`res_high_po`/`res_xhigh_po` resistor ratio, analog
   `PTAT`+`CTAT` output pads, plain (not chopped), single-point 25 °C gain
   trim on the PTAT amplification path.
2. **POR**: bandgap-referenced comparator (drawing off the shared core's
   reference) with resistor-network positive-feedback hysteresis, compared
   against a resistor-divided VDD tap on the `g5v0d10v5` device family.
   This engine is not what asserts reset during power-up ramp (see #3).
3. **Shared infrastructure**: one shared bias/reference core between the
   temperature sensor and the POR precision comparator, plus a **separate,
   non-precision POR-only startup-assist leg** built on sky130's confirmed
   native devices (`nfet_03v3_nvt` or `nfet_05v0_nvt` — choice deferred to a
   future characterization issue), predating the shared core in the
   six-step startup ordering gf180 DR-005's Decision section lays out:
   assist leg conducts first and holds reset asserted before the shared core
   is biased; the shared core's own start-up kick brings it up; the
   precision comparator becomes authoritative only once the shared core
   settles; reset deasserts only once both the shared core is valid and the
   hysteretic threshold decision clears, held for the reset-pulse width; the
   temperature sensor's enable is gated by POR's deasserted output, keeping
   it out of the chicken-and-egg problem entirely.
4. **Deglitch/hysteresis ownership split**: hysteresis (the static,
   hold-near-threshold spec) is the comparator's own positive-feedback
   network; deglitch (rejecting a narrow, fast transient) is a **separate**
   time-domain filter owned by the POR output chain. These are complementary,
   not substitutable — carried unchanged.
5. **Reset pulse**: fixed-width (target re-derived, see
   `spec/porting-plan.md` §2), current-starved-capacitor one-shot referenced
   off the shared core's bias current — no oscillator, no counter, no
   configuration interface. Mirrors this repo's own DR-003/DR-004-equivalent
   carryover (polarity `RESETn` active-low, push-pull drive, below-floor
   pull-down handoff — `spec/porting-plan.md` §1.1).

This is adoption of a **starting point**, not verification. Every numeric
parameter this topology needs — VBE tempco, resistor tempco/tolerance,
native-device threshold spread, comparator offset, mismatch, achievable Iq —
must still be characterized against sky130 models before any value is
claimed. CLAUDE.md's "no claim without a testbench" applies to every
quantitative consequence of this record exactly as it applied to gf180
DR-005's own first-order estimates (which gf180's own later evidence,
[DR-011 (temp-accuracy-mismatch-not-met)](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md)
and
[DR-018 (por-iq-recost)](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-018-por-iq-recost.md),
showed were not automatically achieved by this same topology on gf180mcu —
see `spec/porting-plan.md` §2.7–2.8).

## Alternatives considered

- **Re-run gf180-temp-por's full topology survey from scratch against
  sky130's device menu** — rejected for wave 1. gf180 DR-005's survey
  already argued each rejected alternative against physics that does not
  change between gf180mcu and sky130: BJT VBE tempco and mismatch
  structurally beat resistor-only and MOSFET-subthreshold approaches for
  absolute accuracy regardless of process node; a VDD-referenced divider is
  structurally unable to detect an absolute voltage regardless of process.
  Sky130 offers the same device classes the survey reasoned about, plus a
  *confirmed* native device where gf180mcu's was uncertain — strictly more
  favorable ground for the same conclusion, not less. Re-deriving from zero
  would re-litigate settled device-physics reasoning for no new information.
- **Adopt `sky130-bandgap`'s own recommended core (CMOS-amp Kuijk-style
  bandgap) as this block's shared reference** — rejected. That core is
  optimized for a trimmed, temperature-*flat* output reference (the
  bandgap's entire job); this block's temperature sensor needs the
  *opposite* — an intentionally temperature-*varying* PTAT output — so a
  flat-bandgap topology is the wrong shape for this consumer. The two blocks
  can and should share device-characterization data (`spec/porting-plan.md`
  §2.2) without sharing a schematic.
- **Defer topology selection to a later issue, treating it as out of scope
  for a porting plan** — rejected. Issue #1's Task section explicitly asks
  which parts of the gf180 architecture carry over vs. need re-deciding;
  leaving the single largest carryover question — the circuit topology
  itself — unresolved would not satisfy that requirement, and every other
  section of `spec/porting-plan.md` (the testbench matrix, the
  re-derivation list) is written against this topology's shape.

## Spec lines affected

This repo has no ratified `spec/target-spec.md` yet (`spec/porting-plan.md`
§4). Once created, the "architecture/topology basis" for the POR-threshold,
hysteresis, temp-accuracy, and Iq rows should cite this record (and, through
it, gf180 DR-005) rather than re-deriving the topology argument inline —
exactly as gf180's own `target-spec.md` cites its DR-001…DR-006 rather than
re-arguing them per row.

## Consequences

- Unblocks a future schematic-entry issue with a named hierarchy
  (`bias_core` shared leaf, `por_startup_assist` POR-only leaf,
  `por_comparator`/`por_output_chain`/`temp_core`/`temp_buffer` layered on
  top, `temp_*` gated by POR's output and never required to precede it) —
  the same shape gf180 DR-005 handed its own downstream schematic issue.
- Unblocks a future device-characterization issue with a named device list
  to sweep (`sky130_fd_pr__pnp_05v5_*`,
  `res_generic_po`/`res_high_po`/`res_xhigh_po`,
  `nfet_g5v0d10v5`/`pfet_g5v0d10v5`, `nfet_03v3_nvt`/`nfet_05v0_nvt`) instead
  of an unscoped survey.
- Inherits gf180 DR-005's own named risks at the topology level — the
  precision comparator's Iq headroom is tight against whatever target is
  eventually set (gf180's own <1 µA estimate needed a 3× recost, DR-018),
  and the single-point trim's reach toward any tightened accuracy target is
  the least certain quantitative claim in the source survey (confirmed
  insufficient on gf180mcu itself under mismatch, DR-011) — these are risks
  to independently re-verify on sky130, not assume resolved by inheritance.
- **Bad consequence, stated plainly**: if sky130 characterization shows a
  structurally different problem this topology handles worse than gf180mcu
  — e.g., if sky130's native-device threshold spread turns out far wider
  than gf180's assumed fallback, undermining the startup-assist leg's
  coarse-threshold trustworthiness, or if sky130's BJT/resistor mismatch is
  materially worse than gf180mcu's (which already missed its own accuracy
  target under mismatch per DR-011) — this record must be **superseded** by
  a new decision record, not patched or silently reinterpreted.
