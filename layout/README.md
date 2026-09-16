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
in this repo's own numbering corresponds to them. `layout/bias_core_pnp8_leg/`
and `layout/bias_core_xq1_xqr/` are new to this repo.

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

## `bias_core_xq1_xqr`: the matching 1x reference PNPs (issue #36, part of #34)

[`layout/bias_core_xq1_xqr/`](bias_core_xq1_xqr/README.md) lays out
`design/netlist/bias_core.spice`'s `XQ1` and `XQR` devices — the matching 1x
reference unit for `bias_core_pnp8_leg`'s 8:1 group, and the separate
`VREF`-leg unit, respectively — as a second standalone proof cell, using one
shared-ring `klt gen bjt_array` call (`rows=1 cols=2 ratio=1`) rather than
two independently-ringed blocks (bussing a net between two closed guard
rings does not route — see that cell's own README "Routing" section).

**`klt drc`: clean, 0 violations.** **`klt extract`: 2 devices, 4 nets.**
**`klt lvs` against `design/netlist/bias_core.spice`'s own device cards:
mismatch** (0/2 devices, 0/3 nets) — the same single, well-isolated cause as
`bias_core_pnp8_leg`: base and each device's own emitter extract exactly
right, and the only gap is the collector-ring-to-`VSS` strap
[`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)
blocks.

## `bias_core_passives`: the bias/ratio resistors and Miller caps (issue #37, part of #34)

[`layout/bias_core_passives/`](bias_core_passives/README.md) lays out
`design/netlist/bias_core.spice`'s `XRT`/`XR1`/`XR2`/`XRZ`/`XCC`/`XCOK`
device group — the bias/ratio resistor network (4x
`sky130_fd_pr__res_xhigh_po`, each its own distinct length) and Miller
compensation caps (2x `sky130_fd_pr__cap_mim_m3_1`) — as a third standalone
proof cell, using one single-instance `klt gen res_array`/`cap_array` call
per device (no matched array: none of these 6 devices are meant to match
each other).

**`klt drc`: clean, 0 violations.** **`klt extract`: 6 devices, 11 nets.**
**`klt lvs` against `design/netlist/bias_core.spice`'s own device cards:
mismatch** (0/6 devices, 0/11 nets) — **not** the `bias_core_pnp8_leg`/
`bias_core_xq1_xqr` collector-strap gap (confirmed: this device group's own
`VSS`↔`vsubs` naming makes no difference to the result). Two different,
newly-found `klt lvs`/`klt extract` gaps block it instead — see that cell's
own README "Verification" section for the full diagnosis,
[`2AMLogic/klayout-tools#1907`](https://github.com/2AMLogic/klayout-tools/issues/1907)
and
[`2AMLogic/klayout-tools#1908`](https://github.com/2AMLogic/klayout-tools/issues/1908).

## `bias_core_settle_flag`: the settle-flag output stage (issue #39, part of #34)

[`layout/bias_core_settle_flag/`](bias_core_settle_flag/README.md) lays out
`design/netlist/bias_core.spice`'s `XMPOK`/`XMOKA`/`XMOKB`/`XMOL1`/`XMOL2`/
`XMOKC`/`XMOK2`/`XMOK2P`/`XMO1P`/`XMO1N` device group — the settle-flag
comparator/driver chain that produces `bias_core`'s own `BIAS_OK` output, 10
devices (5x `sky130_fd_pr__pfet_g5v0d10v5` + 5x
`sky130_fd_pr__nfet_g5v0d10v5`, no two of them the same size) — as a fourth
standalone proof cell: a two-row CMOS floorplan (NMOS row, signal channel,
PMOS row) with per-device `guard_ring` body-tie islands abutted at a 0.10um
nwell overlap, and all eight routed nets split across three metal planes by
`connectivity[].layer_role` so the whole cell composes in a single
`klt gen-compose` pass.

**`klt drc`: clean, 0 violations.** **`klt extract`: 10 devices, 11 nets, 11
pins.** **`klt lvs` against `design/netlist/bias_core.spice`'s own device
cards: `match` — 10/10 devices, 11/11 nets, 11/11 pins, 0 mismatches.** This
is **the first sub-block in this repo to reach a full LVS match**: none of
the three gaps blocking the sibling cells touches a MOS device, so this group
was free to go the whole way.

It carries one disclosure of its own, which no step of the chain can see:
`klt gen` cannot draw sky130's `hvi` (75/20) thick-oxide marker, so these 5V
`g5v0d10v5` devices are drawn in the 1.8V domain's geometry, `klt drc` reads
no `hvi` rule, and `klt lvs` deliberately maps both flavours onto one device
class — so the match above is exactly as clean as it would be with the marker
present. Filed as
[`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912);
see that cell's own README for what the match does and does not assert.

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

Revisit `layout/bias_core_pnp8_leg/`'s and `layout/bias_core_xq1_xqr/`'s
collector strap once that issue is resolved upstream, at which point a real
base+collector+emitter LVS match should be possible without changing either
cell's own floorplan.

Two more, both found building `layout/bias_core_settle_flag/` (the first MOS
cell in this repo) and both filed the same way:

3. **`klt gen` can draw no thick-oxide/medium-voltage marker on the sky130
   family**, for any `voltage_flavor` value, even though the curated sky130
   *extraction* deck declares the matching `MOSFlavour(marker=(75, 20),
   flavour="hvi")` and `pdk_models` binds it to the real `g5v0d10v5`
   subcircuits. Since no `klt drc` rule reads `hvi`, and `klt lvs` maps both
   flavours onto one device class, a 5V design drawn in the 1.8V domain
   passes the whole chain clean —
   [`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912).
   This is the one open caveat on this repo's only LVS-matching cell.
4. **A via-ladder's intermediate landing pad can silently short an unrelated
   net.** `gen-compose`'s route-vs-route check deliberately excludes a
   multi-hop ladder's intermediate pads (they are not on the leg's own
   plane) and names `klt drc` as the backstop — but the failure is a *merge*,
   which no rule deck can see. Reproduced in three blocks with `klt drc`
   completely clean and `klt extract` reporting the two nets as one `a|b`
   node —
   [`2AMLogic/klayout-tools#1913`](https://github.com/2AMLogic/klayout-tools/issues/1913).
   `bias_core_settle_flag` hits this for real when its supply rail is left to
   the automatic spanning tree; its own README records the measurement.

## What's next

Per issue #36, this fleet prefers landing DRC-clean/LVS-blocked increments
(isolated to a known, upstream-filed gap) over waiting on the upstream fix —
`bias_core_pnp8_leg`, `bias_core_xq1_xqr`, and `bias_core_passives` all ship
that way; `bias_core_settle_flag` is the first that does not have to, and
lands DRC- and LVS-clean. The remaining `bias_core` device groups (the
PFET/NFET mirror/error-amp stack, the startup kick chain) and the full-cell
assembly are follow-on increments tracked as sibling sub-issues of
[#34](https://github.com/2AMLogic/sky130-temp-por/issues/34); `temp_core`,
`por_comparator`, `por_output_chain`, and `temp_por_top` are tracked from
[#4](https://github.com/2AMLogic/sky130-temp-por/issues/4).
