# `bias_core` post-layout (parasitic extraction) evidence -- issue #487

**Evidence, not a spec claim.** `spec/` and `design/` are untouched; no sim record is edited (new record ids only).

## What is here

| file | what |
|---|---|
| `bias_core.pex.spice` | raw `klt extract --parasitics --deck sky130 --pdk sky130A --top bias_core --pins VDD,VSS,IBIAS,VREF,BIAS_OK` of `../bias_core.gds` (post-#473/#488 render), verbatim |
| `klt-extract.report.json` | the extraction's own JSON report (51 devices: 18 nfet, 17 pfet, 10 pnp, 4 res_xhigh_po, 2 MiM cap; 187 R, 51 C) |
| `make_sim_netlist.py` -> `bias_core.pex.sim.spice` | the disclosed, mechanical derivation of a simulatable netlist (below) |
| `../../../sim/por-comparator-thresholds/records/20261124-031933-1df0a90f-real-bias-core-biaspex.*` | the PVT record (15/15 points x 2 rates, Spot batch fleet) |

## Extraction model (named)

`klt extract --parasitics`, deck `sky130`: **lumped RC**. Per net, one series resistance distributed as a star over the net's device
terminals plus one net-to-substrate (`vsubs`) capacitance from area/perimeter; net-to-net capacitance only for vertical overlap
(crossover). **Not modelled**: lateral (same-layer sidewall) coupling, distributed per-segment RC, fringe shielding, inductance,
frequency dependence. `vsubs` gets a DC tie to ground.

**Resistor handling.** The four `res_xhigh_po` bodies (~5.9 mm of drawn poly; L = 350 / 350 / 1016 / 4104 at W = 2) are instantiated
with their drawn W/L as the same `sky130_fd_pr__res_xhigh_po` model cards the schematic uses. The extractor adds only the
metal-interconnect R and per-net lumped C around them; each body's own distributed capacitance to substrate is **not** extracted beyond
the per-net lumped cap. The result therefore measures routing/interconnect parasitics, not a distributed-RC resistor model.

## Derived simulation netlist (what the campaign ran)

`make_sim_netlist.py` makes exactly two edits and no other (R, C, W, L, topology unchanged): (1) collapses the `NAME|alias` net names
(the layout labels every pin twice, e.g. `VDD|vdd`; `|` is not a safe SPICE node character) to `NAME`; the `--pins` subckt pin order is
already the schematic order, asserted by the script, so no wrapper is needed; (2) rewrites the 35 MOS models `01v8` ->
`g5v0d10v5` (the devices the layout is drawn for; the layout carries no `hvi` marker, so the deck binds the 1.8 V flavour). The result
is "extracted parasitics + the schematic's device models" and inherits that open `hvi` gap. Only a single local tt/27 C probe was run
locally (VPOR-up 2.7127 V, single edge, before the batch).

## Campaign

`sim/por-comparator-thresholds/experiment.json` gains `real-bias-core-biaspex` (same testbench/stimulus/grid/rates as
`real-bias-core`; only `bias_core` swapped). See the "Bias-core post-layout variant" section of
[`sim/por-comparator-thresholds/README.md`](../../../sim/por-comparator-thresholds/README.md) for the delta table.

## Tool friction

Filed [2AMLogic/klayout-tools#7724](https://github.com/2AMLogic/klayout-tools/issues/7724): doubly-labelled pins are emitted as `VDD|vdd` net names (needed the mechanical rewrite above). The MOS-flavour gap (no `hvi` marker) is already tracked from the `por_comparator` extraction.
