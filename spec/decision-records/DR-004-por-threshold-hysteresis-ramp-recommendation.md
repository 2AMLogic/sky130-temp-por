# DR-004: Recommended sky130 VPOR↑/VPOR↓, hysteresis and supply-ramp rows (from committed #98/#102 evidence)

- **Status**: proposed (recommendation only; ratification is the two-key
  ceremony, not this record). Awards no T1 tier, relaxes nothing, and does not
  edit `README.md`'s table.
- **Date**: 2026-10-09
- **Decided by**: Loom Builder agent, issue #123

## Context

[DR-003](DR-003-ratify-target-spec-recommendation.md) deferred three rows
because no sky130 evidence existed: `[TBD-2]` (VPOR↑ / VPOR↓), `[TBD-3]`
(hysteresis floor and ceiling) and the supply-ramp row (README.md rows
"POR thresholds", "POR hysteresis", "Supply-ramp coverage"). Evidence now on
`main`:

- **#102**, `sim/por-comparator-thresholds/` (README.md plus records below):
  `por_comparator` edges from a constant-rate VDD sweep (100 V/s, with a
  50 V/s half-rate guard at 10 mV tolerance), 5 MOS corners
  (tt, ss, ff, sf, fs) x {-40, 27, 125 C} = 15 points per variant, 15/15
  clean and rate-consistent. Records:
  `20261009-054322-10d3e9f-ideal-bias` (ideal 1 uA IBIAS / 1.25 V VREF),
  `20261009-054331-79eebd4-real-bias-core` (real `bias_core`),
  `20261009-062844-09eb234-ideal-bias-passive-skew` and
  `20261009-062845-bf30f6c-real-bias-core-passive-skew` (ll/hh resistor skew,
  tt MOS, 6 points each).
- **#98 / #101**, `sim/supply-ramp-top/` records `20261009-024606-285dd08`
  (as-drawn), `20261009-024607-285dd08` (`diag-mn1-l20` diagnostic),
  `20261009-055755-5346c37` (as-drawn re-run) plus its
  `-local-probe` companion, and `20261009-180056-987e04f-fleet-refusal`.

Per CLAUDE.md "thresholds do not port": every number below is from a cited
sky130 record. No gf180-temp-por number is used. (DR-003 mentions gf180's
100 mV floor only as a flagged non-sky130 figure; it is not used here.)

## Decision

