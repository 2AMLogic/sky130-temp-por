# DR-003: Recommended values for README.md's DRAFT target-specification table

- **Status**: proposed (a Builder-drafted recommendation with an evidence
  record behind each row, per the standing ruling on issue #4/#29 — this
  record does not itself flip README.md's table out of DRAFT, ratify a T1
  tier, or edit any spec row outside this file; that is a separate
  two-key/operator step, matching the precedent DR-001 and DR-002 already
  set of staying `proposed` while the README table stays DRAFT)
- **Date**: 2026-09-15
- **Decided by**: Loom Builder agent, issue #29

## Context

`README.md`'s "Target specification" table (issue #1) is still marked
DRAFT — "engineering to ratify". `spec/porting-plan.md` §2.8 already
reconciled each of that table's rows against sky130's device menu and
gf180-temp-por's own history, sorting rows into "holds" (device-independent),
"resolved by this plan" (DR-001, supply), and rows that "need adjustment" or
must be "flagged — do not carry" pending sky130-specific evidence. Since the
porting plan was written (2026-08-20), five characterization/harness
campaigns have landed sim/ evidence on `main`:
`sim/bias-core-smoke/`, `sim/bias-core-startup/`, `sim/bias-core-op-branch/`,
`sim/temp-core-startup/` + `sim/temp-core-startup-en-delayed/`,
`sim/pnp-mismatch/`, and `sim/native-device-characterization/`. This record
reconciles the porting plan's §2.8 dispositions against that evidence and
recommends **one** set of row values/deferrals for the future
`spec/target-spec.md` (`spec/porting-plan.md` §4 item 4), per issue #29.

Per this repo's `CLAUDE.md` ("Thresholds do not port"): every threshold-class
row below is re-derived from sky130 `sim/` evidence, or marked `[TBD-#n]`
where no such evidence exists yet — none is asserted from
`gf180-temp-por`'s own ratified numbers. The only row this record recommends
a `gf180-temp-por`-influenced structural change to (the Iq row's three-way
split) carries the *accounting structure* per `spec/porting-plan.md` §1.1,
not any of gf180's numeric ceilings.

## Decision

**Recommend the following per-row dispositions** for README.md's target-spec
table (present order). No row is silently skipped, per issue #29's
acceptance criteria.

### 1. Operating temperature: −40…+125 °C

**Recommend: HOLD, ratify as drafted.** Device-independent range
(`spec/porting-plan.md` §2.8, citing gf180's own
[DR-002](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-002-temp-interface.md)/[DR-005](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-005-temp-por-architecture-survey.md)).
Corroborating (not load-bearing) evidence: every PVT-grid `sim/` campaign
committed to `main` so far —
`sim/bias-core-smoke/records/20260825-214036-a9cac4b.md`,
`sim/bias-core-startup/records/20260826-005156-f4f73a5.md`,
`sim/temp-core-startup/records/20260826-053032-ee63b45.md`,
`sim/temp-core-startup-en-delayed/records/20260826-054047-ee63b45.md`, and
`sim/native-device-characterization/records/20260909-232337-c7b9b94.md` —
independently chose this exact −40/27/125 °C axis as their corner grid's
temperature points, and every one of those decks solves (converges to a
result, pass or fail on its own merits) at both extremes. This shows the
range is at least simulatable end-to-end on this design's devices; it is not
itself a measured operating-temperature boundary claim.

### 2. Temperature error, untrimmed ±3 °C / ±1.5 °C with 1-point trim

**Recommend: `[TBD-1]`. Do not carry the README's current numbers.** Per
`spec/porting-plan.md` §1.3/§2.8: this exact target, on this exact topology,
was **measured not met** on gf180mcu itself under 3σ mismatch (±19.2…19.6 °C
and ±7.1…7.7 °C respectively, 6.5× and 4.9× over budget,
[DR-011-temp-accuracy-mismatch-not-met](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md)) —
sky130's own topology inherits no presumption either way. Available sky130
evidence is a **partial** input, not sufficient to ratify a number:
`sim/pnp-mismatch/records/20260825-220116-a9cac4b.md` measures the PNP
sensing pair's own ΔVBE mismatch at 1 σ = 0.065–0.180 mV (identical-pair
rows) / 0.067–0.138 mV (the design's real 1-vs-8-parallel array pair,
`dr1`/`dr10` rows) across −40…125 °C — but gf180's own error-attribution
breakdown found amplifier input-offset mismatch and the gain-mirror ratio
*each independently* busting the ±3 °C budget alongside PNP ΔVBE mismatch
(`spec/porting-plan.md` §2.5, citing
[DR-011-temp-accuracy-mismatch-not-met](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-011-temp-accuracy-mismatch-not-met.md)).
No sky130 characterization of resistor-tolerance mismatch or comparator/
buffer amplifier offset exists on `main` yet, and no full-signal-path
Monte Carlo (PTAT/CTAT output vs. temperature, `[3σ]` per
`spec/porting-plan.md` §3.2) has been run — so the PNP-only number above
cannot be combined into an aggregate accuracy figure without asserting the
other terms are negligible, which nothing on `main` supports. `[TBD-1]`,
owned by a future full-signal-path Monte Carlo characterization issue.

