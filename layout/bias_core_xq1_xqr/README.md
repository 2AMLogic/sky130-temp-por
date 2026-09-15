# `bias_core_xq1_xqr`

Standalone proof-of-concept layout for `design/netlist/bias_core.spice`'s
`XQ1` and `XQR` devices — two single-instance `sky130_fd_pr__pnp_05v5_W3p40L3p40`
units. `XQ1` (`XQ1 VSS VSS NA ...`) is the matching 1x reference unit for
`layout/bias_core_pnp8_leg/`'s "8:1 PNP emitter-count ratio" leg (#30/PR #33);
`XQR` (`XQR VSS VSS ER ...`) is the `VREF`-leg unit. Both tie collector and
base to `bias_core`'s own `VSS` rail and are otherwise electrically
independent of each other (distinct emitter nets `NA`/`ER`) — they are housed
in one composed cell here purely for layout convenience, not because the
schematic wires them together. Part of #34 (device-group split of `bias_core`
layout work), itself a follow-on from #30/#4.

## Recipe

One `klt gen bjt_array` call (`rows=1 cols=2 ratio=1 topology=common_centroid
add_collector_ring=true`) draws both unit devices under a single shared
common-centroid guard ring in one generator invocation — `Q0` is `XQ1`, `Q1`
is `XQR`. `layout/bin/compose-cell.py layout/bias_core_xq1_xqr/cell.json` runs
the full `gen` → `gen-compose` → `drc` → `extract` → `lvs` chain and writes
every step's response next to this file (`compose.request.json`/
`compose.response.json`, `drc.json`, `extract.json`, `lvs.request.json`/
`lvs.json`, `bias_core_xq1_xqr.gds`, `bias_core_xq1_xqr.spice` — the extracted
netlist — and `bias_core_xq1_xqr.ref.spice` — the generated LVS reference,
rewritten from `reference.spice` per `compose-cell.py`'s own unit rewrite,
which is a no-op here since neither device card carries an `L=`/`W=` token).
Re-verify with:

```
python3 layout/bin/compose-cell.py layout/bias_core_xq1_xqr/cell.json --check
```

`reference.spice` is a hand-extracted, byte-for-byte copy of
`design/netlist/bias_core.spice`'s own `XQ1`/`XQR` device cards, wrapped in a
three-port `.subckt` (see that file's own header comment) — not an xschem
export, since the design's own `.subckt bias_core` is the whole cell, not
this sub-group alone.

## Routing

`routing.layer_role: "metal"` (li1) with `routing.cross_block_layer_role:
"metal2"` (met1) for the one same-block self-net (`vss` bussing `Q0_B` and
`Q1_B`) — without it, the `vss` bus jogs directly over `Q1_E`'s own drawn
pad, the same failure mode `docs/cli/gen-compose.md`'s "Cross-block bus
routing (`routing.cross_block_layer_role`, #1168)" worked example describes,
which `layout/bias_core_pnp8_leg/` also hit. `na` (`XQ1`'s emitter) and `er`
(`XQR`'s emitter) are each declared as a top-level `pins[]` entry rather than
a `connectivity[]` net: `klt gen-compose` requires every `connectivity[]` net
to have at least two `{block, port}` entries ("`pins` must be an array of at
least 2 entries"), and each of these is a single, unshared pin — `pins[]`
promotes a single port to a labelled top-level pin without routing any metal,
which is exactly what a lone emitter pin needs.

**Bussing `vss` between two independently-ringed blocks does not work.**
An earlier attempt placed `XQ1` and `XQR` as two *separate* `bjt_array`
blocks (each with its own closed collector ring) and tried to route `vss`
between their two `Q0_B` ports. `klt gen-compose` rejected it outright: a
route from a port inside a block with a closed guard ring, to anywhere
outside that block, "would cross the ring's own metal loop and merge this
net with the ring's tap net." Opening a routing gap in each ring
(`ring_gap_side`/`ring_gap_um`) traded that error for a cascade of routing-
clearance failures (the bus crossing too close to the opening's edge, then
plowing through the far block's own interior) that did not converge on a
clean route. Housing both devices under one *shared* ring (`cols=2` on a
single `bjt_array` call, as shipped) sidesteps the whole class of problem —
`vss` never needs to leave the block it's declared on — and is the approach
this cell.json uses.

**The collector guard ring (`COLL_N`/`COLL_S`/`COLL_E`/`COLL_W`) is
deliberately left out of `vss`'s connectivity**, for the same reason as
`layout/bias_core_pnp8_leg/`: wiring it in never actually lands a contact on
the diffusion-role port (`klt extract` always recovers the collector as a
separate, unstrapped `vsubs` node despite a `routed: true`/clean-`klt drc`
report). Filed generically:
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894).
Dropping it from `connectivity[]`/`pins[]` avoids that failure mode; the
diffusion region itself is still drawn (the generator's own guard ring,
unchanged) and still extracts as one correctly-merged physical node across
both units — only its strap to `VSS` is missing from this increment.

## Verification

- **`klt drc --deck sky130`: clean, 0 violations.**
- **`klt extract --deck sky130`: 2 devices, 4 nets** (`na`, `er`, `vss`, and
  the unstrapped `vsubs` collector node).
- **`klt lvs` against `reference.spice`: mismatch** (0/2 devices, 0/3 nets,
  per `lvs.json`). The extracted per-device topology is confirmed correct —
  `extract.json`'s own `devices[]` reads `{"c": "vsubs", "b": "vss", "e":
  "na"}` for `XQ1` and `{"c": "vsubs", "b": "vss", "e": "er"}` for `XQR`,
  i.e. base lands on exactly the net the schematic puts it on (`VSS`), each
  emitter lands on its own correctly-separate net (`NA`/`ER`), and the only
  discrepancy is the collector/`vsubs` vs. reference's `VSS` difference
  (this cell has 4 nets where the 3-port reference has 3, so no
  `net`/`pin` count can match while that strap is open) — the same single,
  well-isolated, understood cause `bias_core_pnp8_leg/README.md` documents,
  not a wiring error in this cell's own connectivity.

Revisit once
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)
is resolved upstream — no floorplan change is expected to be needed, only
adding the collector-ring pins back into `vss`'s `connectivity[]`.
