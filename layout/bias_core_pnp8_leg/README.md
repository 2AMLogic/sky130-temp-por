# `bias_core_pnp8_leg`

Standalone proof-of-concept layout for `design/netlist/bias_core.spice`'s
`XQ8A..XQ8H` device group — `design/bias_core.md`'s "8:1 PNP emitter-count
ratio" leg: 8 unit `sky130_fd_pr__pnp_05v5_W3p40L3p40` devices, every
collector and base tied to `bias_core`'s own `VSS` rail, every emitter tied
to the shared `EC` node. `XQ1` (the matching 1x reference unit) and `XQR`
(the `VREF`-leg unit) are each a separate single-instance device elsewhere in
`bias_core` and are **not** part of this proof cell — see `layout/README.md`
for why this sub-block was chosen first and what's still open.

## Recipe

One `klt gen bjt_array` call (`rows=2 cols=4 ratio=8 topology=common_centroid
add_collector_ring=true`) draws the whole matched, common-centroid, guard-ring
unit in a single generator invocation — no manual multi-block placement is
needed. `layout/bin/compose-cell.py layout/bias_core_pnp8_leg/cell.json` runs
the full `gen` → `gen-compose` → `drc` → `extract` → `lvs` chain and writes
every step's response next to this file (`compose.request.json`/
`compose.response.json`, `drc.json`, `extract.json`, `lvs.request.json`/
`lvs.json`, `bias_core_pnp8_leg.gds`, `bias_core_pnp8_leg.spice` — the
extracted netlist — and `bias_core_pnp8_leg.ref.spice` — the generated LVS
reference, rewritten from `reference.spice` per `compose-cell.py`'s own unit
rewrite). Re-verify with:

```
python3 layout/bin/compose-cell.py layout/bias_core_pnp8_leg/cell.json --check
```

`reference.spice` is a hand-extracted, byte-for-byte copy of
`design/netlist/bias_core.spice`'s own `XQ8A..XQ8H` device cards, wrapped in
a two-port `.subckt` (see that file's own header comment) — not an xschem
export, since the design's own `.subckt bias_core` is the whole cell, not
this sub-group alone.

## Routing

`routing.layer_role: "metal"` (li1) with `routing.cross_block_layer_role:
"metal2"` (met1) — the two same-block self-nets here (`vss` bussing the 8
base pins, `ec` bussing the 8 emitter pins) each cross the other's
intervening pads, exactly `docs/cli/gen-compose.md`'s own "Cross-block bus
routing (`routing.cross_block_layer_role`, #1168)" worked example, which
uses this same 8-unit `bjt_array` shape.

**The collector guard ring (`COLL_N`/`COLL_S`/`COLL_E`/`COLL_W`) is
deliberately left out of `vss`'s connectivity.** Wiring it in — at any
`routing.layer_role` tried — never actually lands a contact on the
diffusion-role port (`klt extract` always recovers the collector as a
separate, unstrapped `vsubs` node despite a `routed: true`/clean-`klt-drc`
report), and combining it with a second same-block net was observed to
silently short the two together. Filed generically:
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894).
Dropping it from `connectivity[]` avoids both failure modes; the diffusion
region itself is still drawn (the generator's own guard ring, unchanged) and
still extracts as one correctly-merged physical node across all 8 units —
only its strap to `VSS` is missing from this increment.

## Verification

- **`klt drc --deck sky130`: clean, 0 violations.**
- **`klt extract --deck sky130`: 8 devices, 3 nets** (`ec`, `vss`, and the
  unstrapped `vsubs` collector node).
- **`klt lvs` against `reference.spice`: mismatch** (0/8 devices, 0/2 nets,
  per `lvs.json`). The extracted per-device topology is confirmed correct —
  every one of the 8 devices reads `Q$N vsubs vss ec` (collector, base,
  emitter), i.e. base and emitter land on exactly the two nets the schematic
  puts them on, and stay correctly *separate* from each other — the mismatch
  is entirely the collector/`vsubs` vs. reference's `VSS` difference (this
  cell has 3 nets where the 2-port reference has 2, so no `net`/`pin` count
  can match while that strap is open). This was independently confirmed with
  a reduced probe cell.json that also excludes `ec`; the same collector/vss
  split holds, isolating the mismatch to a single, understood cause rather
  than a routing error in this cell's own connectivity.

Revisit once
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)
is resolved upstream — no floorplan change is expected to be needed, only
adding the collector-ring pins back into `vss`'s `connectivity[]`.
