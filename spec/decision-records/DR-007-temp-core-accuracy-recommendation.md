# DR-007: temp_core accuracy (TBD-1): the 3-sigma mismatch figure is real; recommended design change and a provisional budget

- **Status**: proposed (recommendation only; ratification is the two-key
  ceremony, not this record). Edits no `spec/` row, does not touch `README.md`'s
  table, and relaxes nothing.
- **Date**: 2026-10-17
- **Decided by**: Loom Builder agent, issue #187

## Context

[DR-003](DR-003-ratify-target-spec-recommendation.md) row 2 left the temperature
error row as `[TBD-1]` and [DR-006](DR-006-iq-rows-recommendation.md) deferred it to
#105. The #105 campaign has reported it: record
`sim/temp-core-accuracy-mc/records/20261011-165907-69d13ac.md` (local mismatch,
N = 30 per corner per term, 15 process/supply corners, seed 20261010), PTAT-referred, 3 sigma:

| | worst corner | tt / 3.30 V |
|---|---|---|
| untrimmed | 77.38 degC (`sf_2.97V`, 125 C) | 73.66 degC |
| 1-point 27 C trim | 22.76 degC | 21.95 degC |

DR-003's draft values were +/-3 C untrimmed and +/-1.5 C trimmed, about 25x and 15x below the measurement.
**The figure is confirmed.** `sim/temp-core-accuracy-mc/hand-calc-20261017.md` reproduces the dominant terms
from the PDK's own Pelgrom constants and the netlist device sizes: hand/MC = 0.77 to 1.03 for the mirror and
the amplifier at tt/3.30 V and at the worst corner, 0.77 to 0.81 for the total. No measurement or
normalisation error was found, and no re-run was needed.

Where the error comes from (record, worst corner, untrimmed 3 sigma): branch-current mirror **67.29 C**, amplifier
offset **41.39 C**, resistor ratio 4.60 C, PNP pair 2.90 C, everything else 0.26 C. The hand calculation
shows why, and what has to change:

- **Amplifier**: `dPTAT/Vos = (R2+R2TRIM)/R1 = 26`, and `S = 4.71 mV/C`, so **1 mV of input offset is 5.5 degC**.
  `sigma(Vos)` = 1.86 mV hand (2.33 mV MC) from the pfet input pair (12 mV.um / sqrt(L W), L4 W32) and the nfet
  mirror load (8.2 mV.um / sqrt(L W), L8 W8, referred through gmL/gmI = 0.76). Static area is a poor lever: 4x the
  input-pair and load area only halves `sigma(Vos)` (see Alternative A) and leaves the amplifier at ~20 C.
- **Mirror**: the three legs MP1..3 (pfet L4 W8) run at I = 0.44 to 0.59 uA, gm/Id = 11 to 14 /V (moderate
  inversion). A per-leg Vth mismatch of 2.1 mV is a 2.3 to 3.0 % current error; 1 % of PTAT is 3.0 degC, and the
  loop gives `sigma(dI3/I3) = 1.84 sigma_delta`. The lever is gm/Id, not only area: current error is
  `gm/Id x dVth`.

## Decision

Recommend the following design change and a provisional `[TBD-1]`; ratifying either needs its own two-key step.

1. **Chop (or auto-zero) the `temp_core` amplifier** so that the residual input offset is <= 0.05 mV (design
   target, an assumption this DR does not verify). A static offset fix is not enough (Alternative A).
2. **Source-degenerate the three mirror legs MP1/MP2/MP3** with an `res_xhigh_po` resistor per leg dropping
   about 0.3 V at 27 C (about 680 kOhm, i.e. ~0.4 V at 125 C), and **quadruple their area** (L4 W8 -> L4 W32).
   Per-leg `sigma(Vth)` falls 12/sqrt(128) = 1.06 mV (from 2.12) and effective gm/Id falls from 14.4 to about 2.7 /V
   (to ~2.0 /V at 125 C), so `sigma(dI/I)` falls from 3.0 % to 0.29 % per leg; the degeneration resistors add
   about 0.10 % of their own (4.64e-2/sqrt(W L)), so the mirror term is projected at **0.10 x** the record value.
3. **Provisional `[TBD-1]`** (untrimmed / 1-point 27 C trim, 3 sigma, local mismatch, worst PVT corner):
   **+/-12 degC / +/-4.5 degC.** The central projection below is 8.7 / 3.1 degC; the 12 / 4.5 values add the
   N = 30 chi-square 95 % upper factor of 1.34 (record "Statistical resolution"). The value is **provisional**:
   it must be re-confirmed by a post-change run of the #105 campaign (a new run with its own record id,
   N >= 100 per corner) before any ratification. If that run misses, the number moves; the
   spec is not bent to the design.

### Per-term budget (PTAT-referred 3 sigma, degC; worst of -40/27/125 C)

Baseline is the record. "Projected" scales each term's record value: mirror x 0.10 (above); amplifier by
0.05 mV / 2.33 mV (residual offset over the MC `sigma(Vos)` at tt/3.30 V = 0.0215); other terms unchanged. Terms are independent draws and are
combined by RSS; the worst-corner column RSSes each term's own worst corner, which is slightly conservative
(the record's own RSS of its term rows is 79.19 vs the `all` row's 77.38).

