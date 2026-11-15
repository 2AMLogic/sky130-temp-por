# `por-output-chain-deglitch` — cell-level deglitch/one-shot record for `por_output_chain` (issue #349)

Cell-level, 45-point PVT transient of the **unchanged**
`design/por_output_chain.sym`, driven from **ideal comparator and bias
inputs**, run through `sim/bin/corner-run.py` and submitted to the batch
fleet as one `klt sim` request. **Not a spec claim** — no deglitch time,
reset-pulse width, valid-low floor or released-level target is ratified
anywhere in `spec/` (`design/por_output_chain.md`, DR-003 §8); every window
below is a harness-liveness band with its derivation stated in
`experiment.json`.

## Why this experiment exists

`por_output_chain` was the only leaf cell with no cell-level record: it is
exercised only inside the whole-block campaigns (E9–E11, E14), where its
behaviour is mixed with the non-physical solver branches those campaigns
report, and its deglitch delay, RESETn drive and short-pulse behaviour were
measured nowhere on their own (`docs/characterization-report.md` gap 3,
second clause — this experiment closes that clause; the first clause,
comparator mismatch Monte Carlo, is #348's).

## Stimulus

| element | drive |
| --- | --- |
| `V1` (VDD) | `'vsup'`, set per corner by the runner / klt supply axis |
| `I1` (IBIAS) | ideal 1 µA into the node — bias_core delivers 0.78–1.2 µA across the matrix (`sim/bias-core-startup`, glitch-top delivered-bias measurement) and `sim/iq-top`'s ideal-bias variant uses exactly 1 µA |
| `V2` (POR_RAW) | one PWL: rise 100 µs → fall 200 µs (a **100 µs sub-deglitch pulse**), hold low through 1.999 ms, rise at **2 ms** (the real trip, ~1 µs ramp) and stay high; window 10 ms, `uic` cold start |

The ordering *is* the rejection mechanism: the real trip is the last edge,
so RESETn has exactly **one** rising half-rail-class crossing in the window.
A release landing one deglitch-time after the 2 ms trip proves the earlier
pulse contributed nothing; a pulse-honoring corner would release at ~1.5 ms
— before the trip — and fails both release windows outright.

## What is measured (and what it means)

- `release_delay` — trip → RESETn crossing 1.65 V rising. Extraction:
  `integ()` of the boolean `v(resetn) gt 1.65` over the tran's own
  (non-uniform) time grid, indexed to its final element. The window
  (0.5–4 ms) brackets the tt/27 °C/3.3 V pre-submit local probe
  (**1.204 ms**) and `design/por_output_chain.md`'s 1.72 ms smoke point at
  ~0.78 µA real bias. **The cell's deglitch delay had never been measured
  before this experiment** — there is no prior number to bracket.
- `t_release` — the absolute release instant (probe: 3.204 ms).
- `rstn_released` — released high level (probe: 3.014 V of 3.3 V — XMOP's
  drive balancing the always-on MASSIST bleed, a real drop, not a hard
  rail).
- `rstn_asserted` — asserted low level (probe: −4.4 µV; the design doc's
  own `.op` value is 6.5e-10 V).
- `tim_min/max`, `ndg_min/max`, `trip_min/max`, `rstb_min/max` — rail-band
  physicality guards (±1 V margins, temp-core convention) on the four
  internal nodes that carry the deglitch/one-shot/release-latch mechanism.
- `spread_checks`: release_delay spread floor 100 µs — a corner-blind
  harness (`.lib`/`.temp` not taking effect) fails loudly.

## What is NOT measured / claimed

- **No spec value.** No deglitch time, pulse-width, floor or valid-high
  target is proposed or met; the windows are liveness bands, and the record
  says so.
- **Not the shared-bias assembly.** IBIAS is ideal; the POR_RAW source is an
  ideal PWL, not `por_comparator`'s output. Whole-block context is E9–E11
  and E14.
- **No ramp-rate, brown-out, re-assertion or repeated-glitch coverage** —
  the supply is a fixed per-corner value with a single trip edge; supply
  ramping belongs to the whole-block testbenches per root `CLAUDE.md`.
- **No reset-pulse-width derivation.** The one-shot's pulse *duration*
  after a rejected-then-accepted sequence is not extracted here.
- **No layout/post-layout claim** — schematic-only (out of scope, issue's
  own list).

## Harness constraints this manifest works within

- The batch backend accepts **exactly one deck analysis**
  (`sim/bin/corner-run.py build_batch_request`), so the deck is one
  `tran 10u 10m uic` and every measurement is a single self-contained
  expression — the sibling manifests' `let nlast = …` helper-line idiom is
  **not available** here.
- The tran time grid is non-uniform (ngspice-47 emitted 1076 points of
  varying spacing in the probe), so the count-based
  `mean()*length()*tstep` idiom of `sim/native-device-characterization/`
  is not valid on this deck; `integ()[length(...)-1]` is grid-robust.
- The fleet path runs with the repo's `set ng_nomodcheck` (netlist-carried
  `NOMODCHECK_CONTROL`); without it ngspice-46/47 abort before simulating
  on this cell's `nfet_05v0_nvt` (`pdits negative` BSIM parameter check).
- Model-bin legality under the current pin (`f6eeac7d`) re-verified
  2026-11-14: `XMN1` (L=20 W=0.42) and `XMASSIST` (L=25 W=1) are both
  in-bin; no `model_not_found` is expected.

## Running

```sh
# liveness subset (3 points, local) -- not a record
python3 sim/bin/corner-run.py sim/por-output-chain-deglitch --quick \
    --subset-reason "harness liveness check"

# print the 45-point batch request without submitting
python3 sim/bin/corner-run.py sim/por-output-chain-deglitch --backend batch --dry-run

# the record: one 45-point klt sim batch request (no local multi-point grid)
python3 sim/bin/corner-run.py sim/por-output-chain-deglitch --backend batch
```
