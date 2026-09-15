# `bias_core_passives`

Standalone proof-of-concept layout for `design/netlist/bias_core.spice`'s
`XRT`/`XR1`/`XR2`/`XRZ`/`XCC`/`XCOK` device group — the bias/ratio resistor
network (4x `sky130_fd_pr__res_xhigh_po`) and Miller compensation caps (2x
`sky130_fd_pr__cap_mim_m3_1`) `design/bias_core.md` describes. Part of #34
(device-group split of `bias_core` layout work), decomposed as #37, itself a
follow-on from #30/#4. Follows the compose-cell recipe
`layout/bias_core_pnp8_leg/` (#30/PR #33) established.

Unlike `bias_core_pnp8_leg`'s 8:1 matched-ratio PNP group or
`bias_core_xq1_xqr`'s pair of otherwise-identical unit devices, none of these
6 devices are meant to match each other — every one has its own distinct `L`
(resistors) or `plate_w_um`/`plate_h_um` (caps) per
`design/netlist/bias_core.spice`:

| Device | Ports (device-card order) | Value |
|---|---|---|
| `XRT` | `NBTOP` `NB` `VSS` | `res_xhigh_po`, `L=17.5um` (17.5kΩ) |
| `XR1` | `NB` `EC` `VSS` | `res_xhigh_po`, `L=350.0um` (350kΩ) |
| `XR2` | `VREF` `ER` `VSS` | `res_xhigh_po`, `L=4104.0um` (4.104MΩ) |
| `XRZ` | `NZ` `N2` `VSS` | `res_xhigh_po`, `L=1016.0um` (1.016MΩ) |
| `XCC` | `PG` `NZ` | `cap_mim_m3_1`, 20x20um (~815fF) |
| `XCOK` | `VDD` `NOKX` | `cap_mim_m3_1`, 6x6um (~76.6fF) |

## Recipe

Each device is its own single-instance `klt gen` call — `res_array` (flavor
`xhigh`, `num=1`, `dummy=0`) for the four resistors, `cap_array` (`num=1`)
for the two caps — rather than a matched array. `layout/bin/compose-cell.py
layout/bias_core_passives/cell.json` runs the full `gen` → `gen-compose` →
`drc` → `extract` → `lvs` chain and writes every step's response next to
this file, same shape as the sibling recipes. Re-verify with:

```
python3 layout/bin/compose-cell.py layout/bias_core_passives/cell.json --check
```

`reference.spice` is a hand-extracted, byte-for-byte copy of
`design/netlist/bias_core.spice`'s own `XRT`/`XR1`/`XR2`/`XRZ`/`XCC`/`XCOK`
device cards, wrapped in an 11-port `.subckt` — not an xschem export.

## Floorplan

`XR2` (`L=4104.0um`) is two orders of magnitude longer than every other
device here and dominates this sub-block's bounding box: `res_array` draws
one continuous straight poly body per unit resistor, with no built-in
serpentine/meander folding of a *single* device's own length (its `rows`
param folds separate matched *unit* resistors of an array into parallel
rows — not applicable to one `L=4104.0` device). `placement.strategy: "row"`
places all 6 blocks left to right with a uniform 3um gap, so the composed
cell's own bbox is simply as wide as `XR2` plus the other 5 devices'
combined width — a multi-millimeter-wide sub-block, correctly, rather than
artificially compacted.

## Routing

