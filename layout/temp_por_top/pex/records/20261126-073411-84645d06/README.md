# Supply-relative RESETn release, issue #521

The ramp bench grades release at 0.8 × the corner's final supply. An earlier
revision of this record derived that threshold inside the circuit with an
`ETH VTH 0 VSETN 0 0.8` source. Review showed the extra element changes the
nominal extracted waveform (first rise through 2.640 V moved from 16.6871 ms to
1.61536 ms), so that revision is withdrawn and its waveform samples and batch
comparison are removed from this record.

The bench is now **the unmodified post-#501 circuit** (`pextb/tb-ramp.spice`
carries no threshold element). The threshold is a literal in each measurement
card, one literal per supply rail:

| Rail (V) | Threshold 0.8 × rail (V) | Request |
|---:|---:|---|
| 2.970 | 2.376 | [`request-ramp-2p970.json`](pextb-grid/request-ramp-2p970.json) |
| 3.300 | 2.640 | [`request-ramp-3p300.json`](pextb-grid/request-ramp-3p300.json) |
| 3.630 | 2.904 | [`request-ramp-3p630.json`](pextb-grid/request-ramp-3p630.json) |

Each request keeps the 5 process × 3 temperature corners of the original
grid, so the three requests together cover the same 45 corners. KLT uses the
same file-scope `.meas` cards for every corner in a request. Grouping by rail
lets both cards use `WHEN v(resetn)=<literal> RISE=1`. `t_release_v_ih`
reports the first rising crossing time, and `vdd_at_release` samples VDD
at that crossing.

## Local measurements

Single-corner local runs of `klt pex` (schematic and extracted legs, KLT
`0.9.3.dev5645+gdb5b0cad5338`, ngspice 47, sky130A pin
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`).

| Corner | Threshold (V) | Schematic (ms) | Extracted (ms) | VDD at release, both legs (V) | Report |
|---|---:|---:|---:|---:|---|
| tt / 3.300 V / 27 °C | 2.640 | 2.70377 | 16.6871 | 3.300 | [pilot](pilot/klt-pex.report.json) |
| sf / 2.970 V / −40 °C | 2.376 | 1.80093 | not reached in 30 ms | 2.970 (schematic) | [low-rail](low-rail/klt-pex.report.json) |
| tt / 3.630 V / 27 °C | 2.904 | 2.94380 | 27.4470 | 3.630 | [high-rail](high-rail/klt-pex.report.json) |

- **Nominal control, both legs.** The nominal request is byte-identical to the
  post-#501 bench. The extracted leg reproduces the post-#501 pilot value
  (16.6871 ms, 3.300 V) and the schematic leg reproduces 2.70377 ms.
  Nothing about the circuit differs from that pilot.
- **High-rail check.** Both legs release at 3.630 V against 2.904 V; the
  extracted leg is slow (27.4 ms, close to the 30 ms window end).

### Low-rail crossing at sf / 2.970 V / −40 °C

In an ngspice 47 replay of the generated schematic deck, these were the first
consecutive samples to bracket a rising RESETn crossing of 2.376 V.

| Time (ms) | RESETn (V) | VDD (V) |
|---:|---:|---:|
| 1.800335161 | 0.012592986 | 2.970 |
| 1.800992147 | 2.624656773 | 2.970 |

Linear interpolation gives **1.800929605 ms** and **2.970 V**, matching
`t_release_v_ih` (1.80093 ms) and `vdd_at_release` (2.970 V) at the
precision of the [low-rail report](low-rail/klt-pex.report.json).
On the same 30 ms trace, `WHEN v(resetn)=2.640 RISE=1` returned
`out of interval`. Peak RESETn was 2.63833 V.

On the extracted leg, both measurements reported `out of interval` at
2.376 V during the 30 ms transient.

## Batch status

The 45-corner grid was **not** re-submitted in this revision. The previous
attempt failed at S3 input upload (missing `batch-runner-submit` AWS profile on
the submit host), so every row errored on both sides, and its comparison table
was built from the withdrawn `ETH` bench. The physical recovery count for the
45 corners remains **unmeasured**; #521 stays open for it.

## Reproduction

Run from the repository root with the sky130A open_pdks pin above and
ngspice 47.

```bash
pex=layout/temp_por_top/pex
record="$pex/records/20261126-073411-84645d06"
scratch=$(mktemp -d)
common=(--deck sky130 --pdk sky130A --pdk-root "$HOME/.ciel"
        --top temp_por_top --pins VDD,VSS,PTAT,CTAT,RESETn
        --rename-declared-pins --flatten-schematic --format json)
export OMP_THREAD_LIMIT=1

# nominal control (both legs)
klt pex layout/temp_por_top/temp_por_top.gds "$pex/pextb/request-ramp.json" \
  "${common[@]}" --backend local -o "$scratch/pilot.pex.spice" \
  --outdir "$scratch/pilot" > "$scratch/pilot.json"

# All three rails of the grid (requires the fleet submit profile)
for rail in 2p970 3p300 3p630; do
  klt pex layout/temp_por_top/temp_por_top.gds \
    "$record/pextb-grid/request-ramp-$rail.json" "${common[@]}" --backend batch \
    --max-units-per-job 9 --wait-for-capacity 600 \
    -o "$scratch/grid-$rail.pex.spice" --outdir "$scratch/grid-$rail" \
    > "$scratch/grid-$rail.json"
done
```

The low- and high-rail rows were single corners: the nominal request with
`corners` set to `sf` / 2.97 V / −40 °C (threshold 2.376) and `tt` / 3.63 V /
27 °C (threshold 2.904), run with `--backend local`.
