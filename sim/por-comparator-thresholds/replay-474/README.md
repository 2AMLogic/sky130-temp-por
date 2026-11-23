# Issue #474 replay evidence (scratch replays; not a campaign record)

Replays of two residual classes from the #455 fresh-seed campaign (record
`20261121-115035-c591b93b`). ngspice-47 local single-unit runs and one 20-sample
fleet request per corner (`klt sim --backend batch --wait-for-capacity 600`),
sky130A @ open_pdks f6eeac7d, base deck from `run_thresholds_campaign.py` at
`50e1d37f`-equivalent netlist (XRT L=350, XMOK2 L=4 W=8). Seeds are the record's:
`build_mc_replay_request.py tt -40 1 20261202` reproduces the recorded per-sample
seeds exactly (tt/-40C mc13: rndseed 2125796897, mismatch_seed 1401514179; local
replay row count 3656 and VPOR-up 2.85502 V / VPOR-down 2.69226 V equal the record).

## Replaying the committed decks

The three `*.cir` decks are the `klt sim` corner decks for the tt/-40C mc14 draw (default, `gmin=1e-11`,
`gmin=1e-9`) with two lines **elided** by hand so the decks stay path-independent; they do not run as
committed. To replay one:

1. `python3 build_mc_replay_request.py tt -40 1 20261202 <dir>` writes `<dir>/netlist.spice` and
   `<dir>/request.json` (paths resolve from the script's own location, so it runs from any checkout).
2. Replace `.include <netlist.spice from run_thresholds_campaign.py mk>` with `.include <dir>/netlist.spice`.
3. Replace the comment `* write <raw>` with `write <dir>/replay.raw` (inside the `.control` block, after `tran`),
   and set `PDK_ROOT` to the sky130A install (the `.lib` line uses `$PDK_ROOT`).
4. `ngspice -b <deck>`; then `python3 extract_ascii_raw.py <dir> replay` extracts the thresholds from the ASCII raw.
   `chatter_trace.py <dir>` needs a `waveform.raw.json` from a `klt sim` run of the request instead.

The `uic` variant has no committed deck: it is the base deck with ` uic` appended to the `tran` card (the
`monte_carlo.tran_uic` flag in `experiment.json`); its generated decks are in `netlist-snapshots/`.

## Class 2 -- initial-timepoint abort (tt/-40C mc14, request seed 20261202)

Fleet replay of the unchanged deck: `tt_mm/3.630V/-40C/mc14` -> `timestep_too_small`
(19 of 20 samples pass). Local replay: `Initial Transient Solution` prints, then
`doAnalyses: TRAN: Timestep too small; initial timepoint`, 1 data row. At t=0
VDD=0 and every node is ~0 V; the DC solution carries `bvdd#branch` = -3.5 mA.

One-variable comparison on that exact deck (only the listed line added):

| variant | transient | VPOR-up (V) | VPOR-down (V) |
|---|---|---|---|
| default (gmin 1e-12) | ABORT at t=0 | - | - |
| `.options gmin=2e-12` | completes | 2.69305 | 2.53895 |
| `.options gmin=5e-12` | completes | 2.69411 | 2.53964 |
| `.options gmin=1e-11` | completes | 2.69404 | 2.53971 |
| `.options gmin=2e-11` | completes | 2.69409 | 2.53991 |
| `.options gmin=1e-10` | completes | 2.69491 | 2.54110 |
| `.options gmin=1e-9`  | completes | 2.71335 | 2.55864 (outside plateau: leakage-scale) |
| `.options method=gear`, `itl4=100`, `trtol=1`, `cshunt=1e-15` | ABORT | - | - |
| `.options rshunt=1e12` | completes, but see controls | multiple_transitions | 2.53895 |

`gmin` alone is NOT sufficient. A fleet run of the paired matrix (tt/ss, seed 20261114) with
`.options gmin=1e-11` carried in the netlist still aborted two cold draws at the initial timepoint
(tt/-40C mc6, `trouble with node "xdut.bias_okb"`; ss/-40C mc9). tt/-40C mc6 replayed locally
aborts at gmin 1e-12, 1e-11, 1e-10 and 1e-9, and under `rshunt` 1e10/1e12, `itl1=500`, `gminsteps/srcsteps=0`,
`reltol=1e-2`, `abstol/vntol` and `pivtol/pivrel` changes (the testbench already sets `method=gear trtol=50`).

What works is `uic` on the `.tran` card. The VDD stimulus starts at a physical 0 V, so the all-zero
initial state `uic` uses is the physical state, and the DC operating point at VDD=0 -- the solve that
fails -- is skipped. Same decks, default gmin:

| draw | default | `.tran ... uic` |
|---|---|---|
| tt/-40C mc14 (abort draw) | ABORT | completes, up 2.69434 / down 2.53927 V (gmin plateau: 2.694 / 2.540) |
| tt/-40C mc6 (abort draw)  | ABORT | completes, up 2.80523 / down 2.64442 V |

Passing controls, same seeds, default vs `uic` (thresholds must match):

| control | default up/down (V) | uic up/down (V) | delta up/down (mV) |
|---|---|---|---|
| tt/-40C mc13 | 2.85502 / 2.69226 | 2.85437 / 2.69163 | -0.65 / -0.63 |
| tt/-40C mc0 | 2.61710 / 2.46377 | 2.61830 / 2.46407 | +1.20 / +0.30 |

(gmin 1e-11 moved the same controls by -1.08/+0.10 and -0.05/+0.81 mV; `rshunt=1e12` broke the
mc0 control, `NO_RESULT (down:no_transition)`, and is rejected.) Controls move by <= 1.2 mV,
below the 2 mV VDD sample step. The abort is a DC-solution conditioning failure at the all-zero
supply point, not a design fault; the fix is harness-side startup (`monte_carlo.tran_uic`), with
stimulus, corners, sampling and grading unchanged.

## Class 1 -- POR_RAW chatter (ss/-40C mc14, request seed 20261205)

Fleet replay reproduces `NO_RESULT (up:multiple_transitions)`: POR_RAW rises at
VDD=1.8203 V, falls at 1.8270 V, rises at 2.6394 V (VPOR-down 2.4866 V).
`chatter_trace.py` output for the draw vs control mc13 (`OK`, up 2.563 V):

| quantity | mc14 (chatter) | mc13 (control) |
|---|---|---|
| NOKO loop-off plateau peak | 0.642 V @ VDD~1.68 | 0.664 V @ VDD~1.72 |
| NOKO collapse (NOKL meets NA) | VDD 1.72-1.78 V | 1.74-1.80 V |
| NA / NOKL at BIAS_OK assertion | 0.762 / 0.766 V | 0.759 / 0.804 V |
| BIAS_OK asserts at | 1.821 V | 1.862 V |
| POR_RAW | pulses high 1.8203-1.8270 V | no pulse |

The issue's hypothesis (plateau 0.73-0.78 V reaching a ~1.0 V assertion point) is NOT what
happens at ss/-40C: the loop-off plateau is 0.64-0.66 V and NOKX switches when NOKL
crosses the NA mirror reference near VDD 1.8 V. On mc14 BIAS_OK asserts 41 mV earlier
and while NA is still settling (0.726 -> 0.762 V), POR_RAW pulses high for 7 mV of VDD
(70 us at 100 V/s) at VDD=1.82 V, 0.8 V below VPOR-up. On ss/-40C this is an early-assertion
glitch of POR_RAW, not an assertion-threshold/plateau collision (sf/-40C mc16: glitch, not earlier; see below).

The second named chatter case, sf/-40C mc16 (fresh record 20261121-115035-c591b93b, request seed
20261211 = 20261201 + 10, default startup), was traced from the original fleet job
(`klt sim --attach klt-sim-c0de828c00a5` with the committed request/netlist snapshot, no new run) with
`chatter_trace.py`; control = sf/-40C mc15 of the same request (`OK`, up 2.652 V). Same extraction as the ss table:

| quantity | sf mc16 (chatter) | sf mc15 (control) |
|---|---|---|
| verdict (default startup) | NO_RESULT (up:multiple_transitions): rise 1.8170 V, fall 1.8232 V, rise 2.7280 V; VPOR-down 2.570 V | OK, up 2.652 V / down 2.4996 V |
| NOKO loop-off plateau peak | 0.631 V @ VDD~1.66 | 0.619 V @ VDD~1.66 |
| NOKO collapse (< 0.1 V) | VDD ~1.74 V | VDD ~1.72 V |
| NOKL meets NA | VDD 1.78-1.80 V | VDD 1.76-1.78 V |
| BIAS_OK asserts at | 1.818 V | 1.804 V |
| POR_RAW | pulses high 1.8180-1.8229 V (about 5 mV of VDD, 50 us) | no pulse |

What carries over from ss: the plateau is 0.62-0.63 V, not 0.73-0.78 V, so the issue's plateau-collision
hypothesis is refuted at sf/-40C too, and POR_RAW again pulses at the BIAS_OK assertion edge, 0.9 V below
VPOR-up. What does NOT carry over: on sf mc16 BIAS_OK asserts 14 mV *later* than the control, not earlier, so
the "41 mV earlier, NA still settling" feature is specific to the ss/-40C mc14 draw. With one control per
case the earliness claim is established for ss only; the common element is the POR_RAW glitch at the
assertion edge while NA is moving (NA steps 0.693 -> 0.760 V across the assertion step on mc16). The same
`uic` campaign extracts sf/-40C mc16 cleanly (record 20261123-210355-a21a8ca0, up 2.6724 V corner mean over
20/20), i.e. the chatter is solver-state sensitive here too.

One-variable comparison on the exact ss/-40C mc14 deck (local, ngspice-47):

| variant | verdict | VPOR-up (V) | VPOR-down (V) |
|---|---|---|---|
| default | NO_RESULT (up:multiple_transitions) | - | 2.48656 |
| `.options gmin=1e-11` | OK | 2.63904 | 2.48696 |
| `.tran ... uic` | OK | 2.63837 | 2.48763 |

The chatter is therefore marginal and solver-state sensitive: a ~1 mV-scale change in the
numerical solution removes a 7 mV-wide POR_RAW pulse, and the sf/-40C mc16 draw also extracts
cleanly in the `uic` campaign (record 20261123-210355-a21a8ca0). The underlying POR_RAW glitch at the
BIAS_OK assertion edge (ss: 1.82 V vs 1.86 V on the control, while NA is still settling) is a real
sensitivity of the detector that this iteration does NOT correct; no design change was made.
