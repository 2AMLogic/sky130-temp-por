# DR-005: `temp_buffer` scope, PTAT/CTAT output load assumption, and the Sensor-output row

- **Status**: proposed (recommendation only; ratification is the two-key
  ceremony, not this record). Awards no T1 tier, relaxes nothing, and does not
  edit `README.md`'s table or any ratified row.
- **Date**: 2026-10-09
- **Decided by**: Loom Builder agent, issue #125

## Context

Three places in this repo leave the temperature output's drive and load
undecided:

- [DR-002](DR-002-architecture-carryover.md) (hierarchy, ~lines 129-130) lists
  `temp_buffer` as a layer on top of `temp_core`.
- `design/temp_core.md` (Interface table, `PTAT` row) and the header of
  `design/temp_core.sch` say the cell has no output buffer, that `temp_buffer`
  is "a separate, not-yet-ported cell", and that "a consuming testbench must
  specify a high-impedance load" without saying how high.
- README.md "Sensor output" row is `[TBD]` (draft: analog PTAT + CTAT pads;
  stretch: digital out via SAR pairing). DR-003 left it unratified.

No schematic, `design/` doc or issue exists for `temp_buffer`. Issue #105
(temp_core accuracy Monte Carlo) assumes a high-impedance load, which is only
meaningful once "high" has a number.

