# Per-rail release thresholds over the 45-corner PEX ramp grid -- issue #521

**New appended evidence.** Nothing in
[`../20261126-073411-84645d06/`](../20261126-073411-84645d06/README.md) (the
per-rail requests and the single-corner checks) or in
[`../20261124-092216-9307a231/`](../20261124-092216-9307a231/README.md) (the
2.64 V baseline grid) is edited. This record is the batch-fleet run of the three
merged per-rail requests, run `20261126-122246-6640c3df` (2026-11-26
12:22:46-12:30:47 UTC), and its comparison with the baseline ramp rows.

**Measured result: 0 of the 24 baseline group-A rows recover, and none of the
48 baseline pass rows regresses.** The schematic leg now produces a value on
all 24 group-A rows, including the two rows of `sf/2.970V/-40C` that missed the
2.64 V crossing in the baseline. The extracted leg still produces no value on
all 24, so every row keeps delta status `error`.

| file | what |
|---|---|
| [`grid-2p970/klt-pex.report.json`](grid-2p970/klt-pex.report.json) | the fleet report of the 2.970 V rail (15 corners x 2 measurements, threshold 2.376 V): `status: error`, 16 pass, 14 error |
| [`grid-3p300/klt-pex.report.json`](grid-3p300/klt-pex.report.json) | the 3.300 V rail (threshold 2.640 V): `status: error`, 14 pass, 16 error |
| [`grid-3p630/klt-pex.report.json`](grid-3p630/klt-pex.report.json) | the 3.630 V rail (threshold 2.904 V): `status: error`, 18 pass, 12 error |
| [`comparison/compare_ramp_grid.py`](comparison/compare_ramp_grid.py) | derives the three files below from the committed reports and the baseline; `--check` re-derives them and byte-compares with the committed files, `--selftest` runs synthetic reports |
| [`comparison/group-a-recovery.tsv`](comparison/group-a-recovery.tsv) | the 24 group-A rows by corner and measurement: baseline and new delta status, both leg statuses, the new values, the new leg diagnostics |
| [`comparison/ramp-grid-comparison.tsv`](comparison/ramp-grid-comparison.tsv) | all 90 ramp rows (45 corners x 2 measurements) with baseline group, both runs' statuses and values, and a `change` column |
| [`comparison/summary.json`](comparison/summary.json) | the counts quoted below |

## Run

