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

Revisit once the installed `klt` carries
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)'s
fix — see "Upstream status" below — at which point no floorplan change is
expected to be needed beyond adding the collector-ring pins back into
`vss`'s `connectivity[]`.

## Full-cell assembly pins (issue #61)

`pins[]` already promoted `na` and `er` — each a lone emitter pin, promoted
without routing any metal. `vss` was the gap: a real cross-sub-block net
(`bias_core`'s own global ground) that this cell only bussed *internally*,
between `Q0_B` and `Q1_B`, with no externally reachable pad. #40's full-cell
assembly needs it reachable from outside this block, so `pins[]` now
promotes it too.

### Why the ring had to be opened

Same blocker as `layout/bias_core_pnp8_leg/`: `klt gen-compose` refuses any
leg from a non-tap port of a block whose guard/collector ring is a closed
loop ("a route to its non-tap port would cross the ring's own metal loop and
merge this net with the ring's tap net"), so PR #62's plain west-edge-stub
promotion cannot be used here — the rejection fires on the **first** leg
leaving the block. Note this is a *different* failure from the one the
"Routing" section above records: that one was about bussing `vss` between
two *separately* ringed blocks, solved by housing both devices under one
shared ring. This one is about getting a net out of that shared ring at all.

The rejection is plane-agnostic — it fires identically for a backbone on
`metal3` (met2, 70/20), two via levels above the ring's own diffusion role
(65/20), where no merge is physically possible. Filed generically upstream
as
[`2AMLogic/klayout-tools#1960`](https://github.com/2AMLogic/klayout-tools/issues/1960).

So the array is regenerated with a routing opening in the ring
(`params.ring_gap_side: "N"`, `ring_gap_um: 1.5`,
`ring_gap_offset_um: -0.41`), centred exactly on `Q0_B`'s own `x=4.01um`
(the ring's N midpoint is `x=4.42um`). The generator now reports
`COLL_S`/`COLL_E`/`COLL_W` plus a `GAP_N` marker there.

| Net | Tap mechanism | Promoted pad |
|---|---|---|
| `vss` | new leg branching north out of `Q0_B` straight through `GAP_N`, then west | `stub_vss.PAD`, `x=-5.0, y=6.0` |

`Q0_B` sits `2.67um` below the block's own north edge (`y=1.7`, bbox
`y1=4.37`) and the opening is centred on its `x`, so the escape riser is a
straight northward run that crosses no other pad. `stub_vss` is a plain
declare-only li1 stub (`promo_stub.gds`), no PDK awareness needed.

### What the opening costs, stated plainly

The collector ring is now a C-shaped conductor, not a closed loop: its
substrate-isolation function is interrupted for the `1.5um` of the N-side
opening. That is a real floorplan change, not a free one — it just costs
this cell nothing it currently *has*, since the ring is already not strapped
to `VSS` at all and `klt extract` recovers it as the same floating `vsubs`
node either way. Once the installed `klt` carries #1894's fix, close the
ring again and promote `vss` through a real `COLL_*` tap instead.

### Evidence: this changed no device, no net, and no verdict

| | before #61 | after #61 |
|---|---|---|
| `klt drc` | clean, 0 violations | clean, 0 violations |
| `klt extract` | 2 devices, 4 nets, 4 pins | 2 devices, 4 nets, 4 pins |
| extracted netlist `sha256` | `f43e2ba9…` | `f43e2ba9…` (identical) |
| `klt lvs` | `mismatch`, 11 (4 `device.unmatched` + 7 `net.unmatched`) | `mismatch`, 11 (4 + 7) — unchanged |

The extracted-netlist hash being *identical* is the strongest available
evidence that the ring opening merged nothing and broke nothing: `na`/`er`
stay correctly separate, both bases stay on `vss`, and the collector stays
the same separate `vsubs` node. The LVS mismatch is the same pre-existing,
well-isolated collector-strap gap documented under "Verification" — **not**
something this change introduced.

**Verified against a downstream target, not just eyeballed.**

```
python3 layout/bin/check-promotion.py layout/bias_core_xq1_xqr/cell.json
```

places this cell's own composed GDS as a `blocks[].cell` reference plus one
dummy pad for the newly-promoted pin, and routes a 2-pin net to it:
`unrouted_nets: []`, and the downstream-composed stream is itself `klt
drc`-clean. Evidence:
`downstream-check.request.json`/`.response.json`/`.drc.json`/`.gds` next to
this file. Re-run the whole chain with
`python3 layout/bin/compose-cell.py layout/bias_core_xq1_xqr/cell.json --check`.

`na`/`er` are unchanged by this issue — both are still promoted directly off
`array.Q0_E`/`array.Q1_E`, and both still compose cleanly downstream.

### Upstream status (as of 2026-09-16)

[`#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894) **is closed
as COMPLETED**, by
[PR #1930](https://github.com/2AMLogic/klayout-tools/pull/1930) (merged
`2026-09-16T06:44:04Z`), which *did* land a real `COLL_*` diffusion-role
contact fix. **This repo cannot use it yet**: the installed toolchain is
`klt 0.5.0+gba213c617b4e`, built from `ba213c61` (`2026-09-15T23:03:10Z`) —
about eight hours *before* that merge — and its `_resolve_via_drop_layer()`
still has the pre-fix fallthrough. See
`layout/bias_core_pnp8_leg/README.md`'s own "Upstream status" section for
the full write-up.