**Input from gf180 (public repo `2AMLogic/gf180-temp-por`, not carried
numerically).** There, `spec/decision-records/DR-005-temp-por-architecture-survey.md`
placed `temp_buffer` in the hierarchy; `design/temp_core.md` ("Output loading
-- stated, not hidden") then recorded that `temp_buffer` was *not* in the
ratified wave-1 `temp_por_top` hierarchy, that `temp_core` has no buffer, and
that the consequence was handled as a **pad-load specification** (a
minimum `Rload`, bounded by a very-high-impedance measurement load) rather
than as a buffer cell: any consumer unable to meet it "needs the `temp_buffer`
cell". That is, gf180 shipped wave 1 unbuffered with an explicit load
requirement, and treated the buffer as the remedy for a consumer that cannot
meet it. The method is the input; none of its resistances, percentages or
degree figures is used below. Per CLAUDE.md, sky130 is re-derived.

## Re-derivation for sky130 (first-order, no simulation)

Both outputs have a resistive source impedance by construction
(`design/temp_core.sch`):

- `PTAT` is the top of `R2 + R2TRIM` to `VSS`, carrying the PTAT branch
  current. Its source impedance is that series resistance. Drawn geometry is
  `res_xhigh_po` W=2, L=2652.6 (`R2`) and L=450.88 (`R2TRIM`): about 1326 +
  225 = ~1550 squares. At a nominal `res_xhigh_po` sheet resistance of order
  2 kohm/sq (a PDK-level figure not yet verified in this repo), that is of
  order **3 Mohm**, with process spread on top. This is a design-point
  estimate only; the sim record in "Consequences" replaces it.
- `CTAT` is `VEB` of `XQ1` through `XRISO`, a small resistor (`design/`).

A DC load `Rload` from `PTAT` to `VSS` appears in parallel with the
`R2 + R2TRIM` leg, so the PTAT gain (a ratio) is scaled by
`Rload / (Rload + Rs)`, with `Rs` the PTAT source resistance above. Because
PTAT is proportional to absolute temperature, a fractional gain error `e`
reads as roughly `e x T(K)` of temperature error, before any trim. For
`Rs` of order 3 Mohm this gives (order of magnitude only):

| `Rload` | gain error | approx. temperature error at 300 K |
|---|---|---|
| 10 Mohm | tens of percent | tens of K -- unusable |
| 100 Mohm | a few percent | ~10 K |
| 1 Gohm | ~0.3 % | ~1 K |
| 1 Tohm | ~3e-6 | negligible (<0.01 K) |

A *purely resistive* load error is a gain error, so a 1-point trim absorbs
the nominal part; the untrimmed row (`[TBD-1]`) does not. This is why the load
must be fixed once, not left to each testbench. The same drawn geometry
means the sky130 source impedance is not the gf180 one even though ratios
carry (sheet resistance differs by flavor), which is exactly why no gf180
figure is reused.

Supply/devices also matter for a buffer: the block runs on the 5 V-class
`g5v0d10v5` devices at 2.97-3.63 V (DR-001). A unity-gain buffer for a PTAT
node near a diode-drop-scale level at the cold, low-rail corner needs input
common-mode and output swing headroom against that supply, and adds its own
offset (a new term in #105's budget), bias current (against the `[TBD-5]`
temp-iq budget, shared with the POR bias core) and an enable/IBIAS contract
(DR-010-style high-Z when disabled). None of that is characterized; sky130 has
no amplifier-offset evidence yet.

## Decision

**Recommend, as three parts:**

**(a) `temp_buffer` is out of scope for the sky130 wave-1 port; PTAT and CTAT
are delivered unbuffered.** `temp_buffer` stays a named, deferred layer in the
DR-002 hierarchy (not deleted), to be reopened by a new issue and record if
the evidence below says an unbuffered pad cannot meet the load a real consumer
presents. Reopen triggers: (i) the ratified accuracy row cannot be met at the
fixed pad load of (b); (ii) a consumer (e.g. the digital-out stretch via SAR
pairing) cannot present `Rload` of (b); (iii) the sky130 `Rs` measured below
is large enough that (b) is unachievable at any realistic pad.

**(b) Load assumption every `temp_core` testbench must use** (including #105
and any future accuracy claim):

1. **Reference load for pass/fail and accuracy claims**: `Rload = 1 Tohm`
   from `PTAT` to `VSS` and from `CTAT` to `VSS` (a measurement load that
   makes the loading error negligible, so a claim is about the core, not the
   load), `Cload = 0` unless the testbench is explicitly a capacitive one.
2. **Pad-load requirement stated for consumers**: `Rload >= 1 Gohm` on
   `PTAT`, recorded as a requirement on the consumer, with the cost at that
   value reported (not assumed) from the sky130 run. The 1 Gohm figure is a
   *starting point re-derived from the table above*, to be confirmed or moved
   by the evidence, not a ratified number.
3. **Informational loading sweep (not pass/fail)**: every `temp_core`
   accuracy campaign should include, at one nominal corner, the gain error
   at `Rload` of 1 Gohm and 100 Mohm and a small `Cload` on each pad,
   labelled "cost of having no buffer", so the cost is a measured number. It
   is single-unit work (a single-corner `klt sim`, or part of the campaign's
   own fleet request); it is not a reason to run extra grids.
4. Any record that does not state its `Rload`/`Cload` is not usable as
   accuracy evidence.

**(c) Effect on the Sensor-output row and on #105.**

- README "Sensor output" row (`[TBD]`): recommend it be restated at
  ratification as "analog PTAT + CTAT pads, **unbuffered**, pad load
  `Rload >= [value set by evidence]`" in the Target column; the Stretch column
  (digital out via SAR pairing) is unchanged and remains out of wave 1. This
  record **does not edit the row**; the edit belongs to the ratification
  ceremony.
- #105: its "high-impedance load" becomes concretely the reference load of
  (b)1 (`1 Tohm`, `Cload = 0`), declared in `experiment.json`, plus the
  informational sweep of (b)3. #105 adds no buffer-offset term; the budget is
  explicitly for the unbuffered core, and states that a future `temp_buffer`
  would add one.

## Alternatives considered

- **Port `temp_buffer` in wave 1 (buffered pads).** Not chosen: no schematic,
  testbench or offset/Iq evidence exists; it adds an uncharacterized
  amplifier-offset term to an accuracy row that is still `[TBD-1]` and where
  the same topology on gf180 did not meet its target under 3-sigma mismatch
  (`spec/porting-plan.md` §1.3), consumes `[TBD-5]` Iq headroom, and expands
  scope beyond the narrow, evidence-first port. Cost of being wrong later is
  low (the layer is kept in the hierarchy). Not rejected on merit: it is the
  remedy if a reopen trigger fires.
- **Unbuffered, but leave the load to each testbench ("high impedance").**
  Not chosen: this is the current state, and it makes campaigns
  non-comparable and #105's result unfalsifiable. "High" must be a number.
- **Unbuffered with a stricter reference load (e.g. 10 Gohm) or a finite
  nominal one (e.g. 1 Gohm) as the pass/fail load.** Not chosen: a finite
  reference load puts a load-dependent (and process-dependent via `Rs`) term
  into every accuracy claim; 1 Tohm isolates the core, and the finite loads are
  reported as informational cost instead.
- **Delete `temp_buffer` from the DR-002 hierarchy.** Not chosen: DR-002
  is `proposed`, and this decision is explicitly reversible; deferral records
  the reopen triggers instead of erasing the option.
- **Carry gf180's pad-load number.** Not chosen: CLAUDE.md "thresholds do not
  port"; `Rs` here comes from sky130 `res_xhigh_po`.

## Spec lines affected

- README.md target-spec row "Sensor output" (currently `[TBD]`,
  "draft: analog PTAT + CTAT pads"): recommended wording in (c). **Not
  edited here.**
- `design/temp_core.md` `PTAT` interface row and the matching `.sch` header
  text say "high-impedance load" without a value: recommend a follow-up to
  point at this record once ratified. Not edited here.
- DR-002 hierarchy (`temp_buffer` layer): unchanged; its status
  becomes "deferred, reopen triggers in DR-005" if this record is ratified.
- No ratified row (operating temperature, supply) is touched.

## Consequences

- #105 can set up its load unambiguously; its result will say, in its own
  record, what load it assumed.
- The unbuffered choice makes the accuracy row a statement about the pad
  load as well as the core; any consumer with a lower input impedance than
  the ratified pad requirement fails the row, and the fix is a new block
  (`temp_buffer`) -- later, more expensive work and a re-run of accuracy
  evidence.
- The sky130 `PTAT` source resistance (`Rs`) is currently a drawn-geometry
  estimate; a single-corner `klt sim` of `temp_core` at the declared loads
  (or the #105 campaign's own records) should replace it. That sim is
  the evidence this record lacks; none is run here and none is cited.
- Bad consequences: the 1 Gohm pad requirement is demanding for some ADC
  front ends and for probe/pad leakage at 125 C; the digital-out stretch
  will need either a high-Z ADC input or a `temp_buffer`, so this decision
  may be reversed when that stretch is promoted.