The reproduction loop of
[`../20261126-073411-84645d06/README.md`](../20261126-073411-84645d06/README.md#reproduction),
unchanged, from a fleet submit host (loom-crew-7) that carries the
`batch-runner-submit` AWS profile: `klt pex ... --backend batch
--max-units-per-job 9 --wait-for-capacity 600` once per rail, in the order
2.970, 3.300, 3.630 V, each with its own `-o` and `--outdir`. No capacity
refusal occurred. Client `klt 0.9.3.dev5655+g31430c389781`.

| Rail (V) | Threshold (V) | Request | Schematic-leg jobs | Extracted-leg jobs |
|---:|---:|---|---|---|
| 2.970 | 2.376 | [`request-ramp-2p970.json`](../20261126-073411-84645d06/pextb-grid/request-ramp-2p970.json) | `klt-sim-754aa92deba0`, `klt-sim-1344e775267b` | `klt-sim-9f95f710de2c`, `klt-sim-c6a366d607ea` |
| 3.300 | 2.640 | [`request-ramp-3p300.json`](../20261126-073411-84645d06/pextb-grid/request-ramp-3p300.json) | `klt-sim-eb3de377f771`, `klt-sim-2a9d9bac34b0` | `klt-sim-915c63d0fa20`, `klt-sim-a53c45c0015c` |
| 3.630 | 2.904 | [`request-ramp-3p630.json`](../20261126-073411-84645d06/pextb-grid/request-ramp-3p630.json) | `klt-sim-d079c27714dd`, `klt-sim-d927fb569ffc` | `klt-sim-96a85048763a`, `klt-sim-a43b94e9e3c7` |

Each side's 15 units were split into two balanced jobs of 8 and 7. The six
schematic-leg jobs ended `done` (exit 0). The six extracted-leg jobs ended
`failed` with exit 4, which is the verdict exit code for units that errored:
each extracted-leg job's `exit_reason` states it is "not a runner crash and
not the whole-job ceiling", and all 12 jobs were collected. All 12 ran on
the fleet's `sim` image profile on Spot instances of `c7i.4xlarge`,
`m6i.4xlarge` or `m7i.4xlarge`.

Checks on the three reports. `compare_ramp_grid.py` performs the first three
and exits 1, writing nothing, if any fails:

- `backend_failure` is null and `unfinished` is empty in all three; each
  side's `fleet[]` agrees with its `job_ids`.
- Each report holds one rail only, 15 distinct process/temperature
  combinations and 30 rows. Across the three, the 90 (corner, measurement)
  pairs are unique and equal the baseline's ramp key set.
- Each report's `request_sha256` equals the sha256 of its committed request
  above.
- Checked on the run's scratch decks: the rail's literal is in both `.meas`
  cards of all 30 corner decks per rail (`v(resetn)=2.376`, `2.64`, `2.904`).

## Group A: 0 of 24 rows recover

All 24 rows listed as group A in
[`diagnosis-454/error-rows.tsv`](../20261124-092216-9307a231/diagnosis-454/error-rows.tsv)
were matched by corner and measurement. 0 now have delta status `pass`.

| Corner | Rail (V) | Threshold (V) | Baseline schematic / extracted | New schematic | New extracted |
|---|---:|---:|---|---|---|
| `tt/2.970V/-40C` | 2.970 | 2.376 | pass / error | pass, 2.48718 ms, 2.970 V | error |
| `sf/2.970V/-40C` | 2.970 | 2.376 | error / error | pass, 1.80093 ms, 2.970 V | error |
| `fs/2.970V/27C` | 2.970 | 2.376 | pass / error | pass, 3.35770 ms, 2.970 V | error |
| `fs/2.970V/125C` | 2.970 | 2.376 | pass / error | pass, 3.22872 ms, 2.970 V | error |
| `tt/3.300V/-40C` | 3.300 | 2.640 | pass / error | pass, 2.75744 ms, 3.300 V | error |
| `ff/3.300V/27C` | 3.300 | 2.640 | pass / error | pass, 2.56066 ms, 3.300 V | error |
| `ff/3.300V/125C` | 3.300 | 2.640 | pass / error | pass, 2.61544 ms, 3.300 V | error |
| `fs/3.300V/27C` | 3.300 | 2.640 | pass / error | pass, 3.68529 ms, 3.300 V | error |
| `fs/3.300V/125C` | 3.300 | 2.640 | pass / error | pass, 3.52731 ms, 3.300 V | error |
| `sf/3.630V/27C` | 3.630 | 2.904 | pass / error | pass, 2.25169 ms, 3.630 V | error |
| `fs/3.630V/-40C` | 3.630 | 2.904 | pass / error | pass, 4.30692 ms, 3.630 V | error |
| `fs/3.630V/27C` | 3.630 | 2.904 | pass / error | pass, 4.00776 ms, 3.630 V | error |

Per row, the time is `t_release_v_ih` and the voltage is `vdd_at_release`;
[`group-a-recovery.tsv`](comparison/group-a-recovery.tsv) has them as separate
rows. Statuses of the 24 remaining non-pass rows:

- **Schematic leg: `pass` on 24 of 24.** One leg recovered, the schematic leg
  at `sf/2.970V/-40C` (2 rows): 1.80093 ms at 2.970 V against 2.376 V, the
  value the single-corner check of the previous record measured, where the
  2.64 V literal missed a 2.63833 V high level.
- **Extracted leg: `error` on 24 of 24**, all with `delta[].error.code =
  measurement` and the message "produced no value -- ngspice reported: out of
  interval": no rising crossing of 0.8 x rail on RESETn within the 30 ms
  window. The leg's diagnostics are `measurement` x2 on 20 rows, and
  `singular_matrix` + `measurement` x2 on the 4 rows of `ff/3.300V/27C` and
  `fs/3.630V/-40C`, the same two corners the baseline noted. No leg regressed.

## Rest of the ramp grid: 0 regressions

- Of the 48 baseline pass rows, **0 now fail or error**; every one keeps both
  legs and delta status `pass`.
- The 18 group-B rows (the nine `ss` corners, baseline extracted-side abort)
  still error on the extracted side with the same diagnostics
  (`singular_matrix`, `timestep_too_small`, `nonconvergence`, `measurement` x2,
  `analysis_aborted`). Their schematic legs pass.
- Whole grid, 90 rows: baseline 48 pass / 42 error, new 48 pass / 42 error,
  `change` = `unchanged` on all 90. Per leg over the 45 corners: schematic 44
  pass / 1 error before, 45 / 0 now; extracted 24 pass / 21 error before and
  now.
- The three single-corner values of the previous record are reproduced by the
  fleet run: `tt/3.300V/27C` 2.70377 ms schematic, 16.6871 ms extracted, 3.300
  V; `sf/2.970V/-40C` schematic 1.80093 ms, 2.970 V, extracted no value;
  `tt/3.630V/27C` 2.94380 ms schematic, 27.4470 ms extracted, 3.630 V.

## What the threshold change moved

Among the 48 rows that pass in both runs (96 leg values), each leg's new value
compares with its baseline value as follows:

| Rail (V) | Rows pass in both runs | Identical leg values | New value lower | New value higher |
|---:|---:|---:|---:|---:|
| 2.970 | 16 | 16 | 16 | 0 |
| 3.300 | 14 | 28 | 0 | 0 |
| 3.630 | 18 | 18 | 0 | 18 |

Every `vdd_at_release` leg is identical to its baseline value on every rail
(the supply has finished ramping long before release, so it reads the final
supply). Every `t_release_v_ih` leg is identical on the 3.300 V rail, where
the literal did not change, lower on the 2.970 V rail, where the literal
dropped from 2.64 V to 2.376 V, and higher on the 3.630 V rail, where it rose
to 2.904 V. The largest shift among them is 0.04 % of the crossing time
(`tt/2.970V/27C`, schematic leg, 2.46432 ms to 2.46334 ms). This is consistent
with the same rising edge being sampled at a different level; no status
changes.

## Disclosure

- **Same circuit as the baseline.** All three reports and the baseline report
  carry the same `extraction.netlist_sha256`
  (`27086204bda4…`, the hash of the baseline's committed
  [`grid/temp_por_top.pex.spice`](../20261124-092216-9307a231/grid/temp_por_top.pex.spice)),
  the same `schematic_flatten.netlist_sha256` (`c2e8f53d755f…`), the same
  `reference_netlist_sha256` and the same layout `input.content_hash`. The
  only inputs that differ are the `.meas` literals and the per-rail grouping.
- **Extraction:** 154 devices, 71 nets, the same lumped-RC model text;
  `body_bias.status: biased`, 0 unbiased devices, 0 unbiased nets, 0 unbiased
  PMOS body nets.
- **`model_mismatch`, unchanged and still tracked in [#467](https://github.com/2AMLogic/sky130-temp-por/issues/467):**
  the 5 V MOS still extract as `sky130_fd_pr__{n,p}fet_01v8` against the
  design's `..._g5v0d10v5`.
- **Fleet side unchanged from the baseline:** all 12 jobs ran on the same
  image (`ami-09c14f55df4958cbd`) as the baseline's 20, with runner `klt
  0.9.0` (`runner_compatibility: match`), ngspice 47 and PDK stamp
  `open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (`match`).
- **Client side differs from the baseline:** client `klt
  0.9.3.dev5655+g31430c389781` with KLayout 0.30.13, against the baseline's
  `0.9.2` (`046ba74652fc`, the `layout/pdk.json` pin) with 0.30.14. The
  curated `sky130` deck of the newer build hashes differently
  (`16f864ebc7de…` against `36027b82e3b1…`) and still yields the identical
  extracted netlist. `layout/pdk.json` is not touched: its pin describes the
  DRC/LVS evidence, which was not regenerated here.
- A `singular_matrix` warning on the schematic side at
  `xdut.x.xtemp.xr2.t2`, on the three `tt/.../-40C` corners, appears in both
  runs; the legs pass.

## Not committed

The per-corner decks, `ngspice.log` files, batch receipts and the per-rail
extraction copies stayed in the run's scratch directory. The repo keeps raw
run bytes out of git, and the extraction copies are byte-identical to the
baseline's committed one. The reports hold each job's id, state, instance
type, timestamps and per-unit outcome, and each corner's status and
diagnostics.

## Reproduce

The fleet loop is the one under "Reproduction" of
[`../20261126-073411-84645d06/README.md`](../20261126-073411-84645d06/README.md#reproduction).
The comparison needs no fleet access:

```bash
cd <repo root>
c=layout/temp_por_top/pex/records/20261126-122246-6640c3df/comparison/compare_ramp_grid.py
python3 -I $c --check      # re-derive the tables and byte-compare with the committed files
python3 -I $c --selftest   # synthetic reports
python3 -I $c              # re-write the three comparison files beside the script
```

## Scope

No DUT, harness, spec row, solver setting, window or tolerance was changed.
Why the extracted leg produces no crossing at the 12 group-A corners, and why
it aborts at the nine `ss` corners, remains open in
[#454](https://github.com/2AMLogic/sky130-temp-por/issues/454). Nothing here
is graded, and roadmap item 7 stays `unmet` until #454's signoff has a passing
block-level report.