### 3. Sensor output: analog PTAT + CTAT pads / digital out via SAR pairing (stretch)

**Recommend: HOLD, ratify as drafted.** Device-independent interface scope
(`spec/porting-plan.md` §2.8, citing gf180's own
[DR-002](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-002-temp-interface.md)).
Every temp_core `sim/` campaign on `main` already measures `PTAT`/`CTAT` as
the sensor's analog pins (`sim/temp-core-startup/`,
`sim/temp-core-startup-en-delayed/`), consistent with this scope.

### 4. POR thresholds VPOR↑ / VPOR↓: re-derive against sky130 models

**Recommend: `[TBD-2]`. Keep the README's own placeholder wording,
formalize it as a deferral tag.** Confirmed correct as drafted per
`spec/porting-plan.md` §2.3/§2.8 — this cannot be carried from gf180mcu by
construction (device-threshold-dependent). No `sim/` campaign characterizing
`por_comparator`'s threshold, offset, or the resistor-divider ratio exists
on `main` yet (`design/por_comparator.sch`/`.sym` exist; no
`design/por_comparator.md` or `sim/por-comparator-*/` campaign does), so
there is no evidence yet to assign either edge a number. `[TBD-2]`, owned by
a future POR-comparator characterization issue per
`spec/porting-plan.md` §2.3's margin-arithmetic pattern (VPOR↑ must clear
[DR-001](DR-001-supply-flavor.md)'s 2.97 V worst-case-low rail with comfortable
margin — a structural constraint on the eventual number, not the number
itself).

### 5. POR hysteresis: ≥ 100 mV (floor only, no ceiling)

**Recommend: `[TBD-3]`. Needs adjustment, and the current "≥100 mV" should
not be read as a sky130-derived floor.** `spec/porting-plan.md` §2.3/§2.8
flags two problems with this row as drafted, neither resolved by evidence on
`main` yet: (a) gf180's own ratified table has a min/typ/max structure
(100/150/250 mV) with the max specifically *constructed* from VPOR↑ and a
downstream digital floor
([DR-007 amendment A2](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-007-spec-table-amendments.md)) —
an unbounded hysteresis is not a safe target to carry forward even
structurally; (b) the "100 mV" figure itself is gf180's own floor number,
presented in the README with no `[TBD]`/provenance tag as though it were
already sky130-derived, which is exactly what CLAUDE.md's "thresholds do not
port" rule flags. No `sim/` campaign measuring `por_comparator`'s hysteresis
network exists on `main`. `[TBD-3]` for both the floor and a new ceiling row,
owned by the same future POR-comparator characterization issue as row 4 —
the ceiling additionally requires an (also-`[TBD]`) `por-digital-min-vdd`
input from whatever downstream digital domain this block's `RESETn`
ultimately supervises.

### 6. Supply: confirm against sky130 flavors (1.8 V core vs 3.3/5 V devices)

**Recommend: RATIFY at [DR-001](DR-001-supply-flavor.md)'s value.** This is
the one row this repo already has a resolving decision record for: **3.3 V
nominal, ±10 % ⇒ 2.97–3.63 V**, on
`sky130_fd_pr__nfet_g5v0d10v5`/`pfet_g5v0d10v5` for the primary signal path,
`sky130_fd_pr__pnp_05v5_*` for VBE/ΔVBE sensing,
`res_generic_po`/`res_high_po`/`res_xhigh_po` for resistor references, and
`nfet_03v3_nvt`/`nfet_05v0_nvt` for the POR-only startup-assist leg
([DR-001](DR-001-supply-flavor.md), full reasoning there — not repeated
here). Every `sim/` PVT campaign on `main` already runs its supply axis at
exactly 2.97/3.30/3.63 V, consistent with this row. `DR-001` itself remains
`Status: proposed`; this record recommends its value for the table without
separately re-ratifying it.