Two of the six devices' terminals are shared within this device group — `NB`
(`XRT`'s second node / `XR1`'s first node) and `NZ` (`XRZ`'s first node /
`XCC`'s second node) — wired as `connectivity[]` two-pin nets between
adjacent `placement.order` blocks (`rt`↔`r1`, `rz`↔`cc`), each an
opposite-facing port pair so `klt gen-compose`'s obstacle-overlap check
(`docs/cli/gen-compose.md`) has a straight, unobstructed backbone to draw.
Every other non-`VSS` node this device group touches exactly once
(`NBTOP`, `EC`, `VREF`, `ER`, `PG`, `N2`, `VDD`, `NOKX`) is a `pins[]`
declare-only top-level pin instead — no metal routed, just a label on the
port's own already-drawn geometry.

`VSS`: all four resistors' third node is `VSS` in the design netlist, but
`klt gen res_array` reports only two ports per unit (`R<i>_A`/`R<i>_B`) — the
bulk/substrate terminal `sky130_fd_pr__res_xhigh_po` extracts with
(`DeviceExtractorResistorWithBulk`'s synthesized global substrate net,
`vsubs`) is not a drawn/routable port at all, so nothing in `cell.json` wires
it to a locally-named `vss` net. `klt extract` recovers each resistor's bulk
on the deck's global `vsubs` net instead, shared automatically across all
four devices in this composed cell with no `connectivity[]` entry needed
(confirmed: `extract.json` reports `vsubs` with `device_count: 4`). This
initially looked like the resistor analogue of
`layout/bias_core_pnp8_leg/README.md`'s collector-tie gap
([`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)) —
it is not: see "Verification" below for why it is not what blocks this
cell's own LVS run.

## Verification

- **`klt drc --deck sky130`: clean, 0 violations.**
- **`klt extract --deck sky130`: 6 devices, 11 nets** (`ec`, `er`, `n2`,
  `nb`, `nbtop`, `nokx`, `nz`, `pg`, `vdd`, `vref`, `vsubs` — exactly the
  Test Plan's named net list, `VSS` recovered as `vsubs` per the "Routing"
  section above). `device_counts` reads `{"res_xhigh_po": 4,
  "sky130_fd_pr__model__cap_mim": 2}`, and every resistor's own `r_ohm`
  matches `L / W * 2000` (sky130's `res_xhigh_po` sheet rho) exactly —
  `17500`/`350000`/`1016000`/`4104000` Ω for `L=17.5`/`350.0`/`1016.0`/
  `4104.0` respectively.
- **`klt lvs` against `reference.spice`: mismatch** (0/6 devices, 0/11 nets,
  per `lvs.json`) — but, unlike the sibling PNP recipes, **not** because of
  the `VSS`/`vsubs` naming gap the "Routing" section above describes.
  Confirmed directly: renaming `VSS` to `vsubs` throughout a scratch copy of
  `reference.spice` (so the two sides' 11th net is byte-identical) does not
  change the mismatch at all — `reference.spice`'s own device cards already
  carry `VSS` as an explicit third node, so `klt lvs`'s `subckt-call`
  conversion already gives the reference-side resistor class the same
  3-terminal arity as the layout side.

  The real, confirmed root cause is two independent, generic
  `klayout-tools` gaps in how a resistor/capacitor round-trips through the
  SPICE text `klt lvs`'s `form: "subckt-call"` reference conversion and
  `klt extract`'s own netlist writer produce:

  1. **`normalize_reference_netlist`'s `subckt-call` conversion writes a
     literal placeholder value `"0"`** for a converted resistor/capacitor
     card (by design — it has no PDK sheet-resistance/capacitance-per-area
     table to compute a real value from `L=`/`W=`, and deliberately does not
     depend on `klayout_tools.decks` to get one). Every one of this device
     group's four `res_xhigh_po` reference instances therefore reads back
     with the *same* value (`0`), and `kdb.NetlistComparer` cannot establish
     a device correspondence for a class whose every reference-side instance
     shares that placeholder — the whole compare collapses to a `"topology:
     device class could not be mapped to a counterpart"` mismatch on both
     sides instead of proceeding on net-topology alone (which *would*
     disambiguate the four resistors, since each sits on a distinct net
     pair) and reporting the value gap as an ordinary parameter mismatch.
     Confirmed directly: rewriting a scratch reference to `form:
     "plain-element"` with each resistor's/cap's real, correctly-computed
     value (matching `extract.json`'s own reported `r_ohm`/`c_f` exactly)
     raised the match to 4/6 devices, 7/11 nets — every resistor and every
     resistor-touching net matched; only the two caps (and their 4
     cap-touching nets) stayed unmatched, isolating gap 2 below as a fully
     independent second cause. This means `form: "subckt-call"` cannot
     currently reach `status: "match"` (or a useful partial match) for
     *any* design using a curated resistor or capacitor device class,
     defeating its own stated purpose for exactly that case.
  2. **`klt extract`'s SPICE netlist writer drops a MiM capacitor's
     device-class/model-name token from its `C` card entirely.** Every
     resistor `R` card correctly carries a trailing model name
     (`R$3 nbtop nb vsubs 17500 res_xhigh_po`), but every capacitor `C` card
     does not (`C$1 nz pg 8.152e-13` — no fifth token at all, confirmed in
     this cell's own committed `bias_core_passives.spice`). Read back by
     `NetlistSpiceReader` (as `klt lvs` does for both sides), a `C` card
     with no model name becomes the generic `CAP` class rather than the
     specific `sky130_fd_pr__model__cap_mim` a reference declares — so no
     capacitor in any composed cell using `cap_array` can ever be paired
     against a class-carrying reference, independent of gap 1 above.

  Both are generic, design-independent `klayout-tools` gaps, filed per this
  repo's friction protocol:
  [`2AMLogic/klayout-tools#1907`](https://github.com/2AMLogic/klayout-tools/issues/1907)
  (gap 1) and
  [`2AMLogic/klayout-tools#1908`](https://github.com/2AMLogic/klayout-tools/issues/1908)
  (gap 2).

Revisit once those two issues are resolved upstream — no floorplan or
`connectivity[]`/`pins[]` change is expected to be needed in this cell.json,
only `klt lvs`/`klt extract` themselves.
