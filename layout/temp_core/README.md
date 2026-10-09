# `temp_core`

Standalone layout of the whole `.subckt temp_core VDD VSS IBIAS EN PTAT CTAT`
in `design/netlist/temp_core.spice` (see `design/temp_core.md`). This is the
PTAT/CTAT sensing core: the 1:8 PNP pair, the error amplifier, the PTAT
mirror legs, the gain/isolation resistors, the Miller RC, startup, and
enable gating. Issue #104 is one leaf of T1 item 2 (layout). It is not
`temp_por_top`, so **item 2 stays `unmet`** (`manifests/README.md`).

All 48 devices of the subckt are drawn and compared. Nothing is excluded
from LVS, unlike `por_output_chain`.

## Result

Generated and checked with the `klt` build pinned in `layout/pdk.json`,
`0.6.0+g0ce8c64842d9` (see "Tool build").

| Step | Result |
|---|---|
| `klt drc --deck sky130` | `clean`, 0 violations |
| `klt extract --deck sky130` | 48 devices (`nfet` 17, `pfet` 16, `pnp` 9, `res_xhigh_po` 5, `sky130_fd_pr__model__cap_mim` 1), 24 nets, 24 pin labels |
| `klt lvs` vs `design/netlist/temp_core.spice` | `match`: 48/48 devices, 24/24 nets, 0 errors, 5 warnings (below), **no exclusions** |
| `compose-cell.py ... --check` | exit 0, "rebuild matches committed evidence" |
| `check-promotion.py` | all 6 port pins (`VDD`, `VSS`, `IBIAS`, `EN`, `PTAT`, `CTAT`) route to a downstream pad, downstream DRC clean |

Device count by schematic group: 33 MOS (17 NMOS, 16 PMOS), 9 PNP
(`XQ1`, `XQ8A..XQ8H`), 5 resistors (`XR1`, `XR2`, `XR2TRIM`, `XRISO`,
`XRZ`), 1 MiM cap (`XCC`). That is 48, the same as the netlist.

Drawn extent: 2803.9 x 80.9 um (x -10.0..2793.9, y -21.1..59.8). The width
comes from `XR2`, a straight 2652.6 um resistor (see "Floorplan"). The MOS
block alone spans x -10..132.5, y -6.1..59.8.

## Recipe

```
python3 layout/bin/compose-cell.py layout/temp_core/cell.json
python3 layout/bin/compose-cell.py layout/temp_core/cell.json --check
python3 layout/bin/check-promotion.py layout/temp_core/cell.json
```

`cell.json` is the only hand-maintained input. It has two stages:

1. **`xq1`** calls `klt gen bjt_array` once (`rows=1 cols=1 dummy=0`,
   `emitter_um=3.4`, closed collector ring). It wires the base `Q0_B` to the
   ring's own tap `COLL_E` and promotes the emitter as `na`. Outputs:
   `xq1.compose.request.json`, `xq1.compose.response.json`, `xq1.gds`.
2. **Final stage** (154 blocks). It places 33 `mos_array` 1x1 blocks, 16
   n-well `guard_ring` tap islands, 10 p-tap `guard_ring` islands, 5
   `res_array` resistors, 1 `cap_array`, the `xq1` stage, the reused
   `bias_core_pnp8_leg` stream, 6 port stubs and 81 junction blocks
   (`j_*`, see "Routing"). It then routes with `klt gen-compose`, and
   `compose-cell.py` runs `klt drc`, `klt extract` and `klt lvs`
   (`drc.json`, `extract.json`, `temp_core.spice`, `lvs.request.json`,
   `lvs.json`).

`--check` rebuilds in a temp directory and compares the verdict fields
`compose-cell.py` lists, including the `xq1` stage's response. **It does not
diff GDS bytes.** `temp_core.gds` is committed evidence, but `--check` does
not compare it. `check-promotion.py` writes `downstream-check.*`.

