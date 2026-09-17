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

Revisit once the installed `klt` carries
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)'s
fix — see "Upstream status" below — at which point no floorplan change is
expected to be needed beyond adding the collector-ring pins back into
`vss`'s `connectivity[]`.

## Full-cell assembly pins (issue #61)

This cell's own isolated LVS reference only needed `ec`/`vss` bussed
*internally*, so `cell.json` carried **no `pins[]` at all**. Both are real
cross-sub-block nets in `design/netlist/bias_core.spice` — `ec` reaches
`bias_core_passives`'s `XR1`, `vss` is `bias_core`'s global ground bus — so
#40's full-cell assembly needs both reachable from outside this block.

`pins[]` now promotes both, via the same declare-only metal stub technique
PR #62 used on `bias_core_mirror_amp`/`bias_core_settle_flag`/
`bias_core_startup` — **plus one floorplan change those cells did not need**:
a routing opening in the collector ring.

### Why the ring had to be opened

`klt gen-compose` refuses *any* leg from a non-tap port of a block whose
guard/collector ring is a closed loop:

> block 'array' has a closed guard/collector ring (reports a TAP_*/COLL_*
> port and no GAP_* opening) — a route to its non-tap port 'Q3_E' would
> cross the ring's own metal loop and merge this net with the ring's tap
> net; route to the ring's own tap port instead, regenerate the block with
> a routing opening in the ring (params.ring_gap_side/ring_gap_um), or
> regenerate it with add_guard_ring/add_collector_ring: false

That is a *defensive* improvement — it is exactly the silent-short failure
mode `layout/README.md`'s "Known klt gaps" finding 2 describes, now caught
instead of drawn — but it forecloses PR #62's west-edge-stub workaround
here, because it fires on the **first** leg leaving the block, before any
question of where the stub sits. None of the three remedies it names is
free for this cell: `ec`/`vss` are device nets, not the ring's tap net, so
routing to `COLL_*` would wire them to the wrong node; and dropping the
ring entirely throws away the isolation this matched PNP array exists to
get. Verified: the rejection is *plane-agnostic* — it fires identically for
a backbone on `metal3` (met2, 70/20), two via levels above the ring's own
diffusion role (65/20), where no merge is physically possible. Filed
generically upstream as
[`2AMLogic/klayout-tools#1960`](https://github.com/2AMLogic/klayout-tools/issues/1960).

So the array is regenerated with one opening (`params.ring_gap_side: "N"`,
`ring_gap_um: 4.0`, `ring_gap_offset_um: -1.565`), wide enough to carry
both escapes. The generator now reports `COLL_S`/`COLL_E`/`COLL_W` plus a
`GAP_N` marker at `x=7.475um` (the ring's N midpoint is `x=9.04um`), i.e.
an opening spanning `[5.475, 9.475]um` — clearing `Q3_E`'s own
`x=6.32um` and `Q3_B`'s own `x=8.63um` by `0.845um` each. A first attempt
at `ring_gap_um: 3.2` was rejected by `gen-compose`'s own crossing-clearance
check at exactly `0.445um` against a `0.485um` requirement, so the width is
measured, not guessed.

| Net | Tap mechanism | Promoted pad |
|---|---|---|
| `ec` | new leg branching north out of `Q3_E` through `GAP_N`, then west | `stub_ec.PAD`, `x=-5.0, y=10.0` |
| `vss` | new leg branching north out of `Q3_B` through `GAP_N`, then east | `stub_vss.PAD`, `x=23.5, y=9.0` |

Opposite directions on separate lanes, so neither riser crosses the other's
run. `Q3_E`/`Q3_B` both sit `2.67um` below the block's own north edge
(`y=5.5`, bbox `y1=8.17`), so each riser is a short straight run out through
the opening that crosses no other pad. Both stubs are plain declare-only
li1 (`promo_stub.gds`), no PDK awareness needed.

### What the opening costs, stated plainly

The collector ring is now a C-shaped conductor, not a closed loop: its
substrate-isolation function is interrupted for the `4.0um` of the N-side
opening. That is a real floorplan change, not a free one. It costs this
cell nothing it currently *has*, though — the ring is already not strapped
to `VSS` at all (see "Routing" above), and `klt extract` recovers it as the
same floating `vsubs` node either way. Once the installed `klt` carries
#1894's fix, the right move is to revisit this: close the ring again and
promote `vss` through a real `COLL_*` tap instead.

### Evidence: this changed no device, no net, and no verdict

Only the ring geometry and the two new stubs are new. Everything the
verification chain measures is byte-for-byte what it was before:

| | before #61 | after #61 |
|---|---|---|
| `klt drc` | clean, 0 violations | clean, 0 violations |
| `klt extract` | 8 devices, 3 nets, 3 pins | 8 devices, 3 nets, 3 pins |
| extracted netlist `sha256` | `52326d72…` | `52326d72…` (identical) |
| `klt lvs` | `mismatch`, 21 (16 `device.unmatched` + 5 `net.unmatched`) | `mismatch`, 21 (16 + 5) — unchanged |

The extracted-netlist hash being *identical* is the strongest available
evidence that the ring opening merged nothing and broke nothing: the
`ec`/`vss`/`vsubs` split, and all 8 devices' `Q$N vsubs vss ec` topology,
come back exactly as before. The LVS mismatch is the same pre-existing,
well-isolated collector-strap gap documented under "Verification" — **not**
something this change introduced, and not something it was scoped to fix.

**Verified against a downstream target, not just eyeballed.**

```
python3 layout/bin/check-promotion.py layout/bias_core_pnp8_leg/cell.json
```

places this cell's own composed GDS as a `blocks[].cell` reference plus one
dummy pad per newly-promoted pin, and routes a 2-pin net from each to its
dummy: `unrouted_nets: []` for both, and the downstream-composed stream is
itself `klt drc`-clean. Evidence:
`downstream-check.request.json`/`.response.json`/`.drc.json`/`.gds` next to
this file. Re-run the whole chain with
`python3 layout/bin/compose-cell.py layout/bias_core_pnp8_leg/cell.json --check`.

### Upstream status (as of 2026-09-16)

[`#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894) **is
closed as COMPLETED**, by
[PR #1930](https://github.com/2AMLogic/klayout-tools/pull/1930) (merged
`2026-09-16T06:44:04Z`), which *did* land a real fix: `COLL_*` diffusion-role
via-drops now draw an actual `licon`/`mcon` contact instead of falling
through to "nothing to do". **This repo cannot use it yet.** The installed
toolchain is `klt 0.5.0+gba213c617b4e`, built from `ba213c61`
(`2026-09-15T23:03:10Z`) — about eight hours *before* that merge — and its
`_resolve_via_drop_layer()` still has the pre-fix fallthrough, confirmed by
reading the installed source. So the collector strap remains open here, and
the ring opening above is the correct answer *for the pinned toolchain*, not
a permanent one.
