# por-bias-ok-early-assert (issue #495)

Deterministic reproduction of the early `BIAS_OK` assertion / `POR_RAW` release-then-reassert
pulse first seen on one ss/-40 C mismatch draw (PR #491, `replay-474`). A forced DC offset
behind the gate of one OK-detector device (`XMOL2` or `XMOKA`) in a **derived** copy of
`design/netlist/bias_core.spice` replaces the mismatch seed, so the behaviour no longer depends
on solver state. `design/` and `spec/` are untouched.

- Testbench: `testbench/tb_bias_ok_early_assert.sch` (real `bias_core` + `por_comparator` + `por_output_chain` on a shared IBIAS node; quasi-static VDD up/down sweep)
- Runner: `run_early_assert.py` (one `klt sim` deck-list request to the batch fleet; `--probe ID` runs one point locally). Extractor: `pulse_extractor.py` (+ `test_pulse_extractor.py`)
- Manifest: `experiment.json` (grids, offset injection, result classes)
- Records: `records/` (append-only). Raw waveforms/logs live in the artifact store (`manifests/artifacts/`).

```bash
export PATH=$HOME/.local/bin:$PATH PDK_ROOT=$HOME/.ciel
python3 sim/por-bias-ok-early-assert/run_early_assert.py --grid full --wait-for-capacity 600
python3 sim/por-bias-ok-early-assert/run_early_assert.py --probe ss_m40c_r100_default_xmoka_offm060   # one local point
```

## Result (full record `20261123-220630-e2525b25-full`)

See `docs/characterization-report.md` E17. In short: the pulse is deterministic; at 100 V/s it needs a
detector offset of about -30 to -36 mV (XMOKA) or -36 to -60 mV (XMOL2) at ss/-40 C, outside the +-9 mV
(3 sigma) box; its width is ~16-96 mV of VDD on the XMOKA pulse points (duration ~ 1/rate); RESETn never released inside any pulse
window (verdict b). Caveats (single device at a time, 1.0 V extractor floor at ff/125 C, absorption
measured outside E16's VDD range) are listed with the record.