`cell.json` was written by a throwaway script that is not committed. The
script placed the blocks from the generated port positions and assigned
tracks by a randomized conflict search. Nothing in the GDS was edited by
hand. The committed `cell.json` is the artifact, and it regenerates
everything.

Two small hand-made streams sit next to `cell.json`:

- `promo_stub.gds`: a byte copy of the declare-only li1 port stub used by
  `por_comparator` and `por_output_chain`.
- `jct_m1.gds`: a 172-byte GDSII. It has one cell, `jct_m1`, with one
  boundary: a 0.32 x 0.32 um square on met1 (68/20) centred on the origin.
  It is written with the same record layout as `promo_stub.gds`. The writer
  that made it reproduces `promo_stub.gds` byte for byte.

### Tool build

`layout/pdk.json` pins `0ce8c64842d9`. The host's installed `klt` is a
different build (`0.6.0+g1eb3e4bfd0f5`), and it was not touched. All
evidence here comes from the pinned commit, run through a throwaway wrapper
outside the repo, so `check_klt_pin()` stays silent:

```
uvx --from "git+https://github.com/2AMLogic/klayout-tools@0ce8c64842d9" klt "$@"
```

Put a `klt` script that execs this first on `PATH`. The deck is the curated
`sky130` deck, PDK variant `sky130A`. `layout/pdk.json` is unchanged.

## Floorplan

Coordinates are in um.

- **NMOS row at y=0**, orientation `none` (gates face north), one
  `mos_array` 1x1 per device (`gate_contact` on), with a 2.2 um gap. Left to
  right: `MINVN MPASS MBD MDNB MBN1 MBN2 MSU5 MSU2 MDND MSU3 MDNT ML1 ML2
  MS2N MDN2 MENPT MENCT` (x 0..90.5). Ten p-tap islands `pst1..pst10` sit
  at y=-3.5, below the row, one before every second device and one at the
  east end.
- **PMOS row**, orientation `mirror_y` (gates face south). Each origin is
  set so that every gate pad sits on y=25.62. Left to right: `MINVP MENPG
  MBP MCB MSU1 MSU4 MS2P MT | MI1 MI2 | MP1 MPC1 MP2 MPC2 MP3 MPC3` (x
  0..132.5). Each PMOS has its own n-well `guard_ring` tap island at its
  west edge, abutted at a 0.10 um n-well overlap as in `por_comparator`.
- **Bodies.** All 17 NMOS bulks are on `VSS` (substrate plus the `pst`
  islands). 14 PMOS bulks are on `VDD`. **`XMI1` and `XMI2` have bulk `NT`**
  in the schematic, so they sit in their own n-well, 2 um further from their
  `VDD` neighbours on each side. Their two tap islands are wired to `NT`,
  not `VDD`. LVS compares all four MOS terminals, bulk included, and the
  extracted netlist reads `N1 NA NT NT` / `N2 NB NT NT`.
- **Channel** y 9.6..25.6 between the rows. Every signal track runs here.
- **Rails on met1**: `VDD` at y=59.58 above the PMOS row and `VSS` at y=-6
  below the NMOS row, each with a spur to every source pin and tap island.
- **Passives and PNPs, east of the MOS block** (X0 = 140.48). The resistors
  are straight horizontal `res_array` bars (`flavor xhigh`, `W=2`, `num=1`,
  `dummy=0`, one device each), stacked so that each lower row starts further
  west. That way each row's near-end pin has a clear vertical up to the
  channel without crossing the rows above it:

  | Device | Origin | Near end (`R0_A`) | Far end (`R0_B`) |
  |---|---|---|---|
  | `XRISO` (111.05) | (149.48, 1.0) | `NA` | `CTAT` (x 261.2) |
  | `XR1` (119.47) | (146.48, -3.5) | `NB` | `NC` -> `bias_core_pnp8_leg` `ec` |
  | `XRZ` (1000) | (143.48, -8.0) | `N2` | `NZ` -> `XCC` bottom plate |
  | `XR2` (2652.6) | (140.48, -12.5) | `PTAT` | `PTAT_TRIM` (x 2793.7) |
  | `XR2TRIM` (450.88) | (2342.2, -17.0) | `VSS` | `PTAT_TRIM` |

  A resistor's two ends are interchangeable for LVS, so each row's
  `R0_A`/`R0_B` naming follows the floorplan rather than the card order.
  `XR2TRIM` sits under the far end of `XR2`, right-aligned, so `PTAT_TRIM`
  is a 4.5 um vertical link. Its `VSS` end is reached by a met1 lane at
  y=-21. `XCC` (one 12 x 12 um `cap_array` unit) sits right after the far
  end of `XRZ` at (1148.11, -5.5).
