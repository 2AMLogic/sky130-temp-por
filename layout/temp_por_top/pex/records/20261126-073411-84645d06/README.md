# Supply-relative RESETn release, issue #521

The ramp bench uses an ideal voltage-controlled voltage source to set
VTH to 0.8 × VSETN throughout the transient. In the generated schematic
and extracted decks, both cards use `WHEN v(resetn)=v(vth) RISE=1`.
The second card uses `FIND v(vdd)` at the same crossing.

## Local measurements

| Corner | Leg | VTH (V) | First crossing (ms) | VDD at crossing (V) | Same-waveform 2.640 V control (ms) |
|---|---|---:|---:|---:|---:|
| sf / 2.970 V / −40 °C | schematic | 2.376 | 1.80028 | 2.970 | out of interval |
| tt / 3.300 V / 27 °C | schematic | 2.640 | 2.70377 | 3.300 | 2.70377 |
| tt / 3.300 V / 27 °C | extracted | 2.640 | 1.61536 | 3.300 | 1.61536 |
| tt / 3.630 V / 27 °C | schematic | 2.904 | 2.94380 | 3.630 | 2.94300 |

At the low rail, the first samples bracketing 2.376 V interpolate to
1.800281692 ms and 2.970 V. The literal 2.376 V card and the derived card
both report 1.80028 ms. RESETn peaks at 2.63830 V within the 30 ms run.
At the high rail, the literal 2.904 V and derived cards also agree.
The samples include the points immediately before and after each bracket.
[Waveform samples](crossing-samples.tsv) · [Low-rail ngspice output](low-rail-measurements.txt)

The nominal schematic reproduces the post-#501 pilot at its recorded precision.
The nominal extracted result **changed from 16.6871 to 1.61536 ms**. A replay
of the original bench on this host reproduced 16.6871 ms. On the revised
extracted waveform, the two cards agree on 1.61536 ms and 3.300 V. The shift
arises between bench runs, even though both use the same nominal threshold.
The flat schematic and extracted DUT netlists match the archived netlists
byte for byte. [Revised pilot](pilot/klt-pex.report.json) · [Post-#501 pilot](../20261124-092216-9307a231/klt-pex.report.json)

## Batch attempt

The ramp request covers 45 corners and two measurements. All ten shards
failed on their first S3 input upload because the submit host lacked the
`batch-runner-submit` AWS profile. KLT exited 4. Both sides of every row
have status `error` and no value. The count of physical recoveries and new
circuit failures is **unmeasured**.

| Post-#501 ramp rows | Matched rows | Current report |
|---|---:|---|
| Group A, missing crossing | 24 | 0 reported passes, 24 submission errors |
| Group B, aborted transient | 18 | 18 submission errors |
| Previously passing | 48 | 48 new submission errors |

The comparison joins on corner ID and measurement name, stripping the
multi-testbench baseline’s `request-ramp.` prefix. It takes group membership
from the baseline diagnosis. A completed batch run is still required for #521.
[All 90 row pairs](batch/comparison.tsv) · [Batch report](batch/klt-pex.report.json) · [Baseline groups](../20261124-092216-9307a231/diagnosis-454/error-rows.tsv)

## Reproduction

Run from the repository root with the sky130A open_pdks pin
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, ngspice 47 and KLT 0.9.2
(`046ba74652fc`). The batch command needs the fleet provision script
(`KLT_BATCH_PROVISION_SCRIPT`) and the configured submit profile.

```bash
pex=layout/temp_por_top/pex
record="$pex/records/20261126-073411-84645d06"
scratch=$(mktemp -d)
common=(--deck sky130 --pdk sky130A --pdk-root "$HOME/.ciel"
        --top temp_por_top --pins VDD,VSS,PTAT,CTAT,RESETn
        --rename-declared-pins --flatten-schematic --format json)
export OMP_THREAD_LIMIT=1

uvx --from 'klayout-tools==0.9.2' klt pex layout/temp_por_top/temp_por_top.gds \
  "$pex/pextb/request-ramp.json" "${common[@]}" --backend local \
  -o "$scratch/pilot.pex.spice" --outdir "$scratch/pilot" > "$scratch/pilot.json"

cp "$record/low-rail.cir" "$scratch/"
cp sim/spiceinit "$scratch/.spiceinit"
ln -s "$HOME/.ciel/sky130A/libs.tech/combined/sky130.lib.spice" "$scratch/sky130.lib.spice"
ln -s "$scratch/pilot/00-request-ramp.schematic-dut-testbench.spice" "$scratch/schematic-testbench.spice"
(cd "$scratch" && ngspice -b low-rail.cir)

uvx --from 'klayout-tools==0.9.2' klt pex layout/temp_por_top/temp_por_top.gds \
  "$record/pextb-grid/request-ramp.json" "${common[@]}" --backend batch \
  --max-units-per-job 9 --wait-for-capacity 600 \
  -o "$scratch/grid.pex.spice" --outdir "$scratch/grid" > "$scratch/grid.json"
```

For the nominal controls, replay the pilot's generated `corner.cir` for each
leg with its original initialization. Insert the two 2.640 V control
measurements and the `wrdata` commands from `low-rail.cir` before `quit`.
For the high-rail check, use the schematic pilot deck with `alter vset=3.63`
and add the literal 2.904 V and fixed 2.640 V cards. The low-rail check uses
the repository's `sim/spiceinit` as in the #454 single-corner reproduction.
