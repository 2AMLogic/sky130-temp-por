# layout

Physical layout evidence for sky130-temp-por, built with `klayout-tools`
(`klt`) against the sky130 open PDK. See `layout/pdk.json` for the PDK/tool
pin.

## `klt` version pin: the commit, not the semver, is authoritative (issue #51)

`layout/pdk.json` carries two fields for the `klt` build this evidence was
generated/verified against: `klt_version_pin` (the full `version` string
`klt version --format json` reports, e.g. `0.4.0+gba213c617b4e`) and
`klt_commit_pin` (just the `git_commit` half of that same build, e.g.
`ba213c617b4e`). **`klt_commit_pin` is the one that actually identifies the
build** — the leading semver is not reliable on its own. The same commit can
be packaged under more than one semver (a local `+g<hash>` build bumps
`package_version` independently of `git_commit`), and the reverse has also
been observed in a churning toolchain (`klt_version_pin` moving *backwards*
in semver order between sessions while `open_pdks_commit` held still — see
`2AMLogic/sky130-trng`'s own `layout/pdk.json` `_comment` for a worked
example). A host whose installed `klt` happens to share a semver prefix with
the pin but not the commit is still stale, and vice versa.

`layout/bin/_klt_common.py`'s `check_klt_pin()` runs `klt version --format
json` once per `layout/bin/compose-cell.py` invocation and compares the
installed build's `git_commit` against `klt_commit_pin`. A mismatch prints a
**warning**, not a hard failure — the pin is "a provenance pin, not a hard
gate" (`layout/pdk.json`'s own `_comment`), and re-verifying against a newer
`klt` is expected to happen and should simply update the pin plus the
affected evidence directories together. The point of the warning is to make
a stale install self-report plainly, up front, instead of surfacing many
steps later as a confusing "unrecognized key(s)" error deep inside a `klt
gen-compose` call the way it did in issue #51 — at that point the installed
`klt` predated `connectivity[].layer_role` entirely and simply did not
recognize the key.

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

Issue #61 added `pins[]` promotions for `ec` and `vss` (this cell had none
at all before), via a `params.ring_gap_side` opening in the collector ring —
device count, net count, LVS verdict, and the extracted netlist's own
`sha256` are all unchanged by it. See that cell's own README.

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

Issue #61 added a `pins[]` promotion for `vss` alongside the existing
`na`/`er`, via the same `params.ring_gap_side` opening technique — device
count, net count, LVS verdict, and the extracted netlist's own `sha256` are
all unchanged by it. See that cell's own README.

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

## `bias_core_startup`: the startup kick chain (issue #38, part of #34)

[`layout/bias_core_startup/`](bias_core_startup/README.md) lays out
`design/netlist/bias_core.spice`'s `XKS0..XKS4`/`XKA`/`XKAN`/`XKPD`/`XKICK`
device group — a 5-stage diode-connected NFET stack (`XKS0..XKS4`, chained
`VDD -> KS1 -> KS2 -> KS3 -> KS4 -> NKG`) plus the kick node's own
PFET/NFET pull-down network (`XKA`/`XKAN`/`XKPD`) and the NFET that injects
the kick pulse onto `PG` (`XKICK`) — as a fifth standalone proof cell, all 9
devices `sky130_fd_pr__nfet_g5v0d10v5`/`sky130_fd_pr__pfet_g5v0d10v5`: one
long single-row floorplan with per-net `connectivity[].layer_role`
(`bias_core_settle_flag`'s own technique) moving one bundle net (`nkm`) to a
second metal plane so it clears another net's own li1 detour.

**`klt drc`: clean, 0 violations.** **`klt extract`: 9 devices, 10 nets.**
**`klt lvs` against `design/netlist/bias_core.spice`'s own device cards:
`match` — 9/9 devices, 10/10 nets, 10/10 pins, 0 mismatches.** The second
sub-block in this repo (after `bias_core_settle_flag`) to reach a full LVS
match — none of these 9 devices are the `sky130_fd_pr__pnp_05v5_W3p40L3p40`
device `2AMLogic/klayout-tools#1894` blocks, so this group was free to go
the whole way, and it carries the same `hvi`-marker disclosure
`bias_core_settle_flag` does
([`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912)).
An earlier draft hit a new, distinct `gen-compose` gap — promoting several
of an earlier stage's `pins[]` ports through a bundle net at a different
`routing.layer_role` via a `"stages"`/`blocks[].from_stage` two-pass
composition reproducibly failed via-drop with spurious same-layer spacing
violations, where the identical ports routed directly in a single pass with
a per-net `layer_role` did not — filed as
[`2AMLogic/klayout-tools#1917`](https://github.com/2AMLogic/klayout-tools/issues/1917);
see that cell's own README for the full repro. Not blocking: the single-pass
technique is what landed.

## `bias_core_mirror_amp`: the current-mirror + error-amp stack (issue #35, part of #34)

[`layout/bias_core_mirror_amp/`](bias_core_mirror_amp/README.md) lays out
`design/netlist/bias_core.spice`'s `XMP1`/`XMP2`/`XMP3`/`XMPBN`/`XMBN`/
`XMBN2`/`XMBP`/`XMPIB`/`XMPT`/`XMI1`/`XMI2`/`XML1`/`XML2`/`XMS2N`/`XMS2P`
device group — the four PFET mirror legs off `PG`, the NFET/PFET bias-mirror
pair that sets `NBG`/`PB`, the `PB`-gated bias-current outputs (`IBIAS`,
`NT`), and the PFET-input error amp with its NFET mirror load and the
`XMS2N`/`XMS2P` pair that closes the loop back onto `PG` — as a sixth
standalone proof cell, 15 devices (10x `sky130_fd_pr__pfet_g5v0d10v5` + 5x
`sky130_fd_pr__nfet_g5v0d10v5`). Same two-row CMOS shape as
`bias_core_settle_flag`, scaled up: a 10-wide PMOS row on a 9.0um column
pitch with a per-device `guard_ring` nwell tap island abutted at the same
0.10um nwell overlap, a 5-wide NMOS row, and nine routed nets split across
three metal planes by `connectivity[].layer_role` — plus, for `n2`, two
planes within one net by `connectivity[].legs[].layer_role`, the first use
of the per-*leg* form in this repo.

**`klt drc`: clean, 0 violations.** **`klt extract`: 15 devices, 13 nets.**
**`klt lvs` against `design/netlist/bias_core.spice`'s own device cards:
`match` — 15/15 devices, 13/13 nets, 13/13 pins, 0 mismatches.** The third
sub-block in this repo to reach a full LVS match, and the largest; it
carries the same `hvi`-marker disclosure the other two do
([`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912)).
No new tool gap was hit building it.

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

**Update (issue #61) — #1894 is fixed upstream, but the pinned `klt` predates
the fix.** The issue **closed as COMPLETED on 2026-09-16**, by
[PR #1930](https://github.com/2AMLogic/klayout-tools/pull/1930) (merged
`2026-09-16T06:44:04Z`), and the fix is a *real* one, not just a guard:
`_resolve_via_drop_layer()` gained a diffusion-role branch that drops
through the deck's contact to `metals[0]` and ladders up, so a `COLL_*` port
now receives an actual `licon`/`mcon` contact instead of falling through to
"already covered, nothing to do". Finding 2 follows from finding 1 and is
covered by the same fix.

**None of that is usable in this repo yet.** The installed toolchain is
`klt 0.5.0+gba213c617b4e`, built from `ba213c61` (`2026-09-15T23:03:10Z`) —
roughly eight hours *before* that merge. Confirmed by reading the installed
`gen_compose_routing.py`: `_resolve_via_drop_layer()` still has the pre-fix
`return None, None` fallthrough for any non-metals-stack, non-poly port. So
every collector-strap statement recorded above and in the two PNP cells'
own READMEs still holds for the evidence this repo commits today. Closing
the strap for real is gated on a `klt` upgrade plus a full re-run of both
cells — worth doing, since it is the one remaining cause of their LVS
mismatch, but it is a toolchain bump affecting every committed artifact in
`layout/`, not a cell-level edit.

**Update (issue #56):** the installed `klt` build also actively *detects* a
closed guard/collector ring and refuses any leg targeting one of the
array's own non-tap ports (`Q*_B`/`Q*_E`) once that block also carries an
unopened `TAP_*`/`COLL_*` ring — "a route to its non-tap port would cross
the ring's own metal loop and merge this net with the ring's tap net"
(citing this same issue #1527 that #56's own `na`/`pg`/`pb`/`vdd`/`vss`/`n2`
promotions on `bias_core_mirror_amp`/`bias_core_settle_flag` hit and
resolved with a west-edge metal stub). That fix does not transfer here: the
rejection fires on the very *first* leg leaving the block, before any
question of tap-point placement, because `bjt_array`'s ring had no
`GAP_*` opening (`params.ring_gap_side` unset in both cells) — a
defensive improvement (this is exactly the silent-short failure mode
finding 2 above describes, now caught instead of silently drawn), but it
meant `bias_core_pnp8_leg`'s `ec`/`vss` and `bias_core_xq1_xqr`'s `vss` —
all of which the design's own device cards route outside this device
group — had no `pins[]` promotion, and #56 could not add one without either
the upstream collector-strap fix or a `ring_gap_side` floorplan change to
one (or both) of these cells.

**Resolved by issue #61, via the floorplan route.** Since the upstream fix
is merged but not installed (above), both cells were regenerated with a
`params.ring_gap_side: "N"` opening and their nets promoted out through it
— `ec`/`vss` on `bias_core_pnp8_leg`, `vss` on `bias_core_xq1_xqr`. Both
cells' extracted netlists come back **byte-identical** to their pre-#61
committed evidence (same `sha256`, same device/net/pin counts, same LVS
verdict), so the opening merged nothing; and both promotions are verified
downstream by `layout/bin/check-promotion.py` (`unrouted_nets: []`, clean
downstream `klt drc`). Each cell's own README documents the opening and
what it costs — the ring is now a C-shaped conductor, so its isolation is
interrupted for the width of the opening. Revisit and close the rings again
once `klt` is upgraded past #1930.

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
   This is an open caveat on both of this repo's LVS-matching cells
   (`bias_core_settle_flag` and `bias_core_startup`).
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
5. **Promoting an earlier stage's `pins[]` ports through a bundle net at a
   different `routing.layer_role`, via a `"stages"`/`blocks[].from_stage`
   two-pass composition, reproducibly fails via-drop** with spurious
   same-layer spacing violations against the promoting stage's own
   flattened geometry — every pairwise candidate leg among the promoted
   ports fails, at coordinates resolving to the ports' own reported
   positions. The *identical* target ports, routed directly in a single
   `gen-compose` pass with a per-net `connectivity[].layer_role` override
   instead of `from_stage`, route and DRC clean on the same underlying
   device geometry —
   [`2AMLogic/klayout-tools#1917`](https://github.com/2AMLogic/klayout-tools/issues/1917).
   `bias_core_startup` hit this building an early draft; its own README
   records the repro and the working single-pass alternative.

And one more, found building issue #61's `ec`/`vss` promotions:

6. **The closed-guard/collector-ring rejection is plane-agnostic**, so the
   only way to give a net inside a ringed block an external pad is to
   *break the ring*. `gen-compose` decides the rejection from block/port
   identity alone, never from the level the leg would be drawn on:
   verified by composing a leg from a `bjt_array`'s `Q0_B` (li1, 67/20) to
   a stub outside the array with the backbone on `metal3` (met2, 70/20) —
   two via levels above the ring's own diffusion role (65/20), where no
   merge is physically possible, and where the via-drop ladder's landing
   pads all sit at the port's own position *inside* the ring. Rejected
   anyway, with the same message and the same three remedies. Of those
   remedies, "route to the ring's own tap port" does not apply (the escaping
   net is a device net, not the ring's tap net), and the other two both
   destroy the ring. Filed generically as
   [`2AMLogic/klayout-tools#1960`](https://github.com/2AMLogic/klayout-tools/issues/1960);
   both PNP cells pay for it with a `ring_gap_side` opening (see #61 above).

## What's next

Per issue #36, this fleet prefers landing DRC-clean/LVS-blocked increments
(isolated to a known, upstream-filed gap) over waiting on the upstream fix —
`bias_core_pnp8_leg`, `bias_core_xq1_xqr`, and `bias_core_passives` all ship
that way; `bias_core_settle_flag`, `bias_core_startup`, and
`bias_core_mirror_amp` land DRC- and LVS-clean outright. Every `bias_core`
device group now has its own proof cell; the full-cell assembly is the
remaining follow-on increment, tracked as a sibling sub-issue of
[#34](https://github.com/2AMLogic/sky130-temp-por/issues/34); `temp_core`,
`por_comparator`, `por_output_chain`, and `temp_por_top` are tracked from
[#4](https://github.com/2AMLogic/sky130-temp-por/issues/4).
