# `bias_core_mirror_amp`

Standalone proof-of-concept layout for `design/netlist/bias_core.spice`'s
`XMP1`/`XMP2`/`XMP3`/`XMPBN`/`XMBN`/`XMBN2`/`XMBP`/`XMPIB`/`XMPT`/`XMI1`/
`XMI2`/`XML1`/`XML2`/`XMS2N`/`XMS2P` device group — `design/bias_core.md`'s
PFET/NFET current-mirror + error-amp stack. Issue #35 (part of #34, a
device-group split of "T1 item 2/10 continued", itself a follow-on from
#30/#36/#37), decomposed for size from #34. Follows the compose-cell recipe
`layout/bias_core_pnp8_leg/` (#30/PR #33) established, and the multi-plane
two-row CMOS floorplan `layout/bias_core_settle_flag/` (#39/PR #46) and
`layout/bias_core_startup/` (#38/PR #48) proved — this is the third
sub-block in this repo to reach a full `klt lvs` `match`, and the largest
so far (15 devices, 13 boundary nets).

| Device | Ports (device-card order: `D G S B`) | Size |
|---|---|---|
| `XMP1` | `NA` `PG` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=8` |
| `XMP2` | `NBTOP` `PG` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=8` |
| `XMP3` | `VREF` `PG` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=8` |
| `XMPBN` | `NBG` `PG` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=2` |
| `XMBN` | `NBG` `NBG` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=2` |
| `XMBN2` | `PB` `NBG` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=2` |
| `XMBP` | `PB` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=2` |
| `XMPIB` | `IBIAS` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=40` |
| `XMPT` | `NT` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=2` |
| `XMI1` | `N1` `NA` `NT` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=16` |
| `XMI2` | `N2` `NB` `NT` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=16` |
| `XML1` | `N1` `N1` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=4` |
| `XML2` | `N2` `N1` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=4` |
| `XMS2N` | `PG` `N2` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=8` |
| `XMS2P` | `PG` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=2` |

`XMP1`/`XMP2`/`XMP3`/`XMPBN` are the four PFET mirror legs off the shared
gate node `PG`; `XMBN`/`XMBN2` are the NFET bias mirror (`XMBN`
diode-connected on `NBG`) and `XMBP` the PFET diode that sets `PB`;
`XMPIB`/`XMPT` are the `PB`-gated bias-current outputs (`IBIAS` out, and the
error amp's own tail node `NT`); `XMI1`/`XMI2` are the PFET input pair with
`XML1`/`XML2` as their NFET mirror load; `XMS2N`/`XMS2P` drive `PG` from the
amp output `N2`, closing the loop. Thirteen nodes cross this group's
boundary — `VDD`, `VSS`, `PG`, `NA`, `NBTOP`, `VREF`, `NBG`, `PB`, `NT`,
`N1`, `N2`, `IBIAS`, `NB` — exactly the Test Plan's own net list as amended
by the Curator's `NB` correction (`XMI2`'s gate net, driven by the
bias/ratio-resistor divider tracked in #37).

## Recipe

Each device is its own single-instance `klt gen mos_array` call (`rows=1
cols=1 dummy=0 gate_contact=true`, `flavor` per device). `XMI1`/`XMI2` and
`XML1`/`XML2` *are* matched pairs electrically, but `mos_array`'s
common-centroid interdigitation draws an array as one block with shared
source/drain, which cannot express this group's distinct per-terminal nets
(`XML1` is diode-connected, `XML2` is not) — so every device is drawn
separately and matching is left to the identical drawn geometry.
`layout/bin/compose-cell.py layout/bias_core_mirror_amp/cell.json` runs the
full `gen` -> `gen-compose` -> `drc` -> `extract` -> `lvs` chain and writes
every step's response next to this file, same shape as the sibling recipes.
Re-verify with:

```
python3 layout/bin/compose-cell.py layout/bias_core_mirror_amp/cell.json --check
```

`reference.spice` is a hand-extracted, byte-for-byte copy of
`design/netlist/bias_core.spice`'s own fifteen device cards, wrapped in a
13-port `.subckt` — not an xschem export, since the design's own `.subckt
bias_core` is the whole cell, not this group alone.

## Floorplan

`placement.strategy: "explicit"`. Drawn extent 91.18 x 72.17 um
(`x0=-2.19 y0=-6.085 x1=88.985 y1=66.085`); the placed-block bbox
`compose.response.json` reports is `x0=-2.19 y0=0.0 x1=87.84 y1=63.12`, the
difference being the `vss` bus below the NMOS row and the `vdd`/`na` runs
above the PMOS row.

- **NMOS row along `y=0`**, `orientation: "none"`, so every NFET gate faces
  north. Left to right: `mbn` (x=24), `mbn2` (x=31), `ms2n` (x=38), the
  `pst` psub tap island (x=55), `ml1` (x=68), `ml2` (x=79).
- **PMOS row with its bottom edge at `y=22.0`**, `orientation: "mirror_y"`,
  so every PFET gate faces south and lands on the *same* `y=22.36` gate row
  — each PMOS origin is set from its own device height,
  `Y = 22.0 + w + 0.97`. Left to right on a 9.0um column pitch: `mp2` (x=0),
  `mp3` (9), `mp1` (18), `mpbn` (27), `ms2p` (36), `mbp` (45), `mpib` (54),
  `mpt` (63), `mi1` (72), `mi2` (81).
- **A 13um signal channel** (`y` from ~9 to 22) between the two rows carries
  every net that has to cross the cell.

The column order is not cosmetic. `PG`'s pins (four gates plus `XMS2P`'s and
`XMS2N`'s drains) are kept in the **left** half and `PB`'s (four gates,
`XMBP`'s drain, `XMBN2`'s drain) in the **right** half, meeting only at
`ms2p`, whose gate (`PB`, at `x+2.42`) and drain (`PG`, at `x+4.63`) are the
one place the two nets come within 2.2um of each other — so the two longest
bias nets never need to share an x range on the same plane. `mbn`/`mbn2` sit
under `mpbn`/`ms2p` so `NBG` stays a short, local li1 net, and `ml1`/`ml2`
sit under `mi1`/`mi2` so `N1` does too.

**Body ties.** Every PFET gets its own `guard_ring` nwell tap island 2.04um
to its west, placed so the two nwells **overlap by 0.10um** (one electrical
node) while their li1 stays 0.20um apart, clear of sky130's 0.17um li1
spacing floor — the same 0.10um-overlap convention
`layout/bias_core_settle_flag/README.md` works through. The 9.0um column
pitch leaves 1.82um between one device's own nwell island and the next
one's tap, clear of the 1.27um `nwell.space.1` floor. `XMI1`/`XMI2`'s
*sources* are `NT`, not `VDD`, but their **bodies** are `VDD`, so they get
tap islands too, strapped into the `vdd` bus like the rest. A single psub
tap island (`add_well: false`) straps the substrate to `vss`; one is enough,
because an NMOS body is a globally synthesized net regardless of any drawn
contact — see `layout/bias_core_startup/README.md` for the empirical check
behind that claim.

## Routing

Three planes, assigned per net — and, for `n2`, per **leg** — through
`connectivity[].layer_role` / `connectivity[].legs[].layer_role`
([`klayout-tools#1655`](https://github.com/2AMLogic/klayout-tools/issues/1655)),
so no two nets sharing a plane ever cross:

| Plane | Nets | Where |
|---|---|---|
| `metal` (li1) | `nbg`, `nt`, `n1` | three local nets in disjoint x ranges (26.4–33.4, 67.6–81.2, 72.4–83.4; `nt` stays at `y >= 23.97`, above `n1`'s channel lane) |
| `metal2` (met1) | `vdd`, `vss`, `pb`, `n2`'s `ml2.D -> ms2n.G` leg | four disjoint y bands: the `vdd` bus at `y=65.0` (above every PMOS top) with a riser down each tap/source column, the `vss` bus at `y=-6.0` below the NMOS row, `pb`'s channel lane at `y=18.0`, and `n2`'s channel lane at `y=12.0` |
| `metal3` (met2) | `pg`, `na`, `n2`'s `mi2.D -> ml2.D` leg | `pg`'s channel lane at `y=14.0`; `na`'s "attic" run at `y=66.0` straight over the PMOS row; `n2`'s column at `x=88.9`, east of every block |

Every leg is steered explicitly through `connectivity[].legs[]`
([`klayout-tools#1529`](https://github.com/2AMLogic/klayout-tools/issues/1529))
rather than left to the automatic nearest-first spanning tree.
`compose.response.json` records `routed: true` for every net **and** for
every named leg.

Three of those choices are worth the words:

**`na` goes over the roof, not through the channel.** `NA` runs from
`XMP1`'s drain (left half) to `XMI1`'s gate (right half), i.e. across the
whole cell — but `pg`'s own lane already owns the channel on met2 and `pb`'s
owns it on met1 across exactly that x range. Since `gen-compose` *does*
allow a route to plunge into its **own** endpoint's block (just not an
unrelated one), `na` leaves `XMP1`'s drain eastward into the 1.82um gap at
`x=23.5`, climbs to `y=66.0` — clear of `mpib`'s `y=63.12` top, the tallest
block in the cell — runs the width of the PMOS row, and drops back down the
`x=74.42` column straight through `mi1`'s own body onto its south-facing
gate pad.

**`n2` is the one net that needs two planes.** `XMS2N`'s gate sits directly
*under* `pg`'s own channel lane, and the `XMI2` end sits east of every
block, so no single plane can carry `mi2.D`, `ml2.D` and `ms2n.G` at once
without crossing `pg`. The two legs live on met2 and met1 respectively and
stitch at their shared `ml2.U0_D` pin through the existing via-drop — which
is exactly the non-planar case per-leg `layer_role` exists for.

**The `vdd` bus runs above the PMOS row, not below it.** Below the row would
put the bus in the channel, where it would have to cross `pb`'s and `n2`'s
met1 lanes; above it, each source/tap riser drops down a column that is
empty except for its own endpoint's block, and the whole `y < 22` half of
met1 stays free for signal routing.

### One routability lesson worth recording

The first draft routed `nt`'s `mi1.U0_S -> mi2.U0_S` leg by climbing over
`mi1`, running east at `y=40.0`, and dropping *straight down the
`x=81.21` column* onto `mi2`'s west-facing source pad — 8.4um through
`mi2`'s own interior. `gen-compose` rejected it:

> `backbone's 0.17um-wide drawn path crosses 8.405um through its own pin's
> block 'mi2' -- more than that pin's own 0.445um edge margin`

A route may enter its own endpoint's block, but only by that port's own
edge margin *in the direction the port faces* — here 0.36um of west-facing
inset, not 8.4um from the north. Dropping the column at `x=80.5` instead
(just clear of `mi2`'s own `x0=80.85`) and approaching the pad from the
west, the direction it faces, routes cleanly. Note this is a *stricter*
rule than the one the `vdd` risers rely on, where a riser descends tens of
microns inside its own block to reach the same kind of west-facing source
pad — so it is a property of the whole approach path, not of the final
segment alone. Not filed as a tool gap: the rejection message named the
constraint and the fix precisely.

## Verification

Reproduced with `--check` (rebuild into a temp dir, diff the verdict-bearing
fields) at the `klt` build `layout/pdk.json` pins.

- **`klt drc --deck sky130`: clean, 0 violations.**
- **`klt extract --deck sky130`: 15 devices, 13 nets.** `device_counts`
  reads `{"pfet": 10, "nfet": 5}` — the ten
  `XMP1`/`XMP2`/`XMP3`/`XMPBN`/`XMBP`/`XMPIB`/`XMPT`/`XMI1`/`XMI2`/`XMS2P`
  PFETs and the five `XMBN`/`XMBN2`/`XML1`/`XML2`/`XMS2N` NFETs. The
  thirteen nets are exactly the thirteen boundary nodes — `vdd`, `vss`,
  `pg`, `na`, `nbtop`, `vref`, `nbg`, `pb`, `nt`, `n1`, `n2`, `ibias`, `nb`.
- **`klt lvs` against `reference.spice`: `match`** — 15/15 devices, 13/13
  nets, 13/13 pins, `mismatch_count: 0`, `error_count: 0`, and every one of
  the thirteen nets appears in `net_correspondence` as a pin.

As with `bias_core_settle_flag` and `bias_core_startup`, two things this
match does not assert:

1. **Source/drain assignment is not preserved, and is not meant to be** — a
   4-terminal MOS is S/D symmetric and `NetlistComparer` treats it so.
2. **`AS`/`AD`/`PS`/`PD` are not compared** — the extracted values come from
   the drawn diffusion and the design's own cards carry xschem's estimates;
   `klt lvs` compares `L`/`W` and topology, not the parasitic-area
   parameters.

### A note on which `klt` build this was generated with

`layout/pdk.json` pins the evidence to klayout-tools commit
`ba213c617b4e`, whose `klt version` self-report in *this* environment reads
`0.5.0+gba213c617b4e` (the pin's `0.4.0+g...` spelling came from an earlier
build environment where the `v0.5.0` tag had not been fetched, so the
derived package version differed; the git commit — the part that actually
identifies the build — is the same, and `--check` reproduces
`bias_core_startup`'s committed evidence byte-for-byte against it). That is
why this cell's `drc.json`/`lvs.json` `provenance.klt_version` reads
`0.5.0` where the sibling cells' read `0.4.0`: same commit, different
derived version string. The **released** `klayout-tools` v0.5.0 on PyPI is
38 commits *behind* that pin and predates `connectivity[].layer_role`
(#1655), so it cannot rebuild this cell — or any of the existing ones.
Filed as a repo-hygiene follow-up, not a tool gap.

## The one thing this layout does not yet say

Same disclosure as `bias_core_settle_flag` and `bias_core_startup`: `klt
gen` **cannot draw sky130's `hvi` (75/20) thick-oxide marker**, so every
device in this cell is the design's 5V `g5v0d10v5` `W`/`L` drawn in the 1.8V
domain's geometry. `klt drc`'s sky130 deck reads no `hvi` rule, and `klt
lvs` deliberately maps both voltage flavours onto one device class, so the
`match` above is exactly as clean as it would be with the marker present.
Filed generically as
[`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912);
the **topology** of this device group is verified against the schematic and
the floorplan is not expected to change when the gap closes, but this cell
must not be treated as 5V-domain sign-off until it is redrawn with the
marker and re-run against a deck that checks the `hvi` thresholds.
