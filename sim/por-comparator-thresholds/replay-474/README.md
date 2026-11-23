# Issue #474 replay evidence (scratch replays; not a campaign record)

Replays of two residual classes from the #455 fresh-seed campaign (record
`20261121-115035-c591b93b`). ngspice-47 local single-unit runs and one 20-sample
fleet request per corner (`klt sim --backend batch --wait-for-capacity 600`),
sky130A @ open_pdks f6eeac7d, base deck from `run_thresholds_campaign.py` at
`50e1d37f`-equivalent netlist (XRT L=350, XMOK2 L=4 W=8). Seeds are the record's:
`build_mc_replay_request.py tt -40 1 20261202` reproduces the recorded per-sample
seeds exactly (tt/-40C mc13: rndseed 2125796897, mismatch_seed 1401514179; local
replay row count 3656 and VPOR-up 2.85502 V / VPOR-down 2.69226 V equal the record).

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
(70 us at 100 V/s) at VDD=1.82 V, 0.8 V below VPOR-up. This is an early-assertion
glitch of POR_RAW, not an assertion-threshold/plateau collision. No design change was
made for it; it remains open (see PR).