### 7. Iq (block total): < 20 µA / < 5 µA stretch

**Recommend: split into three rows per `spec/porting-plan.md` §1.1/§2.7/§2.8
(`por-iq`, `temp-iq`, `iq-total`, each independently defined and
independently verified, not `iq-total` reconstructed by summing the other
two) — `[TBD-4]` (`por-iq`), `[TBD-5]` (`temp-iq`), `[TBD-6]` (`iq-total`).
Do not carry the README's current `<20 µA`/`<5 µA` numbers forward under any
of the three labels.** This is the row with the most significant new
evidence since the porting plan was written, and it points the same
direction the porting plan already anticipated (§2.8: "likely a mislabeled
carryover") — with a specific, already-measured lower bound that the
original numbers do not clear:

- **`sim/native-device-characterization/records/20260909-232337-c7b9b94.md`**
  (issue #27) measures `ion_n05l25` — the static drain current of
  `MASSIST` (`por_output_chain`'s always-on, gate-tied-to-VDD startup-assist
  leg, `sky130_fd_pr__nfet_05v0_nvt` at its drawn `L=25/W=1` bin) — at
  **9.44–31.94 µA** across the full 45-point PVT grid (17.75 µA at the
  nominal `tt`/27 °C/3.30 V corner; 31.94 µA at the worst corner
  `ff`/−40 °C/3.63 V). `MASSIST` is not gated by `RESETn` and has no off
  state by construction (`design/por_output_chain.md`, "Why `MASSIST`
  exists"), so this current is live in whatever state `por-iq` is quoted in.
  This single leg alone already exceeds the README draft's `<20 µA`
  "Iq (block total)" row at every corner above nominal, and exceeds its
  `<5 µA` stretch figure everywhere — a conclusion `design/por_output_chain.md`
  ("Known trade-off... The static-current cost does not clear the README's
  DRAFT `Iq (block total) < 20 µA` row") already reaches independently.
  That record's own caveat applies here too: this is "a lower bound on, and
  not a measurement of, the block's total quiescent current" — a bare device
  characterization of one leg in isolation, not a block-assembly Iq
  measurement.
- **`sim/bias-core-startup/records/20260826-005156-f4f73a5.md`** measures
  `bias_core`'s own quiescent supply current at 0.76–1.20 µA across the same
  grid — small next to `MASSIST`, but itself an always-on shared-core
  current that any `por-iq` figure must also include per
  `spec/porting-plan.md` §1.1's accounting-structure definition.
- **`sim/temp-core-startup/records/20260826-053032-ee63b45.md`** and
  **`sim/temp-core-startup-en-delayed/records/20260826-054047-ee63b45.md`**
  measure `temp_core`'s own supply current at 5.60–9.82 µA across the
  42/45-passing corners of each grid (the 3 FAILing corners in each are
  excluded per those records' own non-physical-branch guards, documented in
  `design/temp_core.md`) — a partial `temp-iq` data point (the `temp_core`
  sub-cell alone, not `temp_buffer` or a full block assembly).

None of these sub-cell numbers is itself a ratifiable per-row target —
`spec/porting-plan.md` §1.1 requires `iq-total` to be independently verified
at block-assembly level, not reconstructed by summing sub-cell figures, and
`spec/porting-plan.md` §1.3/§2.7 separately warns that gf180's own first-order
`por-iq` estimate needed a 3× recost once measured against the real
assembled circuit
([DR-018](https://github.com/2AMLogic/gf180-temp-por/blob/main/spec/decision-records/DR-018-por-iq-recost.md)).
But the `MASSIST` figure alone is a measured, cited lower bound that already
conflicts with the README's current numbers under any accounting split, so
this record recommends against ratifying `<20 µA`/`<5 µA` in their present
form under any of the three labels. `[TBD-4]`/`[TBD-5]`/`[TBD-6]`, owned by a
future block-assembly Iq characterization issue; that issue's eventual
`por-iq` ceiling should be scoped starting from a base already above
gf180's own ratified `<3.0 µA` `por-iq` figure, not assumed to match it — a
keeper that is always on by construction and already costs tens of µA on
sky130 is a sizing/topology question for that future issue and a decision
record, not something this record resolves.

### 8. Supply-ramp coverage: ramp-rate sweep in the POR testbench matrix

**Recommend: HOLD as a structural requirement, no numeric envelope.**
`spec/porting-plan.md` §2.8/§3.3–§3.4 confirms this holds structurally; no
numeric ramp-rate envelope is asserted by this record or exists in `sim/`
yet (no `sim/` campaign sweeps `dVDD/dt` yet — every PVT campaign to date
uses a fixed-duration `tran ... uic` ramp for branch-selection purposes,
per `design/temp_core.md`/`design/por_output_chain.md`, not the constant-rate
ramp-plus-quasi-staticity-guard construction `spec/porting-plan.md` §3.3
calls for). This row is not a `[TBD-#n]` numeric deferral — it is a
testbench-matrix requirement, unchanged from the README draft.

## Alternatives considered

- **Ratify a specific Iq/temperature-accuracy/hysteresis number now, using
  gf180-temp-por's ratified figures directly** — rejected. This is exactly
  what CLAUDE.md's "thresholds do not port" instruction forbids, and
  `spec/porting-plan.md` §1.3 shows gf180's own topology measured *outside*
  budget on its own PDK for the accuracy row; carrying its numbers to sky130
  would be an unsupported presumption in either direction, and the
  `MASSIST` evidence above shows sky130's own devices already push at least
  one of these rows (Iq) in a *worse* direction than gf180's figures, not a
  neutral one.
- **Wait for full block-assembly characterization before writing any DR** —
  rejected; this is the increment issue #29 asks for (a decision record with
  the evidence record behind each row, distinct from the future
  characterization issues that will produce the numbers themselves). Marking
  rows `[TBD-#n]` with the specific evidence gap named is itself useful,
  citable output — it turns "engineering to ratify" into a tracked list of
  what characterization work each remaining `[TBD]` needs, rather than
  leaving the whole table an undifferentiated DRAFT.
- **Leave the Iq row as a single "block total" line and fold the `MASSIST`
  finding into a footnote** — rejected in favor of the three-way split,
  because `spec/porting-plan.md` §1.1/§2.8 already identifies the single-row
  form as a "likely mislabeled carryover" (the README's numbers actually
  match gf180's `temp-iq` figure, not its block total) — keeping the
  single-row form would repeat that mislabeling rather than fix it.

## Spec lines affected

`README.md`'s "Target specification" table (the `## Target specification
(DRAFT — engineering to ratify, see issue #1)` section) — every row, per the
numbered dispositions above. This record does **not** edit that table (see
Status above and the DR-001/DR-002 precedent of staying `proposed` while the
table stays DRAFT) — it recommends the values a future ratification step
should write there, plus the `[TBD-#n]` tags marking rows with insufficient
evidence to ratify yet. Once `spec/target-spec.md` is created
(`spec/porting-plan.md` §4 item 4), the values/deferrals above are its
starting content for this table's rows, each retaining the citation trail
above rather than being asserted bare.

## Consequences

- Gives the future ratification step (the two-key mechanism named in issue
  #29, not this record) a single recommendation to evaluate instead of
  eight independently-argued rows scattered across `porting-plan.md` §2.8
  and three design docs.
- Surfaces, with a citable number, that this port's `MASSIST` addition
  (`design/por_output_chain.md`, new relative to gf180's own schematic) may
  need its own sizing/topology decision record before an `Iq (block total)`
  row can be ratified at anything close to the README's current draft
  figures — a finding this record reports and scopes, but does not resolve.
- Six rows remain `[TBD-#n]` pending future characterization issues
  (temperature accuracy, POR thresholds, POR hysteresis floor and ceiling,
  and the `por-iq`/`temp-iq`/`iq-total` split) — this record does not reduce
  the amount of characterization work remaining; it inventories it precisely
  against what evidence already exists on `main` vs. what is still missing.
- If a future block-assembly Iq measurement contradicts the `MASSIST`
  device-level lower bound above (e.g., because a resizing decision record
  changes `MASSIST`'s geometry before that measurement is taken), this
  record's Iq section is superseded by whichever record reports that
  measurement, not silently reinterpreted.
- Sets no T1 tier and awards none — that determination is explicitly out of
  scope for this record and for issue #29, per both the issue's text and
  this repo's Loom builder role instructions.
