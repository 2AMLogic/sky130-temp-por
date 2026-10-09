# `por_output_chain`

Standalone proof layout of `design/netlist/por_output_chain.spice`'s whole
`.subckt por_output_chain VDD VSS IBIAS POR_RAW RESETn` (see
`design/por_output_chain.md`): the POR output chain that turns `POR_RAW` into
`RESETn`. Issue #97, a partial leaf of T1 item 2 (layout). It follows the
compose-cell recipe of `layout/por_comparator/` (MOS floorplan, tap islands,
per-net `layer_role`) and `layout/bias_core_passives/` (`cap_array` MiM).
It is one leaf cell of the block, not `temp_por_top`; **item 2 stays `unmet`**
(see `manifests/README.md`), and this cell is **not complete**: one of the
schematic's devices could not be drawn (next section).

## Result

Generated and checked with the `klt` build `layout/pdk.json` pins,
`0.6.0+g0ce8c64842d9` (see "Tool build").

| Step | Result |
|---|---|
| `klt drc --deck sky130` | `clean`, 0 violations |
| `klt extract --deck sky130` | 33 devices (`nfet` 14, `pfet` 14, `sky130_fd_pr__model__cap_mim` 5), 18 nets, 18 pin labels |
| `klt lvs` vs `design/netlist/por_output_chain.spice` | `match`: 33/33 devices, 18/18 nets, 0 errors, 2 warnings (below), **with `XMASSIST` excluded** |
| `compose-cell.py ... --check` | exit 0, "rebuild matches committed evidence" |

Drawn extent 337.8 x 65.0 um (x -10.0..327.8, y -6.1..58.9).

## Blocker: `XMASSIST` (native-Vt NMOS) is not drawn, and is excluded from LVS

`XMASSIST` is `sky130_fd_pr__nfet_05v0_nvt` (`L=25 W=1`, drain `RESETn`, gate
`VDD`, source and bulk `VSS`), native-Vt by design (`design/por_output_chain.md`).
It was measured at the pinned build (`0ce8c64842d9`) and at the host's
`0.7.0+g4cbdfa769875`; both behave the same:

1. **`klt gen` cannot draw it.** `mos_array` has `flavor` `nfet|pfet` only.
   `voltage_flavor` set to `native`, `nvt` or `medium_voltage` reports "has no
   marker layer resolved for the resolved PDK family ('sky130') -- no marker
   was drawn", and `voltage_flavor_mark_present: false`. The geometry is
   identical to a plain `nfet`.
2. **`klt extract --deck sky130` has no native NMOS class** (its
   `device_classes` are `nfet`, `pfet`, `pnp`, the two `cap_mim` models and
   `resistor`), so even a hand-made native device would read back as `nfet`.
3. **`klt lvs` cannot read the reference card.** With the card kept, it stops
   before any compare: `subcircuit 'sky130_fd_pr__nfet_05v0_nvt' is not a known
   device for the requested deck`. The only offered escape is
   `reference.device_map`, which would map it onto the plain `nfet` class and
   let a wrong-type device pass.

Following the project rules (no device substitution, reference not altered):

- The layout **does not contain `XMASSIST`**. A plain-NMOS stand-in would be
  the wrong device.
- The design netlist is **unmodified**. The *generated* reference
  `por_output_chain.ref.spice` omits the `XMASSIST` card
  (`lvs.drop_prefixes: ["XMASSIST"]`), so the compare is 28 MOS + 5 caps
  against the same. **This is the only device exclusion.** The `RESETn`,
  `VDD` and `VSS` nets all still exist without it; what is absent is its
  connection (`RESETn` as drain, the `VDD` gate tie, `VSS` source and bulk).
  `layout/bin/compose-cell.py` was extended for this exclusion (it now also
  drops the `+` continuation line of a removed card).
