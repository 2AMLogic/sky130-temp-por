# sim/temp-core-accuracy-mc -- temp_core full-signal-path mismatch Monte Carlo (issue #105)

Evidence for **DR-003 row 2 (`[TBD-1]`)**: what temperature error, in degC, does the `temp_core` PTAT readout have
under 3-sigma device mismatch, untrimmed and with a 1-point (27 C) gain trim, and which mismatch term is
responsible? The ratified spec is **not** edited; `[TBD-1]` stays open until a human takes this evidence to a
decision record. Records are append-only (`sim/README.md`).

## What is measured

`temp_core` (with the committed `bias_core` feeding `IBIAS`) is powered up from 0 V (`tran ... uic`, EN tied to VDD,
the same stimulus as `sim/temp-core-startup-solver/`) and the settled `PTAT` is read at -40/27/125 C. The temperature
error at temperature T is

    e(T) = (PTAT_sample(T) - PTAT_nominal(T)) / (dPTAT_nominal/dT at T)

with the nominal curve from the mismatch-free run of the same process corner and supply. The 1-point trim multiplies
the sample's PTAT by `PTAT_nominal(27)/PTAT_sample(27)` (an ideal gain trim, as in DR-005), so `e(27) = 0` by
construction. **3 sigma = 3 x the Bessel-corrected sample standard deviation** of e(T); max |e| and the 99.7th
percentile are reported next to it.

### Mismatch terms (per-term switches)

| variant | what is sampled | how |
|---|---|---|
| `pnp` | PNP Is/Bf (Q1 vs Q8A..H) | PDK-native (`<proc>_mm` section), every other coefficient overridden to 0 after `.lib` |
| `res` | xhigh_po body resistance (R2/R1 ratio) | PDK-native, same mechanism |
| `amp` | amplifier input-referred offset | explicit series gate source on MI1/MI2/ML1/ML2, sigma = A_VT/sqrt(W*L) |
| `mirror` | PMOS mirror ratio | explicit series gate source on MP1-3 and MPC1-3, same law |
| `combined` | the four above, jointly | native PNP+RES, explicit AMP+MIRROR |
| `all` | everything the PDK mismatches (adds bias_core, tail/startup/enable MOS, MIM cap) | fully native `<proc>_mm` |
| `nominal` | nothing | the reference transfer function (full 45-point PVT matrix) |
| `control-off`, `control-zeroed` | nothing | negative controls: sigma must be exactly 0 |

Why explicit injection for the two MOS roles: the PDK's MOS mismatch switch is global per family, so it cannot
separate the amplifier from the mirror. The PDK's own MOS mismatch is a threshold shift
`A_VT*mismatch_factor/sqrt(W*L*mult)*AGAUSS(0,1,1)` (`models_fet.spice`), electrically a series gate-voltage source;
the runner inserts exactly that in a copy of the committed `temp_core` text (0 V when off) and asserts `A_VT` against
the installed `models_global.spice`. The `combined` vs `all` and `combined` vs quadrature-sum comparisons in each
record cross-check the injection against the native mechanism.

Coverage: the four single terms + `combined` + `all` at tt, 3.30 V (N = 100 per temperature); `all` additionally at
ss/ff/sf/fs (3.30 V) and tt at 2.97/3.63 V (N = 50), every point at -40/27/125 C. Base seed 20261011, `vary=mismatch`.
`experiment.json` records the full matrix and conventions.

### Operating-point guard and invalid samples

Solver landing on a non-physical branch is a known hazard of this cell (`sim/temp-core-startup-solver/records/20261010-200708-47b96e5`,
issue #86: partial sweep, six historical FAILs not reproduced, 4 of 10 combos NOT-RUN, yet every variant still produced
1-5 non-physical landings per 45 points). So a sample is valid only if its readings sit inside the unrelaxed startup
windows and have settled; invalid samples are **excluded and counted** per group/temperature/reason, never replaced.
The PNP-pair-only prior is `sim/pnp-mismatch/records/20260825-220116-a9cac4b`.

### Pairing across temperature

klt derives the per-sample seed from (seed, corner_index, sample_index). One request per temperature therefore gives
the same draws at all three temperatures, which the 1-point trim needs. The record prints the cross-temperature
correlation of the per-sample deviation as the check (about 1 = paired).

## Execution rule

Every Monte Carlo request runs on the Spot batch fleet: `klt sim ... --backend batch` (`KLT_SIM_BACKEND=batch` on the
dispatch hosts). The runner never launches ngspice over a grid and never falls back to a local grid; a refused or
failed request is recorded as NOT-RUN with klt's error. `probe` runs one local single-corner single-sample point for
debugging only.

## Cold start

```bash
export PDK_ROOT=~/.volare             # sky130A pinned in sim/pdk.json; klt >= 0.7 on PATH
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py probe amp tt 27 3.3        # one local debug point
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py run --run-id r1            # submit all requests to the fleet (resumable: --resume)
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py record --run-id r1         # needs a clean tree; writes records/<id>.{json,md}
```

Raw outputs go to `sim/build/temp-core-accuracy-mc/<run-id>/` (git-ignored); the record keeps compact per-request
digests under `corners/<id>/` and the rendered decks under `netlist-snapshots/<id>/`. A record is refused on a dirty
tree and an existing record id is never overwritten; a correction is a new record with `--supersedes <id>`.

## Layout

- `run_accuracy_mc.py` -- runner (`run | probe | record`), `experiment.json` -- manifest
- `testbench/tb_temp_core_accuracy.spice` -- deck template (header explains the term switches)
- `records/`, `corners/`, `netlist-snapshots/` -- evidence (append-only)
