# `por_comparator` post-layout (parasitic extraction) evidence -- issue #124, T1 item 7

**Evidence, not a spec claim.** `spec/` and `design/` are untouched; no sim record is edited (new record ids only).

## What is here

| file | what |
|---|---|
| `por_comparator.pex.spice` | raw `klt extract --parasitics --deck sky130 --pdk sky130A --pins VDD,VSS,IBIAS,VREF,BIAS_OK,POR_RAW` of `../por_comparator.gds`, verbatim |
| `klt-extract.report.json` | the extraction's own JSON report (21 devices, 81 R, 15 C to substrate, 7 coupling C; total 35349 ohm / 2032 fF; deck sha256 `f8f2c3f4...`, klt 0.7.0+g5e5b55992a7f, open_pdks c6d73a35) |
| `klt-pex.report.json` | the `klt pex` run (`pextb/`, single tt/27C corner, local) -- **status `error`, see Blocker** |
| `make_sim_netlist.py` -> `por_comparator.pex.sim.spice` | the disclosed, mechanical derivation of a simulatable netlist (below) |
| `pextb/` | the `klt pex` testbench request + netlist (same stimulus as the campaign, DUT `.include`d) |
| `../../../sim/por-comparator-thresholds/records/20261010-0112*-postlayout.*` | the post-layout PVT records (15/15 points x 2 rates x 2 variants on the Spot batch fleet) |

## Extraction model (named)

`klt extract --parasitics`, deck `sky130`: **lumped RC**. Per net, one series resistance distributed as a star over the net's
device terminals plus one net-to-substrate (`vsubs`) capacitance from area/perimeter; net-to-net capacitance **only for vertical
overlap** (crossover). **Not modelled**: lateral (same-layer sidewall) coupling (no `--critical-net` given), distributed per-segment RC
(no `--distributed-rc`), fringe shielding, inductance, frequency dependence. `vsubs` gets a 1 Tohm DC tie to ground. Device `W`/`L` come
from the drawn geometry, so the three `res_xhigh_po` bodies (7.9 mm, 6.8 mm, 0.78 mm) are the same drawn-geometry model cards as in the
schematic: the divider body's own distributed capacitance to substrate is **not** extracted beyond the per-net lumped cap.
Full model text: `extraction.model` in `klt-pex.report.json`.

## Blocker: `klt pex` testbench mode cannot grade this cell as-is

`klt pex` reproduced the schematic side exactly (tt/27C: VPOR-up 2.695039 V, VPOR-down 2.547012 V, identical to the fleet
record) but **the extracted side could not be graded** (`status: error`, 2 errored rows, `nothing_checked`), for two reasons:

1. **Pin order.** The extracted `.SUBCKT` lists pins alphabetically (`BIAS_OK IBIAS POR_RAW VDD VREF VSS`) while the testbench
   instantiates positionally; the DUT is wired to the wrong nets and POR_RAW never toggles. Already filed upstream:
   [2AMLogic/klayout-tools#2890](https://github.com/2AMLogic/klayout-tools/issues/2890) (no new issue filed).
2. **MOS flavour.** The layout carries no `hvi` marker (`../README.md` Known gaps 1), so all 18 MOS extract as `sky130_fd_pr__{n,p}fet_01v8`
   while the design uses `..._g5v0d10v5`. `klt pex` reports this correctly in `model_mismatch`. Upstream
   [#1912](https://github.com/2AMLogic/klayout-tools/issues/1912) / [#2402](https://github.com/2AMLogic/klayout-tools/issues/2402) cover it.

## Derived simulation netlist (what the campaign actually ran)

`make_sim_netlist.py` makes exactly two edits to the raw extraction and no other (R, C, W, L, topology unchanged): (1) renames the
extracted subckt `por_comparator_pex` and adds a `por_comparator` wrapper in the schematic pin order that binds the nets by name;
(2) rewrites the 18 MOS models `01v8` -> `g5v0d10v5` (the devices the layout is drawn for). A **single** local tt/27C probe of
this netlist gave 2.6949 / 2.5455 V. The result is therefore "extracted parasitics + the schematic's device models", **not** an
unmodified `klt pex` delta, and it inherits the layout's open `hvi` gap (this cell is not 5 V signoff).

## Campaign (new append-only variants)

`sim/por-comparator-thresholds/experiment.json` gains `ideal-bias-postlayout` and `real-bias-core-postlayout` (same testbenches,
stimulus, 5 process x 3 temperature grid, 100 V/s + 50 V/s half-rate guard, same extractor). Only the `por_comparator` DUT changes;
in the real-bias variant `bias_core` stays the schematic export. Submitted with `run --variant ... --capacity-wait 2700`: 4 `klt sim`
requests, 60 points, all on the Spot batch fleet (job ids in each record's fleet-submissions table); nothing was run locally except the one probe.
All 30 points per variant are clean single-edge results and rate-consistent. Regenerate the tables with
`python3 -I sim/por-comparator-thresholds/postlayout_delta.py <schematic record.json> <post-layout record.json>`.

## Post-layout vs schematic delta (VPOR-up / VPOR-down / hysteresis, PVT grid)

Headline: the extracted lumped-RC parasitics move VPOR-up by -1.8..+0.1 mV, VPOR-down by -1.6..+2.0 mV and hysteresis by
-3.5..+1.4 mV (ideal bias); -1.7..0.0, -2.0..+0.2 and -1.4..+1.2 mV (real bias_core). The sweep resolution is 2 mV of VDD per sample
(1 mV at 50 V/s), so **most deltas are at or below the measurement resolution**. The margin to the 2.97 V low rail is unchanged
(+269 mV ideal, +257 mV real-bias). Not covered: lateral coupling, distributed RC, mismatch Monte Carlo, other sweep rates, and the
fast supply ramp of the assembled block.

### ideal-bias

Schematic record `20261009-054322-10d3e9f-ideal-bias` vs post-layout record `20261010-011227-e2e3fff-ideal-bias-postlayout` (rate 100 V/s; delta = post-layout - schematic)

| corner (process, T) | VPOR-up sch / pex (V) | dUP (mV) | VPOR-down sch / pex (V) | dDOWN (mV) | hyst sch / pex (mV) | dHYST (mV) | status sch / pex |
|---|---|---|---|---|---|---|---|
| tt_-40c | 2.6990 / 2.6990 | -0.0 | 2.5490 / 2.5484 | -0.6 | 150.0 / 150.7 | +0.6 | OK / OK |
| tt_27c | 2.6950 / 2.6949 | -0.2 | 2.5470 / 2.5454 | -1.6 | 148.1 / 149.5 | +1.4 | OK / OK |
| tt_125c | 2.6870 / 2.6855 | -1.5 | 2.5430 / 2.5450 | +2.0 | 144.0 / 140.5 | -3.5 | OK / OK |
| ss_-40c | 2.7010 / 2.7010 | -0.0 | 2.5510 / 2.5496 | -1.4 | 150.1 / 151.5 | +1.4 | OK / OK |
| ss_27c | 2.6970 / 2.6970 | -0.1 | 2.5471 / 2.5466 | -0.5 | 149.9 / 150.3 | +0.4 | OK / OK |
| ss_125c | 2.6890 / 2.6890 | -0.0 | 2.5432 / 2.5450 | +1.7 | 145.8 / 144.1 | -1.8 | OK / OK |
| ff_-40c | 2.6970 / 2.6970 | -0.0 | 2.5475 / 2.5476 | +0.1 | 149.6 / 149.5 | -0.1 | OK / OK |
| ff_27c | 2.6930 / 2.6912 | -1.8 | 2.5439 / 2.5438 | -0.0 | 149.1 / 147.3 | -1.8 | OK / OK |
| ff_125c | 2.6832 / 2.6830 | -0.1 | 2.5430 / 2.5437 | +0.8 | 140.2 / 139.3 | -0.9 | OK / OK |
| sf_-40c | 2.6971 / 2.6970 | -0.1 | 2.5480 / 2.5476 | -0.4 | 149.1 / 149.4 | +0.3 | OK / OK |
| sf_27c | 2.6930 / 2.6930 | -0.0 | 2.5447 / 2.5450 | +0.3 | 148.3 / 148.1 | -0.3 | OK / OK |
| sf_125c | 2.6853 / 2.6850 | -0.3 | 2.5456 / 2.5470 | +1.4 | 139.7 / 138.0 | -1.7 | OK / OK |
| fs_-40c | 2.6990 / 2.6990 | +0.0 | 2.5492 / 2.5490 | -0.2 | 149.8 / 150.0 | +0.2 | OK / OK |
| fs_27c | 2.6950 / 2.6950 | -0.0 | 2.5467 / 2.5455 | -1.2 | 148.3 / 149.5 | +1.2 | OK / OK |
| fs_125c | 2.6871 / 2.6872 | +0.1 | 2.5430 / 2.5426 | -0.4 | 144.1 / 144.6 | +0.5 | OK / OK |

- VPOR-up delta over 15 comparable points: min -1.8 mV (ff_27c), max +0.1 mV (fs_125c)
- VPOR-down delta over 15 comparable points: min -1.6 mV (tt_27c), max +2.0 mV (tt_125c)
- hysteresis delta over 15 comparable points: min -3.5 mV (tt_125c), max +1.4 mV (tt_27c)
- max(VPOR-up): schematic 2.7010 V (ss_-40c), post-layout 2.7010 V (ss_-40c)
- margin vs 2.97 V low rail: schematic +269 mV, post-layout +269 mV

### real-bias-core

Schematic record `20261009-054331-79eebd4-real-bias-core` vs post-layout record `20261010-011229-e2e3fff-real-bias-core-postlayout` (rate 100 V/s; delta = post-layout - schematic)

| corner (process, T) | VPOR-up sch / pex (V) | dUP (mV) | VPOR-down sch / pex (V) | dDOWN (mV) | hyst sch / pex (mV) | dHYST (mV) | status sch / pex |
|---|---|---|---|---|---|---|---|
| tt_-40c | 2.6970 / 2.6970 | -0.0 | 2.5412 / 2.5410 | -0.2 | 155.8 / 156.1 | +0.2 | OK / OK |
| tt_27c | 2.7090 / 2.7090 | -0.0 | 2.5532 / 2.5530 | -0.3 | 155.8 / 156.1 | +0.2 | OK / OK |
| tt_125c | 2.7032 / 2.7031 | -0.1 | 2.5532 / 2.5527 | -0.5 | 150.0 / 150.4 | +0.4 | OK / OK |
| ss_-40c | 2.7010 / 2.6997 | -1.3 | 2.5450 / 2.5430 | -2.0 | 156.1 / 156.8 | +0.7 | OK / OK |
| ss_27c | 2.7130 / 2.7129 | -0.2 | 2.5567 / 2.5570 | +0.2 | 156.3 / 155.9 | -0.4 | OK / OK |
| ss_125c | 2.7071 / 2.7070 | -0.1 | 2.5550 / 2.5548 | -0.2 | 152.2 / 152.3 | +0.1 | OK / OK |
| ff_-40c | 2.6930 / 2.6930 | +0.0 | 2.5390 / 2.5377 | -1.2 | 154.1 / 155.3 | +1.2 | OK / OK |
| ff_27c | 2.7050 / 2.7050 | -0.0 | 2.5507 / 2.5510 | +0.2 | 154.3 / 154.1 | -0.3 | OK / OK |
| ff_125c | 2.6992 / 2.6991 | -0.1 | 2.5527 / 2.5530 | +0.2 | 146.5 / 146.1 | -0.4 | OK / OK |
| sf_-40c | 2.6908 / 2.6890 | -1.7 | 2.5353 / 2.5340 | -1.3 | 155.5 / 155.1 | -0.4 | OK / OK |
| sf_27c | 2.7030 / 2.7029 | -0.1 | 2.5479 / 2.5474 | -0.5 | 155.2 / 155.5 | +0.3 | OK / OK |
| sf_125c | 2.6989 / 2.6972 | -1.6 | 2.5530 / 2.5527 | -0.2 | 145.9 / 144.5 | -1.4 | OK / OK |
| fs_-40c | 2.7010 / 2.7008 | -0.2 | 2.5450 / 2.5438 | -1.1 | 156.1 / 157.0 | +0.9 | OK / OK |
| fs_27c | 2.7116 / 2.7110 | -0.6 | 2.5563 / 2.5554 | -0.9 | 155.3 / 155.7 | +0.3 | OK / OK |
| fs_125c | 2.7070 / 2.7056 | -1.4 | 2.5532 / 2.5529 | -0.3 | 153.8 / 152.7 | -1.1 | OK / OK |

- VPOR-up delta over 15 comparable points: min -1.7 mV (sf_-40c), max +0.0 mV (ff_-40c)
- VPOR-down delta over 15 comparable points: min -2.0 mV (ss_-40c), max +0.2 mV (ff_27c)
- hysteresis delta over 15 comparable points: min -1.4 mV (sf_125c), max +1.2 mV (ff_-40c)
- max(VPOR-up): schematic 2.7130 V (ss_27c), post-layout 2.7129 V (ss_27c)
- margin vs 2.97 V low rail: schematic +257 mV, post-layout +257 mV

## Re-run at the klt `0.9.2` pin (issue #454, 2026-11-20): pin order fixed, report `pass`

The #124 run above was produced by klt `0.7.0+g5e5b55992a7f`. Issue #454 step 1
re-ran the **unchanged** testbench (`pextb/`) on the **unchanged committed
stream** (`../por_comparator.gds`) at the repo's pinned build, klt `0.9.2`
(`046ba74652fc`, via `uvx --from "klayout-tools==0.9.2"`), `--pdk-root
~/.ciel` (open_pdks `f6eeac7dad0…`, the `layout/pdk.json` pin), single tt /
27 C / 3.63 V corner, backend `local` -- no grid, no fleet submission. Both
legs together ran in under a minute on the dispatch host.

| file | what |
|---|---|
| `klt-pex.rerun.report.json` | the re-run's `klt pex` report -- **status `pass`**, 2/2 delta rows |
| `por_comparator.pex.rerun.spice` | the re-run's raw extraction (21 devices, 15 nets -- same counts as 0.7.0) |

**Pin order: fixed.** klt `0.9.2` extraction emits the `.SUBCKT` pins in the
declared `--pins` order -- `.SUBCKT por_comparator VDD VSS IBIAS VREF BIAS_OK
POR_RAW` -- where `0.7.0` wrote them alphabetically (`BIAS_OK IBIAS POR_RAW VDD
VREF VSS`, blocker 1 above; fixed upstream by
[klayout-tools#3269](https://github.com/2AMLogic/klayout-tools/pull/3269)). The
positional `XDUT VDD 0 IBIAS VREF BIAS_OK POR_RAW por_comparator` instantiation
is therefore wired correctly now, and the extracted leg produces both crossings
on its own (`sides.extracted` corner status `pass`, `produced_value: true`):

| spec row (tt/3.63V/27C) | schematic | extracted | delta |
|---|---|---|---|
| `vpor_up_approx` | 2.69504 V | 2.69641 V | +0.051 % |
| `vpor_down_approx` | 2.54701 V | 2.54701 V | 0.0 % |

(The 0.7.0 schematic-side values 2.695039 / 2.547012 reproduce as 2.69504 /
2.54701.)

**MOS flavour: unchanged, and not a tool gap.** `model_mismatch` still reports
the 18 MOS extracting as `sky130_fd_pr__{n,p}fet_01v8` against the design's
`..._g5v0d10v5` (12 n + 6 p; `res_xhigh_po` matches 3/3) -- a property of the
committed stream (no `hvi` marker, `../README.md` Known gaps 1), not of the
tool. Retirement is the re-render at a bumped pin: the guard-ringed-marker
blocker [klayout-tools#6025](https://github.com/2AMLogic/klayout-tools/issues/6025)
closed 2026-11-18 (fix [klayout-tools#6185](https://github.com/2AMLogic/klayout-tools/pull/6185),
commit `89b2cc61a9c4`), but that fix sits 1091 commits past the `v0.9.2` tag
and is in no klt release yet -- the pin bump and `hvi` re-render are tracked in
[#467](https://github.com/2AMLogic/sky130-temp-por/issues/467). `klt pex` grades
this run `pass` with the mismatch disclosed in `model_mismatch.detail`, so the
delta values above compare the layout's drawn `W`/`L` in the 1.8 V model
domain -- the same disclosure the hand-derived campaign netlist carried.

**Body bias / extraction model** (unchanged from the #124 run):
`body_bias.status` is `biased` (0 unbiased devices, nets, or PMOS body nets);
`extraction.model` is the same lumped-RC text as the 0.7.0 run -- single lumped
series R per net in a star, net-to-ground C from area/perimeter,
vertical-overlap net-to-net C, quasi-static; no lateral coupling without
`--critical-net`, no distributed RC, no fringe shielding, no inductance --
quoted verbatim in `klt-pex.rerun.report.json`'s `extraction.model`.

**`make_sim_netlist.py` is no longer needed for new pex evidence** -- `klt pex`
at `0.9.2` measures the extracted leg directly. It stays as the disclosed
derivation of what the #124 PVT campaign actually ran (it additionally rewrote
the MOS models to `g5v0d10v5`, which a `klt pex` run does not), so the
committed campaign records remain reproducible.

**For the block-level run** (issue #454 step 3, waits on #453): `klt pex` at
`0.9.2` already speaks the fleet protocol (`--backend batch`,
`--wait-for-capacity`, `--submit-only`/`--attach`, `--max-units-per-job`) -- a
corner grid can go through the batch fleet the same way `klt sim`'s does; no
upstream dispatch gap to file.
