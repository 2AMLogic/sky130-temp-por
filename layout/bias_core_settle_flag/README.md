# `bias_core_settle_flag`

Standalone proof-of-concept layout for `design/netlist/bias_core.spice`'s
`XMPOK`/`XMOKA`/`XMOKB`/`XMOL1`/`XMOL2`/`XMOKC`/`XMOK2`/`XMOK2P`/`XMO1P`/
`XMO1N` device group — the settle-flag comparator/driver chain that produces
`bias_core`'s own `BIAS_OK` output. Part of #34 (device-group split of
`bias_core` layout work), decomposed as #39, itself a follow-on from #30/#4.
Follows the compose-cell recipe `layout/bias_core_pnp8_leg/` (#30/PR #33)
established.

**This is the first sub-block in this repo to reach a full `klt lvs`
`match`** — 10/10 devices, 11/11 nets, 11/11 pins, 0 mismatches, against
`design/netlist/bias_core.spice`'s own device cards. The three earlier
sub-blocks (`bias_core_pnp8_leg`, `bias_core_xq1_xqr`, `bias_core_passives`)
each land DRC-clean but LVS-blocked on an upstream `klayout-tools` gap; none
of those gaps touch a MOS device, so this group was free to go the whole way.
It is not free of a caveat of its own, though — see "The one thing this
layout does not yet say" below, and read it before treating the match as
sign-off.

| Device | Ports (device-card order: `D G S B`) | Size |
|---|---|---|
| `XMPOK` | `TOK` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=1` |
| `XMOKA` | `NOKO` `NA` `TOK` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=8` |
| `XMOKB` | `NOKL` `NBTOP` `TOK` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=8` |
| `XMOL1` | `NOKL` `NOKL` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=2` |
| `XMOL2` | `NOKO` `NOKL` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=2` |
| `XMOKC` | `NOKO` `NKG` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=1` `W=2` |
| `XMOK2` | `NOKX` `NOKO` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=2` |
| `XMOK2P` | `NOKX` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=1` |
| `XMO1P` | `BIAS_OK` `NOKX` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=1` |
| `XMO1N` | `BIAS_OK` `NOKX` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=0.5` `W=4` |

Eleven nodes cross this group's boundary: `VDD`, `VSS`, `TOK`, `PB`, `NA`,
`NBTOP`, `NOKO`, `NOKL`, `NKG`, `NOKX`, `BIAS_OK`. `NBTOP` (`XMOKB`'s gate)
is one more than #39's own Test Plan net list names — the issue body's device
list carries it, its Test Plan checklist does not; the device cards are the
authority and `NBTOP` is a real eleventh port, not an extra.

## Recipe

Each device is its own single-instance `klt gen mos_array` call (`rows=1
cols=1 dummy=0 gate_contact=true`, `flavor` per device) rather than a matched
array — no two of these ten devices share a `W`/`L`, and none of them are
meant to match each other. `layout/bin/compose-cell.py
layout/bias_core_settle_flag/cell.json` runs the full `gen` → `gen-compose` →
`drc` → `extract` → `lvs` chain and writes every step's response next to this
file, same shape as the sibling recipes. Re-verify with:

```
python3 layout/bin/compose-cell.py layout/bias_core_settle_flag/cell.json --check
```

`reference.spice` is a hand-extracted, byte-for-byte copy of
`design/netlist/bias_core.spice`'s own ten device cards (continuation lines
included), wrapped in an 11-port `.subckt` — not an xschem export, since the
design's own `.subckt bias_core` is the whole cell, not this group alone.

## Floorplan

`placement.strategy: "explicit"`, in the standard two-row CMOS shape. Drawn
extent 44.3 x 32.7 um.

- **NMOS row** along `y=0`, `orientation: "none"` — sources face west, drains
  east, gates north into the channel.
- **PMOS row** with its bottom edge at `y=14.0`, `orientation: "mirror_y"` so
  gates face south into the same channel. `moka` is `"rotate_180"` instead:
  its source (`TOK`) has to face **east**, back toward `mpok`/`mokb`, and
  `rotate_180` is the orientation that moves the source to the east edge
  while still turning the gate south.
- Each PMOS origin is derived from its own device height (`Y = 14.0 + w +
  0.82 + 0.15`), so the `W=1` and `W=8` devices' gates all land on one
  `y=14.36` gate row even though their bodies are 7um apart in height.
- **Bodies are tied by abutment, not by enclosure.** A device nested inside a
  ring is body-tied but unroutable
  ([`2AMLogic/klayout-tools#1493`](https://github.com/2AMLogic/klayout-tools/issues/1493)),
  so `mos_array`'s own `add_guard_ring` is not used. Each PMOS instead gets a
  separate `guard_ring` (`add_well: true`) tap island placed so the two
  nwells **overlap by 0.10um** — merging them into one electrical node, which
  is what puts every PMOS bulk on `vdd` — while their `li1` stays 0.20um
  apart, clear of sky130's 0.17um `li1` spacing floor. Distinct nwell islands
  are kept >= 1.27um apart (`nwell.space.1`). This is
  [`2AMLogic/sky130-trng`](https://github.com/2AMLogic/sky130-trng)'s
  `layout/ro_buf/` technique, unchanged; the 0.10/0.20 pair is its numbers,
  re-derived here against these devices' own bboxes.
- `moka`'s tap island sits **north** of it rather than west, because a west
  island would sit exactly where `noko`'s `li1` drop out of `moka`'s
  west-facing drain has to run. Same 0.10um overlap / 0.20um `li1` clearance,
  rotated 90 degrees.
- Two `guard_ring` (`add_well: false`) psub tap islands tie the substrate to
  `vss`. Without them the five NMOS bulks stay on the deck's synthesized
  global `vsubs` net, separate from the routed `vss` net, and LVS cannot
  match (that is exactly the shape of `bias_core_pnp8_leg`'s own
  collector-tie mismatch). With them, `klt extract` reports **no `vsubs` net
  at all** — the substrate and the `vss` routing are one node, named `vss`.

## Routing

Three planes, assigned **per net** via `connectivity[].layer_role`
([`klayout-tools#1655`](https://github.com/2AMLogic/klayout-tools/issues/1655)),
chosen so that no two nets sharing a plane ever cross — which is what lets
the whole cell compose in a single `klt gen-compose` pass instead of the
multi-stage `"stages"` shape a one-plane floorplan would force:

| Plane | Nets | Why they cannot collide |
|---|---|---|
| `"metal"` (li1) | `nokl`, `noko`, `nokx`, `bias_ok` | Each is confined to its own column of the channel; their x ranges are disjoint |
| `"metal2"` (met1) | `vdd`, `vss` | One lane above the PMOS row (`y=26.5`), one below the NMOS row (`y=-6.0`) |
| `"metal3"` (met2) | `tok`, `pb` | `tok` stays above the PMOS row (`y>=15.47`), `pb` below it (`y<=14.36`) |

The rails are the reason for the split: `vdd` has to reach five tap islands
and three sources spread across the full 44um width, and on li1 every one of
those legs would cross a signal net. On met1 the backbone runs over the
blocks and drops to each pin's own li1 pad through a via at that pin's
position, so it crosses nothing on any plane it shares.

Every leg is steered explicitly through `connectivity[].legs[]`
([`klayout-tools#1529`](https://github.com/2AMLogic/klayout-tools/issues/1529))
rather than left to the automatic nearest-first spanning tree.
`compose.response.json` records `routed: true` for all eight nets **and** for
every named leg (a named leg can be rejected while its net still routes
another way, so `nets[].legs[]` is the field that matters, not just
`nets[].routed`).

**That is load-bearing, and the failure it avoids is silent.** Measured, by
rebuilding this exact cell.json with `vdd`'s `legs[]` removed and nothing else
changed: the nearest-first tree draws a `vdd` leg from `mpok`'s source
straight to `mokb`'s tap island, and that met1 backbone runs through the met1
landing pad `tok`'s own `"metal3"` via-ladder drops at `mpok`'s drain
`(4.63, 15.47)`. `klt gen-compose` still reports **every** leg `routed: true`
with `unrouted_nets: []`; `klt drc` reports 5 `met1.space.1` violations — all
of them near the *tap islands* (`x ≈ -1.0`, `7.5`, `26.0`, `34.5`, `35.0`),
none at the merge; and `klt extract` collapses to 10 nets whose ninth reads
**`tok|vdd`** — one polygon spanning `x` `-1.33 … 36.42`, `y` `15.26 … 25.01`,
i.e. the rail and the signal shorted together. That short is a *merge*, not a
spacing violation, so no rule deck can see it: filed generically, with a
three-block minimal repro in which `klt drc` is completely clean, as
[`2AMLogic/klayout-tools#1913`](https://github.com/2AMLogic/klayout-tools/issues/1913).
Until that closes, a cell composing a rail on one plane over signal nets that
ladder through it must steer the rail explicitly and verify connectivity from
`klt extract`'s own net list — which is what the LVS `match` below does.

`na`, `nbtop` and `nkg` touch exactly one port in this device group, so each
is a `pins[]` declare-only top-level pin — a label on the gate pad's own
already-drawn li1, no metal routed — rather than a `connectivity[]` net.

### Boundary-aware placement of `NOKX` and `BIAS_OK`

Both are nodes the full-cell assembly (#40) has to reach, and #39's curation
notes that `NOKX` is shared with `XCOK` in the passives sub-block (#37), so
it needs the same boundary awareness `BIAS_OK` does rather than being treated
as purely internal. Both are labelled, top-level li1 pins in the extracted
netlist, and both were deliberately routed with a long, straight, unobstructed
run on the **east** side of the cell for #40 to tap by coordinate
(`blocks[].cell.ports[]`):

- `bias_ok` — a vertical li1 run at `x=42.0`, spanning `y=2.0` to `y=15.47`,
  east of every block in the cell (the drawn extent ends at `x=42.085`).
- `nokx` — a vertical li1 run at `x=33.5`, spanning `y=1.0` to `y=15.47`,
  in the empty channel between `mok2`/`mok2p` and `mo1n`/`mo1p`.

Neither is a via-hop away from anything else, so #40 can tap either at any
`y` in those ranges on li1, or one hop up on met1.

## Verification

Reproduced with `--check` (rebuild into a temp dir, diff the verdict-bearing
fields) at the `klt` build `layout/pdk.json` pins.

- **`klt drc --deck sky130`: clean, 0 violations.**
- **`klt extract --deck sky130`: 10 devices, 11 nets, 11 pins.**
  `device_counts` reads `{"nfet": 5, "pfet": 5}`. The eleven nets are exactly
  the eleven boundary nodes — `bias_ok`, `na`, `nbtop`, `nkg`, `nokl`,
  `noko`, `nokx`, `pb`, `tok`, `vdd`, `vss`, each a named pin, with no
  leftover anonymous `$N` node and no separate `vsubs`. Per-net device
  terminal counts match the schematic one for one: `vss` 10 (five sources +
  five bulks), `vdd` 8 (three sources + five bulks), `nokl`/`noko`/`nokx` 4,
  `tok` 3, `bias_ok`/`pb` 2, `na`/`nbtop`/`nkg` 1.
- **`klt lvs` against `reference.spice`: `match`** — 10/10 devices, 11/11
  nets, 11/11 pins, `mismatch_count: 0`, `error_count: 0`.

Two things the match does **not** assert, both worth stating so nobody reads
more into it than it carries:

1. **Source/drain assignment is not preserved, and is not meant to be.**
   `klt extract` reads `XMOKA` back as `M$10 tok na noko vdd` — drain and
   source swapped relative to the device card's `NOKO NA TOK VDD` — because
   that device is the `"rotate_180"` one and the extractor names the terminals
   from geometry. A 4-terminal MOS is S/D symmetric and `NetlistComparer`
   treats it so; nothing is wrong, and the other nine devices read back in
   the schematic's own order.
2. **`AS`/`AD`/`PS`/`PD` are not compared.** The extracted values come from
   the drawn diffusion (e.g. `AS=0.84P` for a `W=2` device) and the design's
   own cards carry xschem's estimates (`as=0.58`); `klt lvs` compares
   `L`/`W` and topology, not the parasitic-area parameters, so they differ
   without affecting the verdict.

## The one thing this layout does not yet say

`klt gen` **cannot draw sky130's `hvi` (75/20) thick-oxide marker**, so every
device in this cell is the design's 5V `g5v0d10v5` `W`/`L` drawn in the 1.8V
domain's geometry. `klayout_tools.gen_layer_params`'
`_PDK_VOLTAGE_FLAVOR_LAYERS` has an empty `sky130` entry, so
`voltage_flavor: "hvi"` resolves to no layer and reports
`voltage_flavor_mark_present: false` rather than drawing anything — even
though the curated sky130 *extraction* deck already declares
`MOSFlavour(marker=(75, 20), flavour="hvi")` and `pdk_models` already binds
that flavour to the real `sky130_fd_pr__nfet_g5v0d10v5` /
`sky130_fd_pr__pfet_g5v0d10v5` subcircuits.

**The chain cannot see this, which is why it is called out here rather than
left to the evidence.** `klt drc`'s sky130 deck reads no `hvi` rule at all
(its own note records that every rule applies its general-case threshold to
`hvi`-marked geometry), and `klt lvs`'s `subckt-call` conversion deliberately
maps both flavour subcircuit names onto the same base `nfet`/`pfet` class —
so the `match` above is exactly as clean as it would be if the marker were
there. Filed generically per this repo's friction protocol as
[`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912).

What that means for this increment: the **topology** of this device group is
verified against the schematic, and the floorplan is not expected to change
when the gap closes — the fix is a marker-layer overlay over the same unit
devices, plus (a question #1912 raises but does not assume) whether the 5V
flavour's own minimum `L`/`W` should widen the drawn device. Its **device
flavour** is not verified, and this cell must not be treated as 5V-domain
sign-off until it is redrawn with the marker and re-run against a deck that
checks the `hvi` thresholds.
