# `por-comparator-thresholds` — VPOR-up / VPOR-down / hysteresis of `por_comparator`

Issue #102. **Evidence, not a spec claim.** This campaign measures the supply
voltages at which `design/por_comparator.sch` (committed export
`design/netlist/por_comparator.spice`, unchanged) switches `POR_RAW`. It
measures them on a slow, constant-rate VDD sweep, over process x temperature.
The numbers below are **proposals** for a separate follow-on DR-003 amendment
that would resolve `[TBD-2]` (VPOR-up/VPOR-down) and `[TBD-3]` (hysteresis
floor/ceiling) in
`spec/decision-records/DR-003-ratify-target-spec-recommendation.md` rows 4/5.
They are **not ratified**. This campaign does not edit `spec/` or `design/`
and does not relax anything.

## What is measured

| quantity | definition (this campaign's, not a ratified bound) |
|---|---|
| VDD stimulus | `V(VDD) = min(3.63, rate*t, max(0, 2*3.63 - rate*t))`. The supply starts at a physical 0 V, rises at constant +rate to the DR-001 high rail (3.63 V), then falls at -rate back to 0 V. Total time is `2*3.63/rate`, derived from the rate rather than a fixed duration, which avoids the gf180 DR-021 ramp-rate/supply confound (porting-plan §2.3). |
| sweep rates | primary **100 V/s** (72.6 ms sweep) plus the **50 V/s half-rate guard** (145.2 ms), each as its own `klt sim` request |
| POR_RAW polarity | `POR_RAW` is **high** when `v(POR_RAW) > 0.5*v(VDD)`, i.e. above half the instantaneous supply. It is evaluated only for `VDD >= 1.0 V`; below that the comparator has no meaningful rail. On the UP sweep `POR_RAW` is expected to **rise** (reset released). On the DOWN sweep it is expected to **fall** (reset re-asserted). A crossing in the other direction is reported as `wrong_direction`. |
| VPOR-up | VDD at the single rising `POR_RAW` crossing of the UP segment, linearly interpolated between the two bracketing samples |
| VPOR-down | VDD at the single falling crossing of the DOWN segment |
| hysteresis | VPOR-up - VPOR-down at the same process/temperature |
| resolution | max time step 20 us = **2 mV of VDD** per sample at 100 V/s (1 mV at 50 V/s). An edge whose bracketing samples are more than 10 mV of VDD apart is `unresolved`. |
| non-results | a segment with no crossing is reported as `no_transition`, along with the state it stayed in. Several crossings are `multiple_transitions`. Neither is ever omitted, and either makes the point `NO_RESULT`. |
| quasi-static guard | VPOR-up and VPOR-down at 100 V/s must agree with 50 V/s within **10 mV**, a tolerance chosen for this campaign and not ratified. Otherwise the point is `RATE-DEPENDENT`. If the half-rate waveform is missing, the point is `UNGUARDED`. Either way it is kept in the table and left out of the binding set. |
| margin | `2.97 V - max(VPOR-up)` against the DR-001 low rail. A non-positive value is a measured failure, never a reason to relax the spec. |

## IBIAS / VREF / BIAS_OK treatment (two variants, never mixed)

The DUT has the ports `VDD VSS IBIAS VREF BIAS_OK POR_RAW`. The campaign runs
two separately recorded variants (`variants` in `experiment.json`):

| variant | testbench | IBIAS | VREF | BIAS_OK | why |
|---|---|---|---|---|---|
| **`ideal-bias`** (PRIMARY) | `testbench/tb_por_comparator_thresholds.sch` | ideal 1 uA source into the mirror-input node | ideal `min(1.25 V, v(VDD))` | `v(VDD)` (always asserted) | Isolates what the comparator itself sets: the xhigh_po divider ratio (XRTOP/XRBOT), the comparator offset, and the XRHYS/XMHSW hysteresis network. `bias_core`'s own process/temperature/startup behaviour (issue #86) is kept out of the threshold numbers. 1 uA and 1.25 V are the `bias_core` intended-branch values (`sim/bias-core-startup`). |
| **`real-bias-core`** (second, separate table) | `testbench/tb_por_comparator_thresholds_realbias.sch` | real `design/netlist/bias_core.spice` on the same VDD | real `bias_core` | real `bias_core` | Shows how far the real VREF(P,T,VDD) and delivered IBIAS move the edges relative to the ideal-bias numbers |

## Corner axes

- **main** (the issue's grid): process `tt, ss, ff, sf, fs` x temperature
  `-40, 27, 125 C` = 15 points, at both rates, for both variants. VDD is the
  swept variable, so there is no separate supply axis. The klt `supply_v`
  axis carries only the 3.63 V sweep peak.
- **passive-skew** (supplement, separate records ending in `-passive-skew`):
  process `ll, hh` x the same 3 temperatures. sky130's `ll`/`hh` `.lib`
  sections are tt MOS with low/high resistor and capacitor parameters. Per
  `sim/pdk.json` they are the **only** sections that move xhigh_po sheet
  resistance; tt/ss/ff/sf/fs all share `parameters_res_nom`. klt passes a
  bare process name straight through to `.lib`, so this axis is reachable.
  Combined MOS-corner x resistor-skew points (for example ss MOS with high
  resistors) are **not** run.
- **mc** (supplement, issue #348, separate records ending in
  `-mismatch-mc`): local **mismatch Monte Carlo** on the `real-bias-core`
  variant only — process sections `tt_mm, ss_mm` x temperature
  `-40, 27, 125 C`, at the primary 100 V/s rate, N = 20 mismatch samples per
  corner (klt `monte_carlo` block, `vary: mismatch`; local mismatch only,
  never `MC_PR_SWITCH` global process MC). One `klt sim` request per
  (process, temperature) = 6 requests: the measured worst-corner cost of the
  real-bias-core 100 V/s grid is 142 s, so 20 x 142 s = 2840 s fits the
  fleet's 3600 s per-job ceiling with headroom, while a request folding the
  three temperatures together (60 x 142 s = 8520 s) would hit
  `batch_job_timeout` — the failure `sim/temp-core-accuracy-mc` already
  recorded. Each request's seed is the base seed plus a distinct offset
  (`tt/-40C -> 20261115` … `ss/125C -> 20261120`; klt derives per-sample
  seeds from the corner index, which is 0 in every one-corner request here,
  so a shared base seed would re-draw the same realisations in all six).
  Each sample is its own transient VDD sweep and returns its own waveform;
  `threshold_extractor.py` extracts that sample's VPOR-up / VPOR-down, and
  hysteresis is computed **per sample**. The record reports, per corner, the
  mean and sample sigma (Bessel, n-1) of the three metrics over the valid
  samples, the N, and the statistical resolution of that sigma,
  `1/sqrt(2(N_valid-1))` (16.2% at N = 20). Disclosures: the MC points run
  **without** the half-rate quasi-staticity guard; temperatures draw
  **independent** realisation sets, so per-corner statistics are valid and no
  per-sample temperature-drift or temperature-correlation claim is made; the
  ideal-bias variant, ff/sf/fs, the ll/hh axis, global process MC and
  post-layout parasitics are not sampled. Evidence only — the record states
  no threshold and edits neither `spec/` nor DR-004.

## Cold-start invocation (from a clean checkout)

Prerequisites: `xschem`, `klt` (klayout-tools, with `KLT_SIM_BACKEND=batch`
fleet credentials), and the pinned PDK
(`ciel enable --pdk-family sky130 -l sky130_fd_pr f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, or
`PDK_ROOT` pointing at an install of that commit). The working tree must be
clean: `run` and `record` both refuse a dirty tree, because records carry
the commit SHA.

```sh
cd sim/por-comparator-thresholds

# 0. extractor selftest (stdlib only, no simulation; also run by CI)
python3 -I threshold_extractor.py

# 1. submit the 5x3 grid to the Spot batch fleet: 2 variants x 2 rates
#    = 4 klt sim requests of 15 points each. Raw outputs go to sim/build/ (gitignored).
python3 run_thresholds_campaign.py run --run-id main --capacity-wait 2700
#    a request refused for fleet capacity is re-submitted (only the failed
#    ones; earlier attempts are archived, not overwritten):
python3 run_thresholds_campaign.py run --run-id main --retry-failed --capacity-wait 2700

# 2. optional ll/hh passive-skew supplement (2 x 2 requests of 6 points)
python3 run_thresholds_campaign.py run --axis passive-skew --run-id skew --capacity-wait 2700

# 2b. mismatch Monte Carlo supplement (issue #348): 6 requests, one per
#     (process, temperature), N = 20 mismatch samples each, real-bias-core only
python3 run_thresholds_campaign.py run --axis mc --run-id mc --capacity-wait 600

# 3. ONE single-corner local cross-check (the only local simulation; never a grid)
python3 run_thresholds_campaign.py probe --variant ideal-bias --process tt --temp 27

# 4. extract + write the append-only evidence (records/, corners/, netlist-snapshots/)
python3 run_thresholds_campaign.py record --run-id main --author "<name>" --probe-note-file <note.md>
python3 run_thresholds_campaign.py record --run-id skew --author "<name>"
python3 run_thresholds_campaign.py record --run-id mc --author "<name>"
```

The driver never launches ngspice over a grid itself. Every multi-point run
is a `klt sim` request with explicit `--backend batch`, and each record lists
the fleet job ids (`environment.remote.job_id`). The fleet runner (klt 0.5.0,
ngspice-46) ignores `options.ngspice_init`, so `set ng_nomodcheck` travels in
a `.control` block inside the generated netlist.

## Results

Records: `records/` (markdown + JSON). Per-point ngspice logs and
change-triggered VDD/POR_RAW/VREF traces: `corners/<record-id>/`. Exact
fleet netlists and requests: `netlist-snapshots/<record-id>/`. Every fleet
request was submitted from a clean tree on `feature/issue-102`. The main
grid used `5e78ab3`. The passive-skew requests used `10d3e9f` and
`9f589eb`, which differ from `5e78ab3` only in runner, manifest and
evidence files; the testbenches and DUT netlists are unchanged. Each
record's fleet-submissions table names the submit commit of every request.

### Main grid: 15/15 points per variant, all rate-consistent

All 4 fleet requests (2 variants x 2 rates, 60 points) passed. Every point
shows exactly one rising edge on the UP segment and one falling edge on the
DOWN segment, each bracketed by 2 mV of VDD. There are no `no_transition`,
`multiple_transitions`, `unresolved` or `RATE-DEPENDENT` points. The worst
full-vs-half-rate delta is 1.8 mV (ideal-bias) and 3.3 mV (real-bias-core),
against the 10 mV guard. No ngspice log contains a model-bin or fatal error,
so every `por_comparator` (and `bias_core`) device resolved a model at every
corner.

**`ideal-bias`** (record `records/20261009-054322-10d3e9f-ideal-bias.md`;
fleet jobs `klt-sim-2371181be7d8` at 100 V/s and `klt-sim-6f5cf1c50d2f` at
50 V/s)

| metric | min | corner | max | corner |
|---|---|---|---|---|
| VPOR-up | 2.6832 V | ff, 125 C | 2.7010 V | ss, -40 C |
| VPOR-down | 2.5430 V | fs, 125 C | 2.5510 V | ss, -40 C |
| hysteresis | 139.7 mV | sf, 125 C | 150.1 mV | ss, -40 C |

**`real-bias-core`** (record
`records/20261009-054331-79eebd4-real-bias-core.md`; fleet jobs
`klt-sim-5fdfcee6a735` at 100 V/s and `klt-sim-34aea90a673a` at 50 V/s)

| metric | min | corner | max | corner |
|---|---|---|---|---|
| VPOR-up | 2.6908 V | sf, -40 C | 2.7130 V | ss, 27 C |
| VPOR-down | 2.5353 V | sf, -40 C | 2.5567 V | ss, 27 C |
| hysteresis | 145.9 mV | sf, 125 C | 156.3 mV | ss, 27 C |

**Margin vs the DR-001 2.97 V low rail** (`2.97 V - max(VPOR-up)`):

| variant | max(VPOR-up) | margin | min(VPOR-up) | 3.63 V high rail above max(VPOR-up) |
|---|---|---|---|---|
| ideal-bias | 2.7010 V (ss, -40 C) | **+269 mV** | 2.6832 V (ff, 125 C) | +929 mV |
| real-bias-core | 2.7130 V (ss, 27 C) | **+257 mV** | 2.6908 V (sf, -40 C) | +917 mV |

Both margins are positive. At every simulated corner the rising threshold
is at least 257 mV below the worst-case low rail.

**Local cross-check** (one point, `--backend local`, host ngspice-42,
ideal-bias, tt, 27 C, 100 V/s): VPOR-up 2.6932 V vs the fleet's 2.6950 V
(-1.9 mV, inside one 2 mV sample step). VPOR-down 2.5470 V matches the
fleet exactly.

### Reading of the numbers (evidence for the DR-003 amendment, not ratified)

- **Thresholds are set by the divider ratio, not by MOS process.** In
  ideal-bias, VPOR-up spans only 18 mV and VPOR-down only 8 mV over all
  15 points. The divider is all xhigh_po, and the five MOS corners leave
  resistor parameters at nominal (`sim/pdk.json`). With an ideal VREF,
  temperature is the larger effect: VPOR-up falls 12-14 mV from -40 to
  125 C at every MOS corner, while the MOS corner spread at 27 C is 4 mV.
- **Real `bias_core` moves the edges by -6 to +20 mV (VPOR-up) and -13 to
  +12 mV (VPOR-down)** relative to ideal-bias at the same corner. It also
  reverses the temperature trend: VPOR-up now rises 6-8 mV from -40 to
  125 C, and the 27 C corner spread grows to 10 mV. Both effects follow the
  real VREF(P,T). The real-bias binding corners are ss/27 C (high side) and
  sf/-40 C (low side). Hysteresis grows by 4.5-9.6 mV.
- **Hysteresis is about 140-156 mV** across both variants. That is above
  the README's unsourced "100 mV" floor (DR-003 row 5). A **ceiling** still
  needs the `[TBD]` `por-digital-min-vdd` input (porting-plan §2.3), which
  this campaign cannot supply. VPOR-down,min (2.535 V, real bias) is the
  number that ceiling would be checked against.
- **What these numbers do not cover:** the corner tables are corner values of
  the nominal drawn circuit. Mismatch Monte Carlo is now run as the `--axis
  mc` supplement (real-bias-core, tt/ss, N = 20 per corner, issue #348); a
  DR-003 amendment should weigh its distributions before treating +257 mV as
  the design margin. Still not covered: combined MOS x resistor-skew corners,
  post-layout parasitics (MC included), sweep rates other than 100/50 V/s,
  and mismatch on the ideal-bias variant. Fast-ramp behaviour of the
  assembled block is `sim/supply-ramp-top/`'s job.

### Passive-skew supplement (ll/hh x -40/27/125 C, tt MOS): 6/6 per variant

Records: `records/20261009-062844-09eb234-ideal-bias-passive-skew.md` and
`records/20261009-062845-bf30f6c-real-bias-core-passive-skew.md`. All points
show clean single edges and are rate-consistent (worst guard delta 3.9 mV).
These tables stand alone; they are **not** merged into the 5x3 tables above.

| variant | VPOR-up min / max | VPOR-down min / max | hysteresis min / max | margin vs 2.97 V |
|---|---|---|---|---|
| ideal-bias | 2.6868 V (ll, 125 C) / 2.6990 V (hh, -40 C) | 2.5430 V (hh, 125 C) / 2.5490 V (ll, -40 C) | 141.8 mV (ll, 125 C) / 150.3 mV (hh, -40 C) | +271 mV |
| real-bias-core | 2.6950 V (ll, -40 C) / 2.7110 V (hh, 27 C) | 2.5412 V (ll, -40 C) / 2.5557 V (ll, 125 C) | 147.8 mV (ll, 125 C) / 158.1 mV (hh, 27 C) | +259 mV |

With an ideal reference, ll vs hh moves VPOR-up by at most 0.2 mV and
VPOR-down by at most 2 mV against the tt points at the same temperature, so
the divider-ratio cancellation holds. With real `bias_core`, hh widens the
hysteresis by about 2-4 mV compared with tt. Neither changes the binding
corners or the margin of the main grid.

### Post-layout variants (issue #124)

`ideal-bias-postlayout` and `real-bias-core-postlayout` re-run the same 5x3 grid at both rates with the `por_comparator` DUT
replaced by the klt-extracted lumped-RC netlist (`layout/por_comparator/pex/`). New record ids; the schematic records above are
untouched. Delta table, extraction model, and the `klt pex` blocker (pin order, MOS flavour) are in
[`layout/por_comparator/pex/README.md`](../../layout/por_comparator/pex/README.md). Run with `run --variant <name>-postlayout`

### Mismatch Monte Carlo supplement (issue #348): real-bias-core, tt/ss x -40/27/125 C, N = 20 per corner

Record: `records/20261115-002854-ad5bbeda-real-bias-core-mismatch-mc.md` (+
`.json`); fleet jobs `klt-sim-75437447430e`, `klt-sim-fcad8d4af43e`,
`klt-sim-f0072776735a`, `klt-sim-d71889c27127`, `klt-sim-2e35a2e1c04a`,
`klt-sim-c4092f427b38` (one per (process, temperature), 20 mismatch samples
each, seeds 20261115-20261120, primary 100 V/s only, no half-rate guard).
Per corner, over the **valid** samples (Bessel (n-1) sigmas; hysteresis per
sample):

| corner | N valid/N run | VPOR-up mean ± sigma (V) | VPOR-down mean ± sigma (V) | hysteresis mean ± sigma (mV) | sigma resolution | excluded |
|---|---|---|---|---|---|---|
| tt/-40C | 13/20 | 2.7789 ± 0.1520 | 2.6195 ± 0.1444 | 159.4 ± 7.6 | 20.4% | 7 |
| tt/27C | 10/20 | 2.7023 ± 0.1157 | 2.5521 ± 0.1127 | 150.2 ± 14.4 | 23.6% | 10 |
| tt/125C | 15/20 | 2.7396 ± 0.1478 | 2.5874 ± 0.1405 | 152.2 ± 7.4 | 18.9% | 5 |
| ss/-40C | 11/20 | 2.7675 ± 0.1033 | 2.6082 ± 0.0979 | 159.3 ± 5.5 | 22.4% | 9 |
| ss/27C | 13/20 | 2.7344 ± 0.1006 | 2.5776 ± 0.0957 | 156.9 ± 5.0 | 20.4% | 7 |
| ss/125C | 19/20 | 2.7283 ± 0.1405 | 2.5749 ± 0.1335 | 153.3 ± 7.1 | 16.7% | 1 |

Two findings the corner tables could not show:

- **The mismatch spread of the thresholds is an order of magnitude larger
  than the corner envelope.** VPOR-up spans 18 mV across the whole 5x3
  corner grid of the nominal circuit; under mismatch its sigma is
  100-152 mV at every simulated corner. The record states the resolution of
  each sigma (17-24% at these N) alongside.
- **38 of 120 samples never release reset at all**: POR_RAW held low through
  the entire 0 -> 3.63 V -> 0 sweep (up AND down `no_transition`), with
  `bias_core`'s VREF healthy (1.14-1.38 V at the intended branch), i.e. the
  failure is downstream of the reference. One further sample shows
  `multiple_transitions` on the DOWN segment. The per-corner distributions
  therefore describe the **releasing subset** only; the failed-release
  fraction (5-50% per corner) is part of the mismatch behaviour, and neither
  DR-004's +257 mV corner margin nor a release-subset sigma describes those
  samples.

Evidence only, as everywhere in this campaign: no threshold is proposed,
`spec/` and DR-004 are untouched. Temperatures draw independent realisation
sets, so no per-sample temperature-drift claim is made.
(post-layout variants are never part of the default `run`).

### Fleet friction (reported, not worked around locally)

25 batch launches were refused before a request ran: 22 by the shared
fleet's `BATCH_MAX_CONCURRENT_INSTANCES=8` cap and 3 by a Spot "no capacity
in any of the 30 pools" shortfall. Each refused request was re-submitted
unchanged (`run --retry-failed`) until it ran, and no point fell back to a
local grid. Each record counts its request's refusals in the
fleet-submissions table. The main `real-bias-core` record lists its 8 as
"unparseable report", because it was written before the runner learned to
read the error document klt puts on stderr. The raw `klt.stderr` for each
of those attempts is the concurrency-cap message. `request.batch.capacity_wait_s`
does not wait out the concurrency-cap refusal, and `--format json` leaves
stdout empty on a launch failure. Both gaps are tracked at
2AMLogic/klayout-tools#2917.
