# DR-008: Relocate the two ratified target-spec rows from README.md to spec/target-spec.md

- **Status**: proposed (restructure only; changes no value and no row status.
  Whether relocating already-ratified rows needs a fresh two-key ceremony is
  for the ratification lane to decide — this record does not self-ratify).
- **Date**: 2026-11-18
- **Decided by**: Loom Builder agent, issue #342 (option (a) chosen in the
  operator-session decision recorded on that issue)

## Context

`README.md` carries DR-003's two ratified rows (operating temperature, supply)
and is hash-pinned in item 10's hygiene inventory. Any `README.md` edit, including
the automated Guide docs tick, therefore stales the item-10 envelope and reds the
`signoff` gate (observed on PR #340: one Judge → Doctor → Judge round-trip, 5 h 38 m,
for a mechanical hash refresh). Dropping `README.md` from the inventory would
un-pin ratified content, and the Guide's staging of `README.md` is a vendored
Loom behavior this repo cannot patch. The root problem is ratified rows living
in an agent-rewritable prose file.

## Decision

Move the two ratified rows into `spec/target-spec.md`, byte-identical in value and
status, and hash that file in item 10 in place of `README.md`. In `README.md`,
rows 1 and 6 keep their label and point at `spec/target-spec.md` rather than
repeating the numbers. Placeholder rows stay in `README.md`.

## Alternatives considered

- **Drop `README.md` from the hygiene inventory** — un-pins ratified spec
  content; rejected on the merits.
- **Stop the Guide tick staging `README.md`, or have it re-attest** — requires a
  change to a vendored Loom file that a resync overwrites; not repo-local.
- **Move the whole table, placeholders included** — pre-empts
  `spec/porting-plan.md` §4's evidence-driven population of `target-spec.md` and
  widens the ratification surface.

## Spec lines affected

Rows 1 (operating temperature, −40…+125 °C) and 6 (supply, 2.97–3.63 V
(3.3 V ±10 %)) of the target-spec table: **location only**. Values, stretch
columns and the `ratified (DR-003)` status are unchanged. DR-001, DR-002 and
DR-003 statuses are unchanged. All other rows are untouched.

## Consequences

- README prose can change without staling item 10; the ratified rows remain
  hash-pinned, so editing a ratified value in `spec/target-spec.md` reds `signoff`.
- A reader must follow one link from the README to find the ratified numbers.
- `spec/target-spec.md` now exists, but holds only the ratified subset; the full
  table remains a future deliverable of `spec/porting-plan.md` §4.
- Item 10's envelope, the manifest citation and the rendered report are
  regenerated in the same change.
