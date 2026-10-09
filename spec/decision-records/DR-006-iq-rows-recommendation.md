# DR-006: Recommended sky130 Iq rows (TBD-4 / TBD-5 / TBD-6) from the committed iq-top evidence

- **Status**: proposed (recommendation only; ratification is the two-key
  ceremony, not this record). Awards no T1 tier, relaxes nothing, and does not
  edit `README.md`'s table.
- **Date**: 2026-10-09
- **Decided by**: Loom Builder agent, issue #136

## Context

[DR-003](DR-003-ratify-target-spec-recommendation.md) row 7 split the README
"Iq (block total)" row into `[TBD-4]` por-iq, `[TBD-5]` temp-iq and
`[TBD-6]` iq-total and carried no number. [DR-004](DR-004-por-threshold-hysteresis-ramp-recommendation.md)
did the same job for the POR rows. The Iq evidence is now on `main`: record
**20261009-191705-df85523** (`sim/iq-top/records/20261009-191705-df85523.md` and `.json`, issue #107):
the unchanged assembled `design/netlist/temp_por_top.spice`, 5 MOS corners
(tt, ss, ff, sf, fs) x {-40, 27, 125 C} x {2.97, 3.30, 3.63 V} = 45 points in
each of two directly simulated states (por-iq: RESETn forced low; iq-total:
natural released state) = **90 points, 73 `ok`, 17 non-`ok`**. temp-iq is the
derived incremental iq-total - por-iq. The record states that the TBD-4/5/6
rows "are owned by a follow-on decision record"; this is that record.

Every number below is read from record **20261009-191705-df85523** (no simulation was re-run for
this DR); numbers marked "derived" are arithmetic on that record's numbers and
are the only ones not printed in it. Per CLAUDE.md and `spec/porting-plan.md`
§2.7, no gf180-temp-por number is used or compared against.

Value-tag conventions applied (`spec/porting-plan.md` §1.1 and §3.2): each
row needs a named binding corner and a statistical-basis tag; Iq is a
budget/limit row, so the basis is **[CWC]** (worst point of the deterministic
corner grid, mismatch not modeled). A row with no stated basis, or whose grid
has a failing point inside the envelope, is not ratifiable. §2.7 adds that any
Iq figure not produced by block-level measurement is provisional.

## Decision

**Recommend: none of the three Iq rows is recommendable as a ratifiable value
yet.** The observed ok-point extremes are recorded below as *provisional,
[CWC], evidence-only* so that downstream work can cite them. No ceiling is
proposed, and no failing point is hidden under one.

### 1. Grid data (all numbers: record 20261009-191705-df85523, uA)

**por-iq** (direct; RESETn forced low by VRST; 45/45 `ok`):

| corner / T | 2.97 V | 3.30 V | 3.63 V |
|---|---|---|---|
| tt -40 C | 70.623 | 90.496 | 111.688 |
| tt 27 C | 62.509 | 79.443 | 97.643 |
| tt 125 C | 55.395 | 69.403 | 84.558 |
| ss -40 C | 64.367 | 83.158 | 103.302 |
| ss 27 C | 57.030 | 72.993 | 90.241 |
| ss 125 C | 50.836 | 64.076 | 78.484 |
| ff -40 C | 77.125 | 98.053 | 120.264 |
| ff 27 C | 68.190 | 86.065 | 105.179 |
| ff 125 C | 60.059 | 74.789 | 90.638 |
| sf -40 C | 64.592 | 83.862 | 104.518 |
| sf 27 C | 57.492 | 73.901 | 91.626 |
| sf 125 C | 51.447 | 65.056 | 79.845 |
| fs -40 C | 76.863 | 97.318 | 119.027 |
| fs 27 C | 67.702 | 85.145 | 103.806 |
| fs 125 C | 59.474 | 73.873 | 89.385 |

**iq-total** (direct, own simulation, never a sum; **X** = non-`ok`, the value
shown is the non-physical settled number the record printed, not a measurement
of Iq; 28/45 `ok`):

| corner / T | 2.97 V | 3.30 V | 3.63 V |
|---|---|---|---|
| tt -40 C | 24.427 | 29.237 | 34.515 |
| tt 27 C | 19.878 | **X** (-1547.102) | **X** (-7776.200) |
| tt 125 C | 17.111 | 19.362 | 21.813 |
| ss -40 C | 23.094 | **X** (-4666.624) | **X** (-1232.266) |
| ss 27 C | **X** (-4675.618) | **X** (22.097) | **X** (-4668.941) |
| ss 125 C | 16.424 | 18.554 | 20.875 |
| ff -40 C | **X** (-5276.614) | 30.919 | 36.504 |
| ff 27 C | **X** (-6206.566) | **X** (-7737.648) | **X** (-6198.869) |
| ff 125 C | 17.863 | 20.256 | 22.861 |
| sf -40 C | **X** (-6202.218) | 30.043 | **X** (-2703.334) |
| sf 27 C | 20.405 | 23.826 | 27.565 |
| sf 125 C | 17.491 | 19.780 | 22.267 |
| fs -40 C | 23.695 | **X** (-6124.676) | **X** (-1239.155) |
| fs 27 C | 19.344 | 22.651 | 26.277 |
| fs 125 C | 16.732 | **X** (-1760.862) | **X** (-6327.092) |

**temp-iq** (derived incremental = iq-total - por-iq; "excl." where iq-total is
non-`ok`; 28/45 `ok`):

| corner / T | 2.97 V | 3.30 V | 3.63 V |
|---|---|---|---|
| tt -40 C | -46.196 | -61.259 | -77.173 |
| tt 27 C | -42.631 | excl. | excl. |
| tt 125 C | -38.285 | -50.041 | -62.745 |
| ss -40 C | -41.273 | excl. | excl. |
| ss 27 C | excl. | excl. | excl. |
| ss 125 C | -34.412 | -45.523 | -57.610 |
| ff -40 C | excl. | -67.134 | -83.759 |
| ff 27 C | excl. | excl. | excl. |
| ff 125 C | -42.195 | -54.533 | -67.776 |
| sf -40 C | excl. | -53.819 | excl. |
| sf 27 C | -37.087 | -50.075 | -64.061 |
| sf 125 C | -33.956 | -45.276 | -57.578 |
| fs -40 C | -53.168 | excl. | excl. |
| fs 27 C | -48.358 | -62.493 | -77.529 |
| fs 125 C | -42.742 | excl. | excl. |

**temp_core attribution delta** (temp_core sub-cell current in iq-total minus in
por-iq; attribution only, from the same runs; 28/45 `ok`):

| corner / T | 2.97 V | 3.30 V | 3.63 V |
|---|---|---|---|
| tt -40 C | 2.777 | 2.825 | 2.871 |
| tt 27 C | 3.515 | excl. | excl. |
| tt 125 C | 4.614 | 4.668 | 4.722 |
| ss -40 C | 2.751 | excl. | excl. |
| ss 27 C | excl. | excl. | excl. |
| ss 125 C | 4.583 | 4.637 | 4.690 |
| ff -40 C | excl. | 2.868 | 2.922 |
| ff 27 C | excl. | excl. | excl. |
| ff 125 C | 4.662 | 4.725 | 4.790 |
| sf -40 C | excl. | 2.845 | excl. |
| sf 27 C | 3.542 | 3.592 | 3.642 |
| sf 125 C | 4.642 | 4.697 | 4.751 |
| fs -40 C | 2.740 | excl. | excl. |
| fs 27 C | 3.474 | 3.523 | 3.571 |
| fs 125 C | 4.574 | excl. | excl. |

Record summary extremes (`ok` points only, as printed in the record): por-iq
50.836 (ss, 125 C, 2.97 V) .. 120.264 (ff, -40 C, 3.63 V), median 78.484;
iq-total 16.424 (ss, 125 C, 2.97 V) .. 36.504 (ff, -40 C, 3.63 V), median
22.040; temp-iq -83.759 (ff, -40 C, 3.63 V) .. -33.956 (sf, 125 C, 2.97 V),
median -51.622. The temp_core attribution delta (per-point table of the
record, `ok` points) spans 2.740 (fs, -40 C, 2.97 V) .. 4.790 (ff, 125 C,
3.63 V); the record's summary prints the iq-total-state temp_core current as
2.740 .. 4.792 uA.

### 2. Accounting for all 90 points

- **por-iq: 45 points, all `ok`, all used** (status counts `{'ok': 45}`).
- **iq-total: 45 points; 28 `ok` and used; 17 non-`ok`, excluded from every
  statistic, reasons below.** None is excluded for being large or small; the
  record excludes only on the documented non-physical-branch signature.
- **temp-iq: 45 derived points; 28 used; 17 excluded** because their
  iq-total is non-`ok` (the por-iq half is fine). The record's temp-iq status
  counts are `{'ok': 28, 'excluded': 17}`.
- 45 + 28 + 17 = 90 points of the iq-total/por-iq grid are accounted for
  (45 por-iq + 28 ok + 17 non-ok iq-total); temp-iq adds no independent
  simulation.

**The 17 non-`ok` points** (all `non-physical-branch`, all iq-total state,
record 20261009-191705-df85523 "Excluded / flagged points"):

| # | point | signature (record) |
|---|---|---|
| 1 | tt 27 C 3.30 V | PTAT -2.024 V; total -1547.102 uA; temp_core -1566.780 uA |
| 2 | tt 27 C 3.63 V | NB 5.16 V; total -7776.200 uA |
| 3 | ss -40 C 3.30 V | NB 4.896 V; total -4666.624 uA |
| 4 | ss -40 C 3.63 V | no node out of range; total -1232.266 uA |
| 5 | ss 27 C 2.97 V | PTAT -2.024 V, NB 4.502 V; total -4675.618 uA |
| 6 | ss 27 C 3.30 V | **PTAT -2.024 V only; total +22.097 uA, temp_core +3.542 uA (positive)** |
| 7 | ss 27 C 3.63 V | PTAT -2.024 V, NB 5.162 V; total -4668.941 uA |
| 8 | ff -40 C 2.97 V | PTAT 4.478 V; total -5276.614 uA |
| 9 | ff 27 C 2.97 V | PTAT 4.645 V; total -6206.566 uA |
| 10 | ff 27 C 3.30 V | PTAT 4.975 V, NB -2.197..-1.857 V; total -7737.648 uA |
| 11 | ff 27 C 3.63 V | PTAT 5.305 V; total -6198.869 uA |
| 12 | sf -40 C 2.97 V | PTAT 4.706 V; total -6202.218 uA |
| 13 | sf -40 C 3.63 V | no node out of range; total -2703.334 uA |
| 14 | fs -40 C 3.30 V | NB 4.896 V; total -6124.676 uA |
| 15 | fs -40 C 3.63 V | no node out of range; total -1239.155 uA |
| 16 | fs 125 C 3.30 V | PTAT -1.911 V; total -1760.862 uA |
| 17 | fs 125 C 3.63 V | NB 5.042 V; total -6327.092 uA |

Location against the ratified envelope ([DR-003](DR-003-ratify-target-spec-recommendation.md)
rows 1 and 6: -40..+125 C, 2.97-3.63 V): **all 17 are inside it.** Every grid
point is at one of the three ratified temperatures and one of the three
ratified supplies (several sit on the envelope edge, which is inclusive), so no
non-`ok` point can be excluded as out-of-envelope. Distribution: by
temperature, 7 at -40 C, 8 at 27 C, 2 at 125 C (27 C loses 8 of its 15 points,
including the nominal tt/27 C/3.30 V point); by corner tt 2, ss 5, ff 4, sf 2,
fs 4. Sixteen of the 17 have a negative total and a temp_core current below
-1 nA (#4, #13 and #15 show no node outside range and are flagged by the
negative-current test alone); #6 is flagged only by the PTAT range test while
its current is positive.

**What #86 explains (verified, not assumed).** Issue #86 (open) concerns six
failing points of the *standalone* `temp_core` startup records
`sim/temp-core-startup/records/20260826-053032-ee63b45.md` (tt -40 C 3.30 V,
tt 125 C 3.30 V, ff -40 C 3.30 V) and
`sim/temp-core-startup-en-delayed/records/20260826-054047-ee63b45.md`
(tt 27 C 3.63 V, tt 125 C 3.63 V, sf -40 C 2.97 V). Matching those by point
identity against the 17 above: only **two coincide** (tt 27 C 3.63 V = #2,
sf -40 C 2.97 V = #12). The other four #86 points are `ok` in 20261009-191705-df85523
(tt -40 C 3.30 V 29.237; tt 125 C 3.30 V 19.362; ff -40 C 3.30 V 30.919;
tt 125 C 3.63 V 21.813), and the other 15 non-`ok` points are not in #86's
list. What #86 and the 17 share is the *signature* documented in
`design/temp_core.md` (negative temp_core supply current, PTAT/NB railed
outside `[-0.3 V, VDD+0.5 V]`), which `design/temp_core.md` reports moves to a
different point set when the solver tolerance changes. #86's cause is itself
undemonstrated (its open acceptance criteria), so this DR does not claim #86
*explains* any of the 17: it can only say the 17 are the same documented class
of artifact, in the assembled design, with its cause open. Whether they are
solver artifacts or real latch-up branches of `temp_core` is **not
established by any committed record**.

### 3. Per-row recommendation

**TBD-4, por-iq: not recommendable yet as a ratifiable value.** Data are
complete (45/45 `ok`), so a provisional **[CWC]** observed maximum exists:
**120.264 uA, binding corner ff / -40 C / 3.63 V** (record 20261009-191705-df85523). But the
state itself is the problem. RESETn is a DUT output that releases above
VPOR↑ (≈2.7 V, DR-004), so inside the 2.97-3.63 V envelope the por-iq state
exists only because the testbench forces RESETn low with VRST. The record
reports 46.343 / 72.622 / 112.162 uA (min/median/max, binding ff / -40 C /
3.63 V) of that current as contention between the output stage and VRST, and
"por-iq less contention" as 4.404 .. 8.102 uA (max at ff / -40 C / 3.63 V).
Ratifying either figure would encode a testbench artifact (the 120 uA) or a
number the record labels as not a proposed ceiling (the 8 uA). Missing
experiment: an agreed, spec-level definition of the por-iq state in the
envelope (e.g. what the integrator actually presents on RESETn, or a
measurement with the contention path accounted for in a way that is itself a
direct simulation), then the 45-point grid re-run in that state.

**TBD-5, temp-iq: not recommendable yet.** The incremental
iq-total - por-iq is **negative at every one of the 28 `ok` points**
(-83.759 .. -33.956 uA, record 20261009-191705-df85523) because por-iq contains the forced-reset
contention that iq-total does not. As defined it is not a sensor current and
cannot carry a [CWC] ceiling. The temp_core attribution delta (2.740 ..
4.790 uA over the 28 `ok` points; binding corner ff / 125 C / 3.63 V) is the
only sensor-own figure, but it is attribution, not an independent
verification (§1.1 requires independent verification), covers `temp_core`
only (no output buffer exists; PTAT/CTAT are unloaded in the record's "Absent
coverage"), and misses the 17 excluded points, eight of which are on the
27 C row where it is otherwise ~3.5 uA. Missing experiments: (a) the TBD-4
state definition above, so the increment has a meaningful baseline; (b)
resolution of the 17 iq-total points; (c) an Iq measurement with the
buffer/load assumption of [DR-005](DR-005-temp-buffer-scope-and-load-assumption.md).

**TBD-6, iq-total: not recommendable yet.** 17 of 45 points, including the
nominal tt / 27 C / 3.30 V point and 8 of 15 points at 27 C, are non-`ok`
inside the ratified envelope. The 28 `ok` values (16.424 ss/125 C/2.97 V ..
36.504 ff/-40 C/3.63 V; median 22.040) are a *survivor* set; the maximum of
the survivors is not the grid maximum, because the missing points include
the fast/cold-and-27 C neighbours of the survivors' maximum (e.g. ff -40 C
2.97 V, and every ff 27 C point). A ceiling taken from 36.504 would hide 17
failing points under it, which this DR does not do. Missing experiment: a
re-run of the iq-total grid (at minimum the 17 points, plus a replicate of
all 45 with a changed solver setting to see whether the failing set moves,
the check `design/temp_core.md` describes) that either lands every in-envelope
point on the physical branch, or shows a point is a real failing state of the
design (a design issue, not an Iq number). That is the demonstration #86
asks for, applied to the assembled block. Until then, any statement about
iq-total must be "28/45 points settled; 17 non-physical".

### 4. Statistical basis and limitations

- Basis for any eventual value: **[CWC]**, worst point of the corner grid
  (`spec/porting-plan.md` §3.2). No mismatch Monte Carlo and no ll/hh
  passive-skew axis were run (record "Absent coverage").
- **Attribution-sum discrepancy.** Two different things must not be conflated.
  (i) The record's sub-cell ammeter sum equals the direct -i(BVDD) to
  2.6e-16 (por-iq) and 2.0e-16 (iq-total) relative over `ok` points; the
  record itself calls this a KCL/instrumentation check, not independent
  physical evidence. (ii) The *derived temp-iq* does not equal the temp_core
  attribution delta: e.g. tt / 27 C / 2.97 V is -42.631 vs +3.515 uA, because
  por_output_chain goes 60.584 -> 14.453 uA between the states and por-iq
  carries the contention. This ~tens-of-uA mismatch between the two ways of
  reading "temp-iq" is a stated limitation, and is why TBD-5 is not
  recommendable. iq-total remains directly measured, never a sum
  (`spec/porting-plan.md` §1.1).
- iq-total at tt / 27 C / 3.30 V has **no local cross-check** (the single
  local run was stopped; record "Local cross-check"); por-iq at that point
  agrees fleet vs local at 79.443 uA. The fleet PDK commit is not reported
  by the runner.
- Constant-VDD settled current only: no ramp inrush, no brown-out. PTAT/CTAT
  unloaded. MASSIST is not separated inside the por_output_chain figure.
- §2.7 warning stands: block-level Iq numbers are provisional until the
  failing points are resolved.

### 5. What this DR does not cover

- **TBD-1 (temperature error) belongs to #105.** No accuracy claim here.
- **Post-layout parasitics** belong to #124 and the
  `spec/porting-plan.md` §3.6 re-verification; all numbers here are
  pre-layout schematic simulation.
- POR thresholds, hysteresis and supply ramp (DR-004), the sensor-output row
  (DR-005), and the `temp_core` startup root cause (#86) are not decided here.
- No netlist change is proposed, and no design-sizing change (the always-on
  MASSIST cost is a design question for a separate record).

## Alternatives considered

- **Recommend a ceiling from the 28 `ok` iq-total points (e.g. 36.504 uA
  rounded up)** — rejected: it would hide the 17 failing in-envelope points,
  including the nominal corner.
- **Declare the 17 out-of-scope as "solver artifacts"** — rejected: #86's cause
  is undemonstrated, and its list overlaps only 2 of the 17 by point.
- **Recommend por-iq = 120.264 uA (ff / -40 C / 3.63 V)** — rejected as a
  ratifiable value: dominated by a testbench-forced contention current.
- **Recommend por-iq less contention (4.404..8.102 uA) as por-iq** — rejected:
  the record flags it as a comparison figure, not a ceiling, and it is a
  difference of quantities rather than a direct simulation of a state.
- **Recommend the temp_core attribution delta as temp-iq** — rejected: it is
  attribution only and misses 17 points.
- **Carry gf180 Iq figures** — rejected (CLAUDE.md, `spec/porting-plan.md` §2.7).

## Spec lines affected

README.md "Target specification" row "Iq (block total)" (`[TBD-4]` /
`[TBD-5]` / `[TBD-6]`). This record changes none of it. If the operators
accept it, the only recommended README change is to annotate the row's
status "not ratified; evidence 28/45 iq-total points settled, see DR-006". No
ratified row (1, 6) is touched.

## Consequences

- TBD-4, TBD-5 and TBD-6 all stay open; the row cannot be ratified from the
  current evidence. Closing it needs: a spec-level por-iq state definition;
  resolution (or demonstration as real) of the 17 iq-total points, with a
  solver-sensitivity replicate; then a superseding Iq record and a DR that
  supersedes this one.
- Verification work that reports Iq must quote it as "provisional, 28/45
  settled", not as a margin against any bound.
- The finding that tt / 27 C / 3.30 V, the nominal point, does not settle in
  the assembled iq-total run strengthens the case for finishing #86 for the
  assembled design before any Iq ratification.
- The ok-point survivor statistics (16.424 .. 36.504 uA) are biased toward
  125 C (13 of 15 points ok there vs 7 of 15 at 27 C); do not read the
  survivor median as a typical value.
