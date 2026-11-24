# `temp_por_top` block-level post-layout (parasitic extraction) evidence -- issue #454, T1 item 7

**Block-level `klt pex` evidence, currently `status: error`: the extracted leg
cannot start.** The cause is measured, single and upstream:
[klayout-tools#7091](https://github.com/2AMLogic/klayout-tools/issues/7091)
(net labels differing only by case -> duplicate parasitic card names +
case-folded node shorts; closed upstream as a clean refusal, not a rename, so the
forward path is repo-side, #501). Per #454's step 6, the report is committed as it is,
the cause is linked, and the issue stays open. No spec or harness window was
relaxed; nothing here edits existing records.

> **Staleness note (#473, PR #488).** This record predates the #473 re-render
> of `temp_por_top.gds`. It extracted the superseded stream
> `sha256:746e20de…` (153 devices, 71 nets, pre-`XMOKH`); the current
> `../temp_por_top.gds` is `sha256:5eb5432a…` and `klt lvs` now matches
> 154/154 devices and 71/71 nets. The 153-device counts below describe the old
> stream, not the current tree. PEX was **not** re-run for #473: the record is
> already `status: error` from klayout-tools#7091, the repo-side fix is #501,
> and item 7 belongs to #454.

## What is here

| file | what |
|---|---|
| `temp_por_top.pex.spice` | the raw `klt pex` extraction of `../temp_por_top.gds` (153 devices, 71 nets, 566 R + 210 C parasitic cards), verbatim |
| `klt-pex.report.json` | the `klt pex` report -- **status `error`**: both schematic legs `pass`, both extracted legs `error` (`ngspice_fatal`, `analysis_started: false`), 3/3 delta rows `error` |
| `pextb/` | the two `klt sim` testbench requests + netlists (the spec suite, below) |

## The spec suite (whole-block testbenches, per #454 step 3)

Both requests re-use the existing whole-block campaigns' stimulus exactly:
physical 0 V start, `V(VDD) = min(3.30, rate*t)` at rate 10000 V/s (the
`sim/iq-top` rate), held to tstop 30 ms, `.options method=gear trtol=50`,
`set ng_nomodcheck` carried in the netlist (the fleet runner ignores
`options.ngspice_init`). Measurements reference **top-level nodes only**
(VDD, RESETn, i(BVDD)) because the extracted leg is flat -- DUT-internal nets
(POR_RAW, IBIAS, ...) do not exist there.

- `request-ramp.json` / `tb-ramp.spice` -- the supply-ramp **release
  measurement** (`sim/supply-ramp-top`): first rising V_IH = 0.8*vf crossing
  of RESETn (the campaign's release definition; 3.30 V -> 2.64 V literal).
  Rows: `t_release_v_ih`, `vdd_at_release`.
- `request-iq-por.json` / `tb-iq-por.spice` -- **Iq** (`sim/iq-top`), in the
  `por-iq` state (RESETn forced low by a 0 V `VRST`, disabling `temp_core`):
  trailing-window mean of i(BVDD) over [25, 30] ms, the same window
  `sim/iq-top` grades. The por-iq state is the Iq spec row because the
  `sim/iq-top` record graded it `ok` at 45/45 corners, while the natural
  released state (iq-total) hits the known non-physical `temp_core` branch at
  17/45 points **including tt/27C/3.30V**
  (`sim/iq-top/records/20261009-191705-df85523.md`).

## Result (pilot: one tt / 27 C / 3.30 V point, local backend)

Per #454: one point first, to learn the run time before any grid. klt `0.9.2`
(`046ba74652fc`, the `layout/pdk.json` pin, via `uvx --from
"klayout-tools==0.9.2"`), `--pdk-root ~/.ciel` (open_pdks `f6eeac7dad08...`),
`--pins VDD,VSS,PTAT,CTAT,RESETn --rename-declared-pins --flatten-schematic`,
backend `local`, single corner. **No grid was run, locally or on the fleet.**

- Extraction: 1.8 s, `status: extracted`, 153 devices / 71 nets (the same
  counts `klt lvs` matched 153/153 and 71/71 for that stream, before the #473 re-render), `.SUBCKT temp_por_top VDD VSS
  PTAT CTAT RESETn` in the declared order, so the positional `XDUT` is wired
  correctly (the #3269 pin-order fix holds at the block level too).
- Schematic legs (both testbenches): `pass` within a 22 s total wall time for
  the whole run. Values: `t_release_v_ih` 2.71265 ms, `vdd_at_release`
  3.30000 V (censored by construction at this rate: the ramp ends at 0.33 ms
  and release is one-shot-delay-dominated, so VDD is already at its final
  value -- the campaign's r10000 records show the same), `iq_por_settled`
  -79.443 uA (i(BVDD) sign; = 79.443 uA supply current, inside the
  `sim/iq-top` por-iq table's 50.8..120.3 uA band).
- Extracted legs (both testbenches): `error` before any analysis started --
  see the blocker. The extracted-netlist **simulation** run time is therefore
  **unmeasured**; what the pilot establishes is that no grid is worth
  submitting until the repo-side net-label fix (#501) lands (every fleet point would reproduce the same
  load failure).

## Blocker: case-colliding net names (single cause, upstream)

The flat parasitic extraction keeps the composed sibling cells' internal nets
distinct (71 nets, LVS-matched) but names them from their layout labels, and
one leaf's labels are uppercase while a sibling's are lowercase. Nine net
pairs differ only by case (`N1/n1`, `N2/n2`, `NA/na`, `NB/nb`, `NBG/nbg`,
`NT/nt`, `NZ/nz`, `PB/pb`, `PG/pg`), which yields 53 case-colliding parasitic
card names. ngspice folds case, so the extracted netlist dies at load:

```
Error on line 1542 or its substitute:
  r.xdut.rn1_t0 xdut.n1__t0 xdut.n1 2337.15353461
device already exists, bail out
```

(first duplicate: `RN1_t0 ... N1` vs `Rn1_t0 ... n1`). Even with unique card
names, the two nets' nodes would fold to one node -- an electrical short --
so the netlist is unsimulatable as generated, in a way no `klt pex` flag at
0.9.2 avoids (`--tie-net` maps body nets; `--rename-declared-pins` covers only
the declared pin set; `--critical-net`/`--distributed-rc` keep net-derived
names). Filed as
[klayout-tools#7091](https://github.com/2AMLogic/klayout-tools/issues/7091)
(searched first: #5494 is multi-top, #5894 lumped net R, #4200 the closed
same-named-net *merge* -- none covers the case-collision of distinct nets).
Device-only extraction is unaffected (unique `$n` device names), which is why
`klt lvs` on the same stream passes.

## Disclosure (per #454 step 4)

- **`body_bias.status`: `biased`** -- 0 unbiased devices, 0 unbiased nets, 0
  unbiased PMOS body nets (verbatim in `klt-pex.report.json`).
- **`extraction.model`**: the same lumped-RC text as the `por_comparator` runs
  -- single lumped series R per net in a star over the net's device terminals,
  net-to-ground C from area/perimeter, vertical-overlap net-to-net C
  unconditionally, lateral same-layer coupling only for declared
  `--critical-net` pairs (none declared), quasi-static; no distributed RC, no
  fringe shielding, no inductance. Quoted verbatim in the report's
  `extraction.model`.
- **`model_mismatch`** (disclosed, not a grading blocker): the 61 n + 52 p
  5 V MOS extract as `sky130_fd_pr__{n,p}fet_01v8` against the design's
  `..._g5v0d10v5` -- the streams' missing `hvi` marker, whose re-render is
  tracked in [#467](https://github.com/2AMLogic/sky130-temp-por/issues/467)
  (klt release carrying klayout-tools#6185). Matched: `nfet_05v0_nvt` 1/1
  (XMASSIST), `pnp_05v5` 19/19, `res_xhigh_po` 12/12; `cap_mim_m3_1` counts
  8 extracted vs 5 reference cards (unit-vs-card counting of the MF=4 timer
  cap; both sides instantiate the same model).
- **Fleet**: nothing was submitted (nothing to dispatch -- see above), so
  there are no fleet job ids to record for this report. Once the net labels are
  case-consistent (#501) and the extracted leg loads, the 5x3x3 grid goes through the batch fleet with `--wait-for-capacity 600`
  (`klt pex` 0.9.2 speaks the fleet protocol: `--backend batch`,
  `--max-units-per-job`, `--submit-only`/`--attach`), never as a local grid.

## Reproduce

    uvx --from "klayout-tools==0.9.2" klt pex \
      layout/temp_por_top/temp_por_top.gds \
      layout/temp_por_top/pex/pextb/request-ramp.json \
      layout/temp_por_top/pex/pextb/request-iq-por.json \
      --deck sky130 --pdk sky130A --pdk-root ~/.ciel \
      --top temp_por_top --pins VDD,VSS,PTAT,CTAT,RESETn \
      --rename-declared-pins --flatten-schematic \
      -o layout/temp_por_top/pex/temp_por_top.pex.spice \
      --outdir <scratch> --backend local --format json \
      > layout/temp_por_top/pex/klt-pex.report.json

Exit code 4 (`status: error`) is the recorded outcome until the repo-side net-label fix (#501) lands; #7091 itself is closed upstream as a clean refusal, not a rename.
