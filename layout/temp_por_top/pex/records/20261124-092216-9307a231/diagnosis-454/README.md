# Attribution of the 51 grid error rows -- issue #454

**New appended evidence.** Nothing in `../README.md`, `../grid/` or the pilot is
edited. This directory only reads `../grid/klt-pex.report.json` (klt `0.9.2`,
grid status `error`, 84/135 pass, 51 error) and adds two single-corner local
reproductions. No grid was run. Item 7 stays `unmet`.

| file | what |
|---|---|
| `error-rows.tsv` | all 51 error rows: group, testbench, measurement, corner, failing side, `delta[].error.code`, the side's full diagnostic code list, schematic value |
| `inputs/` | the decks of the local reproductions (`deck.cir` tt/-40C extracted, `deck_ss.cir` ss/27C extracted, `deck_sch.cir` tt/-40C schematic), the testbench copy, and the two ngspice run logs (`inputs/ss-run.txt`, `inputs/tt-n40-run.txt`). The logs carry a `.txt` name because `.gitignore` excludes `*.log` outside `sim/*/corners/`. They are **re-runs** of the decks beside them (ngspice-47, one `ngspice -b` each, 2026-11-25, in the #519 review cycle): the first-run output was never committed and the numbers quoted below were reproduced exactly. Paths are written `<repo>` / `~`; point them at a checkout and a PDK root to rerun |

## Accounting (51 = 24 + 27, by corner, testbench, side)

| group | rows | corners | testbench x side | schematic leg |
|---|---|---|---|---|
| **A** no 2.64 V RESETn rising crossing in the 30 ms window | 24 | 12 | ramp only (2 measurements per corner) | releases at 1.9-4.3 ms at 11 of the 12 corners; `sf/2.970V/-40C` has no crossing on **both** sides (2 of the 24 rows are the schematic side) |
| **B** extracted run aborts | 27 | 9 (`ss`, all 3 V x 3 T) | ramp (18 rows) and iq-por (9 rows), extracted side only | passes at all 9 corners (ramp release 2.6-3.2 ms) |

Group A corners: `tt/2.970V/-40C`, `tt/3.300V/-40C`, `ff/3.300V/125C`,
`ff/3.300V/27C`, `fs/2.970V/125C`, `fs/2.970V/27C`, `fs/3.300V/125C`,
`fs/3.300V/27C`, `fs/3.630V/-40C`, `fs/3.630V/27C`, `sf/3.630V/27C`,
`sf/2.970V/-40C`. Group B corners: `ss/{2.970,3.300,3.630}V/{-40,27,125}C`.

Two group A corners (`ff/3.300V/27C`, `fs/3.630V/-40C`, 4 rows) carry
`delta[].error.code = singular_matrix`, but their side diagnostics also list the
missing-crossing measurement failure, and the same warning appears on corners that
pass. They are group A, not solver aborts: the row code is mis-attributed
(upstream gap, below). Counting by `delta[].error.code` therefore gives 31
`singular_matrix` + 20 `measurement`, but by cause it is 27 + 24.

## Group A: no crossing -- design vs solver is **unresolved**

Measured (fleet report values and one local run each side of tt/3.30 V/-40C):

- The extracted release is bimodal across the 45 corners. Where it releases it is
  either early (1.2-2.3 ms, 0.3-0.9x the schematic) or very late (tt/3.30 V/27C
  16.69 ms, tt/3.63 V/27C 27.45 ms, sf/3.30 V/-40C 20.17 ms, sf/3.63 V/-40C
  21.40 ms, 6-10x); the delta tolerance grades those late values `pass`. At the
  12 group A corners it does not release at all in 30 ms.
- Local single run, extracted, `tt/3.30V/-40C` (5.8 s, ngspice-47, original
  `tran 1u 0.03 0 1e-05` window): reproduces `out of interval`. RESETn never
  rises: max 53 mV (at 10 us), -3.5 mV at 10 ms, -6.9 mV at 30 ms. At 30 ms
  V(VDD) = 3.300 V, **V(PTAT) = 12.79 V** and V(CTAT) = 17 mV.
- Same point, schematic (flat schematic DUT from the grid artifacts): release
  2.757 ms (the fleet's 2.76 ms), RESETn 2.970 V, V(PTAT) = 0.283 V, V(CTAT) =
  0.755 V.

So the failure is a RESETn that stays low, not a release slightly beyond the
window, and the extracted network sits in a state with a node above the supply
(PTAT 12.8 V on a 3.3 V rail), which a passive-parasitic RC netlist cannot reach
physically. That is the signature of a non-physical ngspice solution branch or of
a netlist defect (for example a coupling-capacitor loop with no DC path), not of a
slow timer. This run does not separate them: **attribution unresolved between a
solver branch and an extraction/design cause**. It rules out "window too short"
(the ramp holds VDD flat for 27 ms with RESETn at about 0 V).

Evidence still needed (none requires a grid): a per-node dump for the extracted
`tt/3.30V/-40C` point with `.op` and `.nodeset` on PTAT; the same point at a longer
window and tighter `reltol`; a bisection of the lumped-RC cards (strip the
coupling `C` cards, then the series `R` cards) to see which element creates the
12.8 V state; and a check of why `sf/2.970V/-40C` has no crossing on the
schematic side too (a schematic-only behavior, not a pex effect).

## Group B: `ss` extracted abort -- solver limitation at the DC operating point

- Fleet diagnostics, identical at all 9 corners and both testbenches:
  `singular_matrix` (on `xdut.ptat_trim__t0`, `xdut.nz$1` or `xdut.sns` per
  corner), `timestep_too_small`, `nonconvergence` (dynamic gmin stepping failed),
  `analysis_aborted`.
- Local single run, extracted, `ss/3.30V/27C` (3.3 s): the failure is at the
  **initial operating point**, before any transient step. Dynamic and true gmin
  stepping both fail (`inputs/ss-run.txt` lines 12-15; the fleet diagnostics carry
  only the dynamic-gmin warning); source stepping fails; `Error: Transient op
  failed, timestep too small`; trouble reported at instance `xdut.x$116`
  (`X$116` in `../grid/temp_por_top.pex.spice`, a `sky130_fd_pr__pnp_05v5_W3p40L3p40`
  BJT, the only PNP flavour in the netlist: 19 instances). ngspice's message names
  the PDK's inner model `sky130_fd_pr__pnp_05v5_w0p68l0p68par5x_model-instance`
  and the instance `q.xdut.x$116.qsky130_fd_pr__pnp_05v5_w3p40l3p40`; the
  `w0p68l0p68par5x` string is that inner model card name, not a device in the
  netlist. Singular warnings at `xdut.ptat_trim__t0` and `xdut.nz$1`.
- The schematic leg of the same corners passes, so the extracted netlist (with its
  parasitic `R`/`C` cards and the BJT substrate wiring) is what the solver cannot
  start from at the slow process corner.

Attribution: **solver limitation on the extracted netlist** (no DC solution found
by ngspice's op strategies), restricted to `ss`. The earlier record text calls this
"the #153 signature"; the evidence here supports only the generic part (a
singular-matrix warning followed by a timestep/gmin failure). #153 concerns the
schematic block, whose `ss` legs pass here, so the two are not shown to share a
cause and #153 is left untouched. Not resolved: whether the failure is a genuine
extracted-netlist bistability or a conditioning problem (the same open question as
group A, and the two may share the `PTAT` branch).

## klt gaps demonstrated

Two gaps were found while attributing the rows, filed generically at
`2AMLogic/klayout-tools`; the second turned out to be half a klt gap and half
this repo's own `.gitignore`:

- [#7904](https://github.com/2AMLogic/klayout-tools/issues/7904) -- `delta[].error`
  reports a warning-severity `singular_matrix` instead of the measurement failure
  (4 of the 51 rows; mis-sorts the taxonomy above).
- [#7905](https://github.com/2AMLogic/klayout-tools/issues/7905) -- batch
  `corner.cir` has a `.include` pointing at a non-retained job path
  (`/var/tmp/eda-job-klt-sim-<id>/inputs/netlist.cir`), so the failed corners
  could not be re-run from the artifacts. The two local reproductions above had to
  be rebuilt by hand from the testbench and the extraction. **Not a klt gap:** the
  absence of per-corner `ngspice.log` files in `../grid/artifacts/`. Upstream
  measured that all 180 engine logs were present in the fleet outputs and were
  restored by klt `0.9.2`; this repo's `.gitignore` rule `*.log` (negated only for
  `sim/*/corners/`) kept them out of the committed tree. That is this repo's
  friction (a `*.log` rule hiding record evidence), recorded here, not a tool
  defect.

The design/solver findings (groups A and B) are not klt defects as demonstrated and
are recorded here as evidence only. Whether group B is a klt extraction defect
(compare 2AMLogic/klayout-tools#1263, closed: a substrate-coupling net not
exposed as a pin gave a singular DC solve) is not shown by these runs.

## Disclosure for the cited reports

The three repro decks add `set ng_nomodcheck` and extra `.meas` probes relative to the
grid's `corner.cir`; the `tran 1u 0.03 0 1e-05` window and the 2.64 V `RISE=1`
crossing are the original.

Both `../klt-pex.report.json` (pilot, `status: pass`) and `../grid/klt-pex.report.json`
(grid, `status: error`):

- **`body_bias.status`: `biased`** (0 unbiased devices, 0 unbiased nets, 0 unbiased
  PMOS body nets).
- **`extraction.model`**: the lumped-RC model text carried verbatim in each report:
  net-to-ground area/perimeter capacitance plus vertical-overlap net-to-net
  coupling; lateral coupling only for declared `--critical-net` pairs; a single
  lumped series resistance per net, star-distributed across its device terminals
  (no per-segment RC ladder unless `--distributed-rc` names the net); fringe
  shielding not modelled.
- `model_mismatch` is unchanged (5 V MOS extracting as `01v8`, #467).

Neither report is cited as item 7 in the manifest: the pilot is a single point and
the grid reports `error`.