**Recommend the following.** "Corner" is the binding PVT corner of the cited
extremum. The statistical basis of every number is **PVT-corner extremes only,
no mismatch Monte Carlo** (the #102 README says so explicitly).

### Row 2 (README "POR thresholds VPOR↑ / VPOR↓", `[TBD-2]`): split

**2a. Recommend recording a provisional corner envelope** (real-bias-core is
the binding variant, because it is the block that ships; ideal-bias is
corroborating):

| quantity | min (corner) | max (corner) | record |
|---|---|---|---|
| VPOR↑, real-bias-core | 2.6908 V (sf, -40 C) | 2.7130 V (ss, 27 C) | 20261009-054331-79eebd4-real-bias-core |
| VPOR↓, real-bias-core | 2.5353 V (sf, -40 C) | 2.5567 V (ss, 27 C) | 20261009-054331-79eebd4-real-bias-core |
| VPOR↑, ideal-bias | 2.6832 V (ff, 125 C) | 2.7010 V (ss, -40 C) | 20261009-054322-10d3e9f-ideal-bias |
| VPOR↓, ideal-bias | 2.5430 V (fs, 125 C) | 2.5510 V (ss, -40 C) | 20261009-054322-10d3e9f-ideal-bias |
| VPOR↑, real-bias, ll/hh | 2.6950 V (ll, -40 C) | 2.7110 V (hh, 27 C) | 20261009-062845-bf30f6c-real-bias-core-passive-skew |
| VPOR↓, real-bias, ll/hh | 2.5412 V (ll, -40 C) | 2.5557 V (ll, 125 C) | 20261009-062845-bf30f6c-real-bias-core-passive-skew |

The ll/hh envelope lies inside the main-grid real-bias envelope, so the
real-bias main grid is the binding set. One-sided structural check against
[DR-001](DR-001-supply-flavor.md)'s 2.97 V low rail: margin
`2.97 V - max(VPOR↑)` = **+257 mV** (real-bias, ss, 27 C, record
`...054331-79eebd4-real-bias-core`); +259 mV in the ll/hh set. Also +917 mV
below the 3.63 V rail's top end.

**2b. Numeric ratifiable bounds stay `[TBD-2]`.** Recommend that no bound
tighter than "VPOR↑,max < 2.97 V by a Monte Carlo-backed margin" be
ratified yet. Missing evidence, specifically:

1. Mismatch Monte Carlo of `por_comparator` (comparator offset and divider
   ratio; the #102 README calls these "the likely dominant spread for a
   ratio-set threshold"). A bound without it would be a corner bound dressed as
   a statistical one.
2. Variant disagreement: real `bias_core` moves VPOR↑ by -6…+20 mV and VPOR↓
   by -13…+12 mV against ideal-bias and reverses the temperature trend
   (#102 README "Reading of the numbers"). The two variants differ in their
   binding corners, so the real-bias number depends on the unresolved `bias_core`
   startup/VREF behavior (issue #86).
3. Combined MOS x resistor-skew corners (e.g. ss MOS with hh resistors) are not
   run; ll/hh were run only with tt MOS.
4. Post-layout parasitics (no layout exists), and sweep rates other than
   100/50 V/s.
5. The as-drawn assembled-block threshold/behavior (see row 8): #102 measured
   `por_comparator` in isolation, not inside `temp_por_top`.

### Row 3 (README "POR hysteresis", `[TBD-3]`): floor candidate, ceiling TBD

**3a. Corner envelope** (hysteresis = VPOR↑ - VPOR↓ at the same corner):

| variant | min (corner) | max (corner) | record |
|---|---|---|---|
| real-bias-core | 145.9 mV (sf, 125 C) | 156.3 mV (ss, 27 C) | 20261009-054331-79eebd4-real-bias-core |
| ideal-bias | 139.7 mV (sf, 125 C) | 150.1 mV (ss, -40 C) | 20261009-054322-10d3e9f-ideal-bias |
| real-bias, ll/hh | 147.8 mV (ll, 125 C) | 158.1 mV (hh, 27 C) | 20261009-062845-bf30f6c-real-bias-core-passive-skew |
| ideal-bias, ll/hh | 141.8 mV (ll, 125 C) | 150.3 mV (hh, -40 C) | 20261009-062844-09eb234-ideal-bias-passive-skew |

The lowest value anywhere is **139.7 mV** (ideal-bias, sf, 125 C); the lowest
for the shipped variant is **145.9 mV** (real-bias, sf, 125 C). Recommend the
operators treat these as the sky130-derived basis for any floor. This record
does **not** recommend carrying the README's former "≥100 mV" as a sky130
number: it is a gf180 figure (DR-003 row 5). Whatever floor is ratified
must be chosen against the corner-minimum above and the Monte Carlo result
below, not against 100 mV. Numeric floor stays `[TBD-3]` pending the same
Monte Carlo (item 1 in row 2b); the corner minimum is a ceiling on how high
a floor could be set, not a margin-bearing floor.

**3b. Ceiling stays `[TBD-3]`.** Missing evidence: `por-digital-min-vdd`
(the downstream digital domain's minimum operating voltage, integrator-supplied,
`spec/porting-plan.md` §2.3), which the ceiling is constructed from together
with VPOR↓,min. The reference value that ceiling would be checked against is
VPOR↓,min = 2.5353 V (real-bias, sf, -40 C, record `...054331-79eebd4-real-bias-core`).
No committed record supplies `por-digital-min-vdd`.

### Row 8 (README "Supply-ramp coverage"): HOLD structural, numeric envelope `[TBD]`

Recommend: keep the row as a structural requirement (constant-rate ramp sweep
with half-rate quasi-staticity guard, per porting-plan §3.3) and ratify **no
numeric ramp-rate envelope**. The committed #98 / #101 records contain no
usable result for the as-drawn block:

- `20261009-024606-285dd08` (as-drawn, 360 points): all 360 ERROR,
  `model_not_found` (por_output_chain `XMN1` L=25 had no valid bin; #101).
- `20261009-055755-5346c37` (as-drawn after the #101 fix) and
  `20261009-180056-987e04f-fleet-refusal`: 360 points declared, **none run**;
  every fleet submission was refused. The only as-drawn simulation is one local
  probe (tt, 27 C, 3.30 V, 10 kV/s; no model error; no transition claim).
- `20261009-024607-285dd08` is the `diag-mn1-l20` variant (XMN1 at L=20),
  explicitly not the design. It is **not** used for any number here. For
  context only: 358/360 points show one release and no re-assert, but 151/360
  points FAIL physicality (temp_core self-biased nodes below -0.3 V, issue
  #86), the two transition FAILs sit at 500 kV/s and were flagged for re-run at
  finer resolution, and its own text says no bound is ratified.

Missing evidence, specifically: the as-drawn `temp_por_top` rate x PVT grid
(`run_ramp_campaign.py run --variant as-drawn`, then `record`) completing on
the fleet; resolution of the #86 temp_core startup artifacts so physicality
does not mask the transition verdict; the ll/hh passive-skew axis crossed with
rate; brown-out/dip behavior (porting-plan §3.4); rates outside 500 V/s to
1 MV/s.

## Alternatives considered

- **Recommend a numeric VPOR↑/VPOR↓ window now (e.g. the corner envelope
  rounded outward)** — not chosen as a ratifiable bound: corner-only, no
  mismatch, and ideal vs real bias disagree. Recorded as the provisional 2a
  envelope instead.
- **Use the diag-mn1-l20 ramp record as ramp evidence** — rejected: it is a
  different circuit and mostly fails on physicality.
- **Carry gf180 thresholds or its 100/150/250 mV hysteresis structure
  numerically** — rejected (CLAUDE.md).
- **Say nothing until Monte Carlo and the ramp grid exist** — rejected: the
  corner envelope, the +257 mV margin and the exact missing-evidence list are
  already citable and unblock grading design work.

## Spec lines affected

README.md "Target specification" rows "POR thresholds VPOR↑ / VPOR↓"
(`[TBD-2]`), "POR hysteresis" (`[TBD-3]`) and "Supply-ramp coverage" (`[TBD]`).
This record changes none of them; if the operators ratify it, the
recommended edit is limited to annotating rows 2/3 with the 2a/3a corner
envelopes marked "provisional, corner-only", leaving the numeric bounds and
the ceiling `[TBD]`. Rows 1 and 6 (final per DR-003) are untouched.

## Consequences

- Verification issues (#105, #106, #116, #117) get a cited corner envelope to
  compare against, but still no ratified bound; they must report against the
  envelope as "provisional".
- The +257 mV margin is a corner number only; it must not be quoted as the
  design margin until Monte Carlo exists.
- Hysteresis on sky130 measured ~140-158 mV across all variants; any ratified
  floor in that range or below leaves little or large room depending on
  the Monte Carlo spread, which is unknown.
- Three evidence gaps are named as follow-on work: `por_comparator` mismatch
  Monte Carlo; `por-digital-min-vdd` plus a ceiling; the as-drawn
  `temp_por_top` ramp grid (blocked by fleet capacity and #86).
- If the as-drawn ramp grid later contradicts the #102 isolated-comparator
  edges, a new record supersedes this one; it is not silently reinterpreted.
