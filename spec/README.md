# spec

- [`porting-plan.md`](porting-plan.md) — what carries over from
  [`gf180-temp-por`](https://github.com/2AMLogic/gf180-temp-por)'s
  architecture and spec structure, what must be re-derived against sky130
  device models, and the PVT/ramp-rate testbench matrix the POR and sensor
  testbenches must cover before design starts. The first deliverable this
  repo produces — see the repo README and `CLAUDE.md`.
- [`decision-records/`](decision-records/) — one file per decision, using
  the format in `decision-records/TEMPLATE.md` (the blank template, not a
  decision itself). The table below is the index of every `DR-*.md` file;
  the status is copied from each file's own `Status` line, and the last
  column names the README target-specification row(s) the record addresses.
  `DR-004` through `DR-008` are all `proposed` recommendations awaiting the
  two-key ceremony (see [`ratification/`](../ratification/)) — none of them
  is ratified.

  | Decision | Subject | Status | README target row(s) addressed |
  |---|---|---|---|
  | [`DR-001`](decision-records/DR-001-supply-flavor.md) | Supply/device flavor — sky130 3.3 V I/O-class devices (`g5v0d10v5` at 3.3 V), not 1.8 V core | `proposed` (input to a future spec-ratification issue; creates/ratifies no `target-spec.md`) | Supply (row 6) — its value is what `DR-003` ratified |
  | [`DR-002`](decision-records/DR-002-architecture-carryover.md) | Adopt `gf180-temp-por`'s shared-core / two-tier POR architecture as sky130's starting topology | `proposed` (input to a future schematic-entry issue; adopts a topology, does not verify it) | none (architecture, not a spec row) |
  | [`DR-003`](decision-records/DR-003-ratify-target-spec-recommendation.md) | Recommended values for README.md's DRAFT target-specification table | `ratified` (two-key path, issue #78) — **scoped**: only row 1 (operating temperature, −40…+125 °C) and row 6 (supply, 2.97–3.63 V per `DR-001`) are final; all other rows stay `[TBD]` | rows 1 and 6 final; all other rows deferred |
  | [`DR-004`](decision-records/DR-004-por-threshold-hysteresis-ramp-recommendation.md) | Recommended sky130 VPOR↑/VPOR↓, hysteresis and supply-ramp rows (from committed #98/#102 evidence) | `proposed` (recommendation only; ratification is the two-key ceremony) | POR thresholds `[TBD-2]`, POR hysteresis `[TBD-3]`, Supply-ramp coverage |
  | [`DR-005`](decision-records/DR-005-temp-buffer-scope-and-load-assumption.md) | `temp_buffer` scope, PTAT/CTAT output load assumption, and the Sensor-output row | `proposed` (recommendation only; ratification is the two-key ceremony) | Sensor output (`[TBD]`); discusses `[TBD-1]`/`[TBD-5]` as constraints without recommending them |
  | [`DR-006`](decision-records/DR-006-iq-rows-recommendation.md) | Recommended sky130 Iq rows (`[TBD-4..6]`) from the committed `sim/iq-top` evidence | `proposed` (recommendation only; ratification is the two-key ceremony) | Iq (block total): `[TBD-4]` por-iq, `[TBD-5]` temp-iq, `[TBD-6]` iq-total — finds them not yet recommendable (17 of 45 iq-total points non-`ok`) and names the missing experiments |
  | [`DR-007`](decision-records/DR-007-temp-core-accuracy-recommendation.md) | `temp_core` accuracy (`[TBD-1]`): the 3-sigma mismatch figure is real; recommended design change and a provisional budget | `proposed` (recommendation only; ratification is the two-key ceremony) | Temperature error, untrimmed `[TBD-1]` (both the untrimmed and 1-point-trim columns) |
  | [`DR-008`](decision-records/DR-008-relocate-ratified-target-spec-rows.md) | Relocate the two ratified target-spec rows (1 and 6) from README.md to `spec/target-spec.md` so README prose edits stop staling item 10 | `proposed` (restructure only; changes no value or row status; does not self-ratify) | rows 1 and 6 — location only |
- [`ratification/`](../ratification/) — the two-key ratification process
  (`market-key`, `ee-key`) `DR-003`'s recommendation and any future
  `target-spec.md` ratification goes through.

[`target-spec.md`](target-spec.md) holds only the two rows DR-003 ratified (operating
temperature and supply), relocated from the README by `DR-008`. The full table is
still a future deliverable per the porting plan §4, populated from
device-characterization evidence rather than asserted ahead of it; the
placeholder rows stay in the repo README until then.