- **PNPs.** `XQ8A..XQ8H` reuse `layout/bias_core_pnp8_leg/`'s committed
  stream unchanged (`blocks[].cell`, origin (276.38, -4.03)). Those devices
  have the same card as in `bias_core` (`VSS VSS <emitter>`), so only the
  emitter net name differs (`NC` here, `ec` there). That block's existing
  `ec` and `vss` escape stubs are declared as its ports. `XQ1` is the `xq1`
  stage at (306.38, -2.0). Its `na` port is the emitter pad, and its `vss`
  port is the collector ring's own li1 at `COLL_E`.
- **Ports** are declare-only li1 stubs on the west edge: `VDD`/`VSS` at
  x=-6, and `IBIAS`, `EN`, `PTAT`, `CTAT` at x=-10 on their own track's y.

## Routing

Role names: `metal` = li1, `metal2` = met1, `metal3` = met2, `metal4` =
met3, `metal5` = met4.

**Two-layer channel route.** Every device net other than the rails and the
three short local links is routed the same way:

- a **met1 vertical** from each pin to that net's track;
- a **met2 horizontal** track, one y per net, between the pins' x
  positions;
- at each (pin x, track y) a **junction block** `j_<net>_<block>_<port>`
  (`jct_m1.gds`). The vertical ends on it, and the met2 legs on either side
  land on it, so `gen-compose`'s own via ladder changes layer there.

Verticals of different nets never share an x, and tracks of different nets
never share a y where their x spans overlap. So no two nets cross on the same
plane, and only the met1 verticals near close pin pairs (for example an
NMOS pin under a PMOS pin) constrain which track sits above which. The
scratch search found one assignment for all 19 channel nets on a 0.5 um
met2 pitch:

| Track y | Nets (disjoint x spans share a y) |
|---|---|
| 10.22 | `NBG` |
| 10.72 | `N1`, `M2D` |
| 11.22 | `PG` (to x 1154.6, the `XCC` top plate) |
| 11.72 | `N2` |
| 12.22 | `PB` |
| 12.72 | `CTAT` (port to `XRISO` far end) |
| 14.22 | `IBIAS` |
| 15.72 | `ENB`, `M1D` |
| 18.72 | `NA` (to `XQ1`, x 308.1) |
| 19.22 | `NR` |
| 20.22 | `NB` |
| 20.72 | `PCAS` |
| 21.22 | `NT` |
| 21.72 | `M3D` |
| 22.22 | `ND` |
| 23.72 | `EN` |
| 24.72 | `PTAT` |

