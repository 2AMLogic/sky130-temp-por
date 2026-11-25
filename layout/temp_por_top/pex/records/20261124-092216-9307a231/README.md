# `temp_por_top` block-level pex re-run after the net-label case fix -- issue #501

**New appended evidence.** The recorded `status: error` pilot one directory up
(`../klt-pex.report.json`, `../temp_por_top.pex.spice`, PR #477 / #454 T1 item 7)
is untouched; this record is the re-run after the repo-side fix #501 makes the
composed siblings' net labels case-consistent (the `bias_core` family's
lowercase `n1 n2 na nb nbg nt nz pb pg` labels upper-cased to match their own
reference netlists, `temp_core`'s stage-0 `na` pin label likewise). Same
stimulus, same pins, same deck, same klt build (`0.9.2`, `046ba74652fc`, the
`layout/pdk.json` pin).

| file | what |
|---|---|
| `klt-pex.report.json` | single-corner pilot (tt / 27 C / 3.30 V, backend `local`) -- **`status: pass`**: both schematic legs and both extracted legs ran and produced values. The extracted netlist loads in ngspice; the `device already exists` failure is gone |
| `temp_por_top.pex.spice` | the pilot's extraction (154 devices, 71 nets, 570 R + 202 C parasitic cards, `.SUBCKT temp_por_top VDD VSS PTAT CTAT RESETn`) |
| `pextb-grid/` | the 5x3x3 fleet requests + testbenches (stimulus copied verbatim from `../pextb/`; corners widened to process `tt,ss,ff,sf,fs` x supply `2.97,3.3,3.63` V x temp `-40,27,125` C = 45 corners; `backend: batch`; the tb copies' relative `.include` of `design/netlist/temp_por_top.spice` adjusted for this directory's depth, nothing else) |
| `grid/klt-pex.report.json` | the 5x3x3 fleet run -- `status: error` at the report level: **84/135 delta rows pass, 51 error** (taxonomy below). Submitted `--backend batch --max-units-per-job 9 --wait-for-capacity 600`; 20 fleet jobs (`klt-sim-021375bf74bf ... klt-sim-f69593744ef8`, full list in the report's per-side `environment.remote`) |
| `grid/temp_por_top.pex.spice` | the grid run's own extraction copy (same GDS, byte-identical role) |
| `grid/artifacts/` | per-corner `corner.cir` + `ngspice.log` for both sides, both testbenches |

## Pilot result (tt / 27 C / 3.30 V, local)

Wall time **20.7 s** for the whole run (extract + 4 sims) -- the run-time datum
the #477 record could not measure. Values:

| measurement | schematic | extracted |
|---|---|---|
| `t_release_v_ih` | 2.704 ms | **16.69 ms** |
| `vdd_at_release` | 3.300 V | 3.300 V |
| `iq_por_settled` | -79.42 uA | -111.0 uA |

The extracted release is ~6x later than schematic at this corner (the report's
own delta tolerance grades it `pass`; the shift is consistent with parasitic
series R on the `PG`/`NZ` one-shot timer nets plus coupling C). Recorded as
measured; no bound is proposed here.

## Grid result (5x3x3, fleet)

- `iq_por_settled`: **36/45 pass**
- `t_release_v_ih` + `vdd_at_release`: **24/45 pass** (the two rows share the
  crossing, so they error together)
- Error taxonomy (51 rows):
  - 18x extracted `t_release_v_ih` produced no value (`out of interval`) -- no
    2.64 V RESETn rising crossing within the 30 ms window on the extracted leg,
    the same late-release behavior the pilot's 16.7 ms point sits at the edge of;
  - 2x schematic-side no value (the `ss` ramp corners, whose schematic legs also
    never release in window -- visible in the report as the 18 skipped
    `unavailable_comparison` rows);
  - 25x extracted `singular_matrix` warning at `xdut.ptat_trim__t0`, 3x at
    `xdut.nz$1`, 3x at `xdut.sns` (ngspice singular-matrix warnings on the
    extracted side at the affected corners).

Nothing here is graded; roadmap item 7 stays `unmet` until #454's signoff has a
passing block-level report. The `singular_matrix` and no-release findings are
new measured input for that campaign, not spec positions.

## Disclosure (carried from the #477 record; re-verified on this run)

- **`body_bias.status`: `biased`** -- 0 unbiased devices, 0 unbiased nets
  (verbatim in both reports).
- **`extraction.model`**: unchanged lumped-RC model text, quoted verbatim in
  both reports.
- **`model_mismatch`** (unchanged from #477, tracked in #467): the 61 n + 52 p
  5 V MOS still extract as `sky130_fd_pr__{n,p}fet_01v8` against the design's
  `..._g5v0d10v5` (missing `hvi` marker); `cap_mim_m3_1` counts 8 extracted vs
  5 reference cards (unit-vs-card counting of the MF=4 timer cap).
- The nine former case pairs are gone: `extract.json` carries no
  "differ only by case" warning anywhere under `layout/`, and the flat pex
  netlist has **zero** case-folded duplicate card names (checked over all 926
  cards). Distinct same-named nets from different siblings now disambiguate the
  way `temp_core`/`por_comparator` already did before the fix (`N1` vs `N1$1`,
  card prefix `..._dup1_...`), which ngspice loads.

## Layout-side re-verification (this record's cause, #501 AC)

`klt lvs` matches and DRC stays clean at every re-rendered level, with the
counts unchanged from before the rename: leaves `bias_core_mirror_amp` 15/15
devices 13/13 nets, `bias_core_passives` 6/6 11/11, `bias_core_settle_flag`
11/11 11/11, `bias_core_startup` 9/9 10/10, `bias_core_xq1_xqr` 2/2 3/3, then
`bias_core` 51/51 27/27, `temp_core` 48/48 24/24, and `temp_por_top` **154/154
devices, 71/71 nets** (the current post-#473 counts; the #477 record's 153
describes the superseded stream), declared pin order
`VDD VSS PTAT CTAT RESETn` unchanged. The intended same-net case-fold label
joins (`VDD|vdd`, `VSS|vss`, `VREF|vref`, `IBIAS|ibias`, `BIAS_OK|bias_ok`)
are untouched and behave as before.

Block ERC was re-run against the new stream and stays `erc_status: clean`
(0 findings) with one spec change: `erc-supply-spec.json`'s `nets[]` entry
for `NT` now declares `"islands": 2` — the upper-case rename makes the label
`NT` legitimately name two distinct nets at the top (temp_core's XMI1/XMI2
source-tie net and bias_core's mirror-amp NT), the upstream-sanctioned
declaration for a label naming N nets (klt erc's `nets[].islands`, issue
#2400). Falsifiability probed on scratch copies: undeclared (implicit 1)
and `"islands": 3` both return the `erc.unconnected_net` NT finding;
`"islands": 2` is clean. Every re-rendered cell also rebuilds byte-for-byte
(`compose-cell.py --check`).

## Reproduce

Pilot (as recorded above):

    uvx --from "klayout-tools==0.9.2" klt pex \
      layout/temp_por_top/temp_por_top.gds \
      layout/temp_por_top/pex/records/20261124-092216-9307a231/../pextb/request-ramp.json \
      layout/temp_por_top/pex/records/20261124-092216-9307a231/../pextb/request-iq-por.json \
      --deck sky130 --pdk sky130A --pdk-root ~/.ciel \
      --top temp_por_top --pins VDD,VSS,PTAT,CTAT,RESETn \
      --rename-declared-pins --flatten-schematic \
      -o <out>.pex.spice --outdir <scratch> --backend local --format json

Grid: same command shape with this record's `pextb-grid/` requests and
`--backend batch --max-units-per-job 9 --wait-for-capacity 600`.

## Correction (2026-11-25)

Appended, not an edit: the "Error taxonomy" above miscounts. Re-derived with `jq`
from `grid/klt-pex.report.json` (51 error rows in total, unchanged):

- Extracted `t_release_v_ih` `out of interval` is **12** corners (24 rows), not 18.
  18 is the number of corners with an extracted-side `singular_matrix`.
- `singular_matrix` diagnostics are 21x `xdut.ptat_trim__t0` (not 25), 3x
  `xdut.nz$1`, 3x `xdut.sns` on the extracted side (27, not 31), plus 6x
  `xdut.x.xtemp.xr2.t2` on the schematic side.
- The schematic-side ramp error is at `sf/2.970V/-40C`, not an `ss` corner.
- `unavailable_comparison` appears on all 51 error rows, not 18.
- Omitted above: all 9 `ss` corners abort the transient (`timestep_too_small`,
  `nonconvergence`, `analysis_aborted`) on both testbenches, 27 of the 51 rows;
  the #153 signature.