- Filed upstream, generically:
  [2AMLogic/klayout-tools#2912](https://github.com/2AMLogic/klayout-tools/issues/2912).

Consequence: this directory is **not** an LVS `match` of the whole subckt. It
is a match of everything but one device. Adding the native device is the
remaining work for this leaf, and is blocked on the tool.

## Recipe

```
python3 layout/bin/compose-cell.py layout/por_output_chain/cell.json
python3 layout/bin/compose-cell.py layout/por_output_chain/cell.json --check
```

`cell.json` is the only hand-maintained input (59 blocks). It calls `klt gen`
once per block (`mos_array` 1x1, `guard_ring` tap islands, `cap_array`;
outputs in `gen/`), places the blocks with `placement.strategy: "explicit"`,
routes with `klt gen-compose` (`compose.request.json` /
`compose.response.json`), then runs `klt drc`, `klt extract` and `klt lvs`
(`drc.json`, `extract.json`, `por_output_chain.spice`, `lvs.request.json`,
`lvs.json`). `promo_stub.gds` and `promo_stub_v.gds` are byte copies of the
declare-only pad stubs the other cells use. `layout/pdk.json` is unchanged.

`--check` rebuilds in a temp directory and compares `status`/counts/bbox
fields (the `drc.json`, `extract.json`, `lvs.json` and `compose.response.json`
fields `compose-cell.py` lists); **it does not diff GDS bytes**, so
`por_output_chain.gds` is committed evidence but is not itself compared.

`cell.json` was authored with a throwaway script (a placement and track
assignment search, not committed) that computes every waypoint from the
generated port positions; nothing in the GDS was edited by hand. The
committed `cell.json` is the artifact, and it is what regenerates everything.

### Tool build

`layout/pdk.json` pins `0ce8c64842d9`. The host's installed `klt` is a
different, newer build (`0.7.0+g4cbdfa769875`) and was not touched. All
evidence here was produced by the pinned commit through a throwaway wrapper
outside the repo, so `check_klt_pin()` stays silent:

```
uvx --from "git+https://github.com/2AMLogic/klayout-tools@0ce8c64842d9" klt "$@"
```

Put a `klt` script exec'ing that first on `PATH`. Deck: the curated `sky130`
deck, PDK variant `sky130A`.

## Floorplan

Coordinates in um. Nothing is shared with, or edited in, any other
`layout/*/` cell or `design/`.

- **One `mos_array` (1 row, 1 column, no dummies) per MOS**, `gate_contact`
  on. 14 NMOS in a row along y=0 (gates north, orientation `none`), 14 PMOS
  mirrored (`mirror_y`) so every gate pad sits on y=45.2 (gates south), and a
  signal channel between (y 13..43).
- **Row order** follows function so most nets stay local: NMOS `MBD MN1 MND
  MDGNT MDGNI MG1N MG2N MDIS MDANT MDBNI MRLK MNAN2 MNAN1 MON`; PMOS `MPD MP2
  MPT MDGPT MDGPI MG1P MG2P MTSW MDAPI MDBPT MNAP2 MNAP1 MAST MOP`.
- **Bodies.** Every PMOS has its own `guard_ring` n-well tap island (abutted
  at the 0.10 um n-well overlap, as in `por_comparator`) tied to `VDD`. Seven
  p-tap islands `pst1..pst7` (y=-3.5, in the gap before every second NMOS)
  tie the substrate to `VSS`. As extracted: all 14 NMOS bulks are on `VSS`, all
  14 PMOS bulks on `VDD`; no `vsubs` net remains.
- **Capacitors** (x >= 187.8, east of the rows): `CDG` is one `cap_array`
  (11 x 11 um top plate, `num=1`). `CTIM` (`W=L=28`, `MF=4`) is **four**
  separate 28 x 28 um `cap_array` blocks (`ctim0..3`, 3 um apart), one per
  multiplier unit: top plates all on `TIM`, bottom plates all on `VSS`. Four
  blocks rather than `num=4` so each bottom-plate port is reachable from the
  open gap west of its own block. `klt extract` reads them back as 1 + 4
  capacitors (`area_um2` 121 and 784 each; `c_f` 250 fF and 1589 fF, which
  are `klt extract`'s deck values, not measurements).
- **Rails on met1**: `VDD` at y=58.8 above the PMOS row, `VSS` at y=-6.0
  below the NMOS row, spurring to every source pin and tap island. `VSS`
  continues east under the capacitors and rises in the gaps to each bottom
  plate.
- **External ports** are declare-only li1 stubs (`promo_stub*.gds`):
  `VDD`, `VSS`, `IBIAS`, `POR_RAW` on the west edge (x=-10, `VDD`/`VSS` at
  x=-6), `RESETn` on the east end of its track (x=174). Each is named in
  `pins[]` and appears as a pin label in `extract.json`.

## Routing

Every net except the rails is a star of legs from a hub pin along one
horizontal track in the channel, with vertical drops to each pin, on **one
plane per net** (`connectivity[].layer_role`). A random-restart search picked
each net's plane (met1..met5) and track so that no two nets sharing a plane
come within spacing of each other or of each other's via-stack pads; 16
signal nets fit, two of them (`PDN`, `TRIP`) on met5 at the deck's 1.6 um
minimum width. `TIM` and `NDG` use their own plane for the device pins and a
per-leg `metal5` override (0.4 um) for the legs to the capacitor top plates,
which sit on met4. `klt gen-compose` reports every net and every leg
`routed: true`, `unrouted_nets: []`. 28 warnings, all of the form "block
'nwt_x' is placed 0.00um from block 'x'" (the tap islands abutted on purpose,
as in `por_comparator`).

The search is a heuristic; `klt drc` and `klt extract` are the arbiter. A first
assignment from it drew one `met5` and then one `met4` spacing violation, and
other seeds were refused by `gen-compose` ("crosses already-routed net"); the
committed one is the first that was routed, DRC-clean and LVS-clean.

## Verification detail

`klt drc --deck sky130`: `clean`, 0 violations. **Deck scope** (from
`drc.json` `coverage`): 18 deck scopes (`cap2m capm ct difftap li licon m1 m2
m3 m4 m5 nwell poly via via2 via3 via4 x`), the curated sky130 deck's
spacing/width/enclosure/area/angle/grid rules on the layers this cell draws.
Not covered: the `*.angle.1`/`*.ongrid.1` rules on marker layers this cell
does not draw (`hvi`, `hvntm`, `dnwell`, `lvtn`, ... reported as skipped), and
anything the deck does not model (no latch-up, antenna, density or
well-proximity-to-tap-distance rule is claimed). Layers in the stream without
rules: 67/5, 68/5, 69/5, 70/5, 72/5. The deck is `released: false`.

`klt extract --deck sky130`: `status: extracted`, 33 devices, 18 nets, 18 pin
labels. `device_counts`: `{"nfet": 14, "pfet": 14,
"sky130_fd_pr__model__cap_mim": 5}`. Port nets, each labelled at its stub
(`extract.json` `nets[]`): `IBIAS` (-10, 13), `POR_RAW` (-10, 23.8), `RESETn`
(174.0, 43.0), `VDD` (-6, 58.8), `VSS` (-6, -6.0). Connectivity to the
devices is what LVS verifies (below); VDD and VSS tap connectivity is the
bulk census above.

`klt lvs`: `match`, devices 33/33, nets 18/18, pins 18 layout / 5 reference,
`mismatch_count: 2`, `error_count: 0`. The 2 are warnings:

- `device.placeholder_value`: the capacitor `C` is the literal 0 in the
  subckt-call reference, so it is excluded from the compare.
- `device.geometry_not_compared`: capacitor `A` and `P` are secondary
  parameters, not compared.

So capacitor values and areas are **not verified by LVS** (same as
`bias_core_passives`): the `CDG`/`CTIM` multiplicities are checked by count
(1 and 4 units) and by the topology of both plates, and the unit sizes
(121 and 784 um2 `area_um2`) were read from `extract.json`. MOS classes
compare `L` and `W` and all four terminals including the bulk (the default).

**Reference rewrite (`lvs.expand_multiplier`).** `klt lvs` refuses the
reference card `XCTIM ... MF=4 m=4` ("one device per drawn gate"). The
generated `por_output_chain.ref.spice` therefore writes it as `XCTIM_0..3`,
each `MF=1 m=1`, which is exactly what the layout draws. `design/` is
unchanged. Other cards differ from the source only by `u` unit suffixes
(`compose-cell.py`'s known rewrite).

Negative controls (scratch copies of the generated reference, not
committed): `XMN1` `L` 25 -> 24 gives `mismatch` (5 `device.property`
errors); `XMDIS`'s gate moved from `PGDGB` to `PGDG` gives `mismatch`
(`device.unmatched`); dropping `XCTIM_3` gives `mismatch` (32 of 33 devices).
So `L`, the topology and the capacitor count are really compared.

## Known gaps

1. **`XMASSIST` is missing** (above): the single LVS exclusion, blocked on
   [klayout-tools#2912](https://github.com/2AMLogic/klayout-tools/issues/2912).
2. **No `hvi` thick-oxide marker** at the pinned build: all 28 MOS are the 5 V
   devices' `W`/`L` drawn without the marker, and neither `klt drc` nor `klt
   lvs` can see it (the same disclosure as `por_comparator`, upstream
   [#1912](https://github.com/2AMLogic/klayout-tools/issues/1912), closed;
   redrawing belongs to the pin bump that regenerates every `layout/*/`
   directory together). **This cell is not 5 V sign-off.**
3. **Capacitor values not LVS-compared** (placeholder `C`, secondary `A`/`P`).
4. **Long-channel devices** (`L` 10 and 25 um) are single-finger, as in
   `por_comparator`; area is not optimized (336 um wide, mostly the
   capacitors and the long devices). No density or matching work.
5. **No ERC, no parasitic extraction, no simulation** of the laid-out cell.
   `sim/` is untouched.
6. **Not a signoff citation.** `manifests/` is not cited from this
   directory, and item 2 stays `unmet`.