The junction blocks are needed because a `gen-compose` leg cannot change
plane except at a block port. Each junction carries **four ports at the same
point** (`N`, `S`, `E`, `W`), one per approach direction. With one port, a
leg arriving from a side the port did not face was rejected as "reaches the
pin from behind". Filed generically as
[2AMLogic/klayout-tools#2930](https://github.com/2AMLogic/klayout-tools/issues/2930).
An earlier attempt routed each net on one plane only (met1..met5, star from
a hub, por_output_chain's style). A randomized search placed at most 14 of
the 19 nets: with pins on both rows, a net's verticals cross every other
same-plane net's track.

**Local links and special legs:**

- `NC`: met1, `XR1` far end up to the `ec` stub of `bias_core_pnp8_leg`.
- `NZ`: met3 (`metal4`), `XRZ` far end up to `XCC`'s met3 bottom plate.
- `PTAT_TRIM`: met1, vertical between `XR2` and `XR2TRIM`.
- `PG` reaches `XCC`'s top plate on met4 (`metal5`, a per-leg override)
  from its junction.
- `VSS` reaches both PNP blocks by metal. A met1 leg runs along the y=-21
  lane and rises at x=314.36 to `XQ1`'s ring (`COLL_E`). A second leg runs
  from `bias_core_pnp8_leg`'s `vss` stub around under `XQ1` to the same
  point. **That riser crosses over the `XRZ` and `XR2` bodies** (met1 over
  the poly, no contact). That is DRC-legal, but it is one metal crossing
  over the gain resistor.

`gen-compose` reports every net `routed: true` and `unrouted_nets: []`. It
gives 34 advisory warnings: 32 are the abutted n-well tap islands ("placed
0.00um from block", on purpose, as in `por_comparator`), and 2 are
junctions 0.38 um from a PMOS block (the hint is 0.40 um). `klt drc` is
clean.

## Verification detail

**DRC.** `klt drc --deck sky130`: `clean`, 0 violations. Scope (from
`drc.json` `coverage`): 78 rules checked across `capm diff li1 licon1 mcon
met1 met2 met3 met4 nwell poly psdm tap via via2 via3`. Skipped: the
`*.angle.1`/`*.ongrid.1` rules on marker layers this cell does not draw
(`hvi`, `hvntm`, `dnwell`, `lvtn`, ...) and the met5/capm2/via4 rules
(nothing is drawn there). The deck models no latch-up, antenna, density or
well-to-tap-distance rule, so none of those is claimed. The deck is
`released: false`.

**Extract.** `klt extract --deck sky130`: `extracted`, 48 devices, 24 nets,
24 pin labels, `dummy_devices_dropped: 0`, and empty `single_terminal_nets`,
`dead_metal`, `unbiased_pmos_body_nets` and `missing_flavour_markers`.
`merged_net_labels` holds only the three intended joins with the reused
blocks' own labels: `NA|na` (`xq1` stage), `NC|ec` and `VSS|vss`
(`bias_core_pnp8_leg`, `xq1`). As drawn, independently of LVS:

| Device | Netlist `L`, `W` (um) | Extracted `l_um`, `w_um` | `r_ohm` (deck value) |
|---|---|---|---|
| `XR1` | 119.47, 2 | 119.47, 2.0 | 119,470 |
| `XRISO` | 111.05, 2 | 111.05, 2.0 | 111,050 |
| `XRZ` | 1000, 2 | 1000.0, 2.0 | 1,000,000 |
| `XR2` | 2652.6, 2 | 2652.6, 2.0 | 2,652,600 |
| `XR2TRIM` | 450.88, 2 | 450.88, 2.0 | 450,880 |
| `XCC` | `W=L=12` | `area_um2` 144.0 | `c_f` 2.97e-13 (deck value) |

`r_ohm`/`c_f` are `klt extract`'s deck values (body only). They are not
measured or PEX values. `(XR2 + XR2TRIM) / XR1` as drawn is 3103.48 /
119.47 = 25.977 in length units. That is the same ratio as the netlist
(both are 2 um wide).

**LVS.** `klt lvs`: `match`, devices 48/48, nets 24/24, pins 24 layout / 6
reference, `error_count: 0`, `mismatch_count: 5`. All 5 are warnings, and
each one limits what the match proves:

- `device.parameter_excluded`: the `PNP` compare is limited to `NE`
  (`lvs.options.compare_parameters`, the same limit the `bias_core` PNP cells
  use; sky130's fixed-geometry `AE` gap is
  [klayout-tools#2335](https://github.com/2AMLogic/klayout-tools/issues/2335)).
  So PNP `AE` is **not** verified.
- `device.placeholder_value` x2: the subckt-call reference carries `R=0`/`C=0`
  for the 5 resistors and the MiM cap, so their **values** are not compared.
- `device.geometry_not_compared` x2: resistor `L/W/A/P` and MiM `A/P` are
  KLayout secondary parameters and are not compared.

MOS classes compare `L`, `W` and all four terminals, bulk included. So the
match proves topology for every device, plus MOS sizing. Resistor and cap
sizing rests on the extracted-geometry table above, not on LVS.

The reference `temp_core.ref.spice` differs from the source only by the `u`
unit suffixes (`compose-cell.py`'s known rewrite). There is no
`drop_prefixes` and no `expand_multiplier`. `design/` is unchanged.

**Negative controls.** Each run used a scratch copy of the generated
reference against the committed `temp_core.spice`; none is committed. Each
one turns `match` into `mismatch`:

| Edit to the reference | Result |
|---|---|
| `XMI1` bulk `NT` -> `VDD` | `mismatch`, 47/48 devices (`device.unmatched`) |
| `XMCB` `L` 8 -> 7 | `mismatch`, 47/48 devices (5 `device.property` errors) |
| `XQ1` emitter `NA` -> `NC` | `mismatch`, 47/48 devices |
| `XR1` far end `NC` -> `PTAT_TRIM` | `mismatch`, 47/48 devices |
| `XQ8H` removed | `mismatch`, 47 reference devices |

So the separate `NT` body, MOS `L`, the PNP and resistor terminals, and the
PNP count are really compared.

**Metal-only connectivity of the PNP straps.** LVS sees the PNP collectors
and bases on `VSS` whether they reach it by metal or only through the
p-substrate. To check the metal path, the GDS was probed with a scratch
`klayout.db` netlist made of li1, mcon and met1..met5 only (no diffusion,
tap or substrate). `stub_vss`, `XQ1`'s ring (`COLL_E`),
`bias_core_pnp8_leg`'s `vss` stub, `XR2TRIM`'s `VSS` end and an NMOS source
all fall on one metal net, and `XQ1`'s emitter and `XRISO`'s `NA` end fall
on another. So both PNP blocks are strapped to `VSS` in metal, not only
through the substrate.

## Known gaps

1. **No `hvi` thick-oxide marker** at the pinned build. All 33 MOS are the
   5 V devices' `W`/`L` drawn without the marker, and neither `klt drc` nor
   `klt lvs` can see it. This is the same disclosure as every other MOS cell
   here
   ([#1912](https://github.com/2AMLogic/klayout-tools/issues/1912)).
   **This cell is not 5 V sign-off.**
2. **Matching is by construction only, and only partly.** `XQ1` is a
   separate single-unit ring about 5.5 um east of the 8-unit
   `bias_core_pnp8_leg` array. It is not common-centroid with the 8, which
   is the same split `bias_core` uses. `XMI1`/`XMI2` and `XML1`/`XML2` are
   adjacent single devices, not interleaved, and the three `XMPk`/`XMPCk`
   legs sit side by side. Routing is not symmetric. LVS checks none of this,
   and nothing here was simulated with parasitics.
3. **Resistor and cap values are not LVS-compared** (placeholder `R`/`C`,
   secondary geometry). The drawn `L`/`W` and the cap area match the
   netlist exactly (table above).
4. **PNP `AE` is not compared** (`compare_parameters: {pnp: [NE]}`).
5. **Area is not optimized.** Each resistor is one straight bar (no
   folding: a folded `res_array` would be several series devices). `XR2`
   alone makes the cell 2.8 mm wide. `PG` runs 1.1 mm to `XCC`, and the
   `VSS` lane runs 2.2 mm to `XR2TRIM`. Their resistance and capacitance
   were not extracted.
6. **One `VSS` riser crosses `XRZ` and `XR2`** in met1 (above).
7. **Trim.** `PTAT_TRIM` is the single trim node the schematic carries. No
   strap ladder is drawn, because the schematic has none
   (`design/temp_core.md`, "Trim mechanism").
8. **No ERC, no parasitic extraction, no simulation** of the laid-out cell.
   `sim/` is untouched.
9. **Not a signoff citation.** `manifests/` cites nothing from this
   directory, and item 2 stays `unmet`.
