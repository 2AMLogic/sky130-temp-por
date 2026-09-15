# layout

Physical layout evidence for sky130-temp-por, built with `klayout-tools`
(`klt`) against the sky130 open PDK. See `layout/pdk.json` for the PDK/tool
pin.

**Status (issue #30, this increment): the recipe lands, proven on a real
`bias_core` sub-block.** `layout/bin/compose-cell.py` and
`layout/bin/_klt_common.py` are ported byte-for-byte from
[`2AMLogic/sky130-trng`](https://github.com/2AMLogic/sky130-trng)'s own
`layout/bin/` (a shared, design-agnostic driver for the
`klt gen` → `klt gen-compose` → `klt drc` → `klt extract` → `klt lvs` chain —
see that script's own module docstring for the full contract). Their
docstrings still cite `sky130-trng`'s own issue numbers (`#22`, `#27`, `#49`,
`#1492`, ...) — those refer to *that* repo's history, not this one; nothing
in this repo's own numbering corresponds to them. Only `layout/bias_core_pnp8_leg/`
is new to this repo.

## `bias_core_pnp8_leg`: the first real sub-block

[`layout/bias_core_pnp8_leg/`](bias_core_pnp8_leg/README.md) lays out
`design/netlist/bias_core.spice`'s `XQ8A..XQ8H` device group — the "8:1 PNP
emitter-count ratio" leg `design/bias_core.md`'s sizing section describes —
as a standalone proof cell, using `klt gen bjt_array`'s common-centroid
matched-array generator (one call draws the whole matched, guard-ringed
group; no manual multi-block placement the way a digital gate needs).

**`klt drc`: clean, 0 violations.** **`klt extract`: 8 devices, 3 nets.**
**`klt lvs` against `design/netlist/bias_core.spice`'s own device cards:
mismatch** (0/8 devices, 0/2 nets) — but a single, well-isolated, understood
cause, not a wiring error in this cell's own `cell.json`: the base ↔ emitter
topology extracts **exactly right** for all 8 devices (confirmed by a reduced
probe that excludes the collector, see below); the only gap is the
collector-ring-to-`VSS` strap the schematic's own device cards require
(`XQ8A VSS VSS EC ...` — collector and base both explicitly tied to `VSS`).
That gap traces to a real `klt gen-compose` limitation, not a cell.json bug —
see "Known klt gaps hit building this recipe" below,
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894).

## Known klt gaps hit building this recipe

Filed generically at
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)
per this repo's CLAUDE.md friction protocol (describing the tool gap, not
this design). Two related findings, both isolated with reduced repro cells
(an 8-unit `bjt_array`, `rows=2 cols=4 ratio=8 common_centroid
add_collector_ring=true`, with two same-block self-nets — a base bus and an
emitter bus, `routing.cross_block_layer_role` configured per
`docs/cli/gen-compose.md`'s own worked example for exactly this shape):

1. **A `bjt_array` collector-ring port (`COLL_N`/`COLL_S`/`COLL_E`/`COLL_W`,
   declared on the diffusion role, not `li1`) never receives a real
   `licon`/`mcon` contact from `klt gen-compose`'s via-drop, at any
   `routing.layer_role` tried.** The leg reports `routed: true`, and at the
   `"metal2"`/`"metal3"` role pair `klt drc` reports clean — but `klt
   extract` always recovers the collector as a separate, unstrapped `vsubs`
   node, never merged with the net it was wired to. (The diffusion region
   itself *is* correctly extracted as one shared node across all 8 units —
   confirming the guard ring's own physical continuity — only the strap up
   to routing metal is missing.) At the base `"metal"` (`li1`) role, the
   *same* connectivity additionally produces 10 reproducible `li1.space.1`
   violations from routing to `COLL_*` alone (no second net involved).
2. **Routing that same collector-ring net *and* a second same-block net
   (the emitter bus) together, at the `"metal2"`/`"metal3"` role pair,
   silently shorts the two unrelated nets together** — `klt extract` merges
   the base and emitter nodes into one — while `klt gen-compose` still
   reports both nets fully `routed: true` and `klt drc` still reports clean.
   Excluding the collector-ring pins from the base net's connectivity (this
   repo's own shipped `cell.json`) avoids this; the base and emitter nets
   then extract correctly separate, per-device, matching the schematic
   exactly.

Revisit `layout/bias_core_pnp8_leg/`'s collector strap once that issue is
resolved upstream, at which point a real base+collector+emitter LVS match
should be possible without changing this cell's own floorplan.

## What's next

`temp_core`, `por_comparator`, `por_output_chain`, `temp_por_top`, and the
rest of `bias_core` itself (the PFET/NFET mirror stack, the kick chain, the
Miller caps, the bias resistors) are follow-on increments once the
collector-strap gap above is closed or worked around — tracked from
[#4](https://github.com/2AMLogic/sky130-temp-por/issues/4).