| term | baseline untrim, worst corner | projected untrim, worst corner | baseline untrim, tt/3.30 | projected untrim, tt/3.30 | baseline trim, worst | projected trim, worst | baseline trim, tt/3.30 | projected trim, tt/3.30 |
|---|---|---|---|---|---|---|---|---|
| mirror (MP1..3, MPC1..3) | 67.29 | **6.73** | 67.29 | 6.73 | 18.84 | 1.88 | 18.84 | 1.88 |
| amplifier (MI1/2, ML1/2) | 41.39 | **0.89** | 39.80 | 0.85 | 14.57 | 0.31 | 13.67 | 0.29 |
| resistor ratio | 4.60 | 4.60 | 3.34 | 3.34 | 0.01 | 0.01 | 0.01 | 0.01 |
| PNP pair | 2.90 | 2.90 | 2.21 | 2.21 | 2.48 | 2.48 | 1.74 | 1.74 |
| other (bias, 2nd stage, startup) | 0.26 | 0.26 | 0.22 | 0.22 | 0.15 | 0.15 | 0.04 | 0.04 |
| **RSS** | 79.19 | **8.70** | 78.28 | **7.88** | 23.95 | **3.13** | 23.34 | **2.58** |
| record `all` row | 77.38 | | 73.66 | | 22.76 | | 21.95 | |

The residual is then dominated by the resistor ratio (untrimmed) and the PNP pair and mirror (trimmed). None
of the three is addressed by this DR; the PNP term is the floor of the trimmed row at this PNP area.

## Alternatives considered

- **Relax `[TBD-1]` to fit the current design (e.g. +/-80 C)** — rejected. CLAUDE.md forbids relaxing the spec to
  make results pass, and DR-003 ties no ratified number to this design.
- **A. Static upsizing only, no chopping** (input pair 4x area: W32 -> W128; load 4x: W8 -> W32; mirror
  degeneration and 4x area as above) — halves `sigma(Vos)` to about 0.93 mV, leaving the amplifier at about 20.7 C and the
  RSS at about **22 C untrimmed worst corner (7.9 C trimmed)**: still above any plausible row. A 10 to 100 x offset
  reduction cannot come from area at an acceptable die cost. Kept as the fallback if chopping is rejected: it
  would support only about +/-25 C / +/-9 C.
- **C. Chopped amplifier plus dynamic element matching of the three mirror legs** — projected RSS about 5.6 C untrimmed / 2.5 C
  trimmed worst corner (mirror residual taken as 0.1 % effective, an unverified assumption). Needs a rotation clock, a
  filter on PTAT/CTAT, and it changes the DR-005 sensor-output scope; not recommended until B is simulated. It would
  not reach the draft +/-3 C / +/-1.5 C either, because the resistor and PNP terms (4.6 and 2.9 C untrimmed) remain.
- **Larger PNP and longer R1 to reach the draft +/-3 C / +/-1.5 C** — not evaluated; recorded as the next lever after B.
- **2-point (offset + gain) trim** — not evaluated; the record models only the 1-point gain trim, and the per-die test
  cost is a spec decision, not a design one.

## Spec lines affected

Proposes a value for `[TBD-1]` (temperature error, untrimmed and 1-point trim); changes nothing yet.
`README.md`'s `Temperature error, untrimmed` row stays `[TBD-1]` / `not ratified`. Ratification, if any, is the
separate two-key step, after the post-change campaign described under Consequences.

## Consequences

- **Design work, separate issue**: schematic changes to `temp_core` (chopper or auto-zero stage; MP1..3 re-sized and
  degenerated). Not implemented here.
- **Headroom to verify**: at 2.97 V and 125 C the PTAT branch has about 1.1 V between VDD and PTAT for MP3, MPC3 and
  the new degeneration drop (~0.4 V at 125 C); that is feasible but tight and unsimulated. The gate voltage PG also
  moves by the degeneration drop.
- **Chopping side effects**: a ripple on PTAT that the readout must filter, a clock (or an on-chip oscillator) in a
  block that currently needs none, and a new cold-start/ramp behaviour to cover in the supply-ramp matrix (#86's
  startup campaigns).
- **Re-run required**: the #105 campaign on the changed netlist, with an `mmoff_*` term set updated for the new
  devices and N >= 100 per corner, submitted through `klt sim` on the fleet backend; this DR's figures are
  projections, not measurements. Until then the row cannot be ratified.
- **T1 items 5 and 6 (#4)** stay gated: the accuracy row is now characterised (and understood), not closed.
- **Bad consequence**: the recommended change does not meet the draft +/-3 C / +/-1.5 C. A row of about +/-12 C untrimmed
  is a poor sensor spec; the DR says so rather than hiding it.
- **Not covered**: global process Monte Carlo, layout/gradient mismatch, dynamic behaviour, trim-ladder resolution
  (see the record's "Not measured"); the budget inherits all of those limits.
