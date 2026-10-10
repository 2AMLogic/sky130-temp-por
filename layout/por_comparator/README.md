# `por_comparator`

Standalone proof layout of `design/netlist/por_comparator.spice`'s whole
`.subckt por_comparator VDD VSS IBIAS VREF BIAS_OK POR_RAW` — the POR
comparator leaf cell: bias-gating network, the NMOS differential pair with
its PMOS mirror load, the resistor divider that senses `VDD`, the hysteresis
switch, and the two-inverter output stage. 21 devices: 6x
`sky130_fd_pr__pfet_g5v0d10v5`, 12x `sky130_fd_pr__nfet_g5v0d10v5`, 3x
`sky130_fd_pr__res_xhigh_po`. Issue #82, T1 item 2 (layout); follows the
compose-cell recipe of `layout/bias_core_settle_flag/` (MOS floorplan, tap
islands, per-net `layer_role`) and `layout/bias_core_passives/` (straight
single-instance `xhigh` resistors). It is one leaf cell of the block, not
`temp_por_top`; item 2 stays `unmet` (see `manifests/README.md`).

## Result

Generated and checked with the `klt` build `layout/pdk.json` pins (see
"Tool build" below).

| Step | Result |
|---|---|
| `klt drc --deck sky130` | `clean`, 0 violations |
| `klt extract --deck sky130` | 21 devices (`nfet` 12, `pfet` 6, `res_xhigh_po` 3), 15 nets, 15 pin labels |
| `klt lvs` vs `design/netlist/por_comparator.spice` | `match`: 21/21 devices, 15/15 nets, 0 errors, 3 warnings (below) |
| `compose-cell.py ... --check` | exit 0, "rebuild matches committed evidence" |

The LVS reference is the design netlist itself (`lvs.reference:
design/netlist/por_comparator.spice`, `lvs.subckt: por_comparator`), not a
hand-copied reference. `por_comparator.ref.spice` is the unit-rewritten form
`compose-cell.py` hands to `klt lvs` (only `L=`/`W=` unit spellings differ).

Drawn extent 8008.3 x 65.6 um (x -10.0..7998.3, y -28.1..37.5). The width is
the divider: the resistors are straight, uncompacted bodies (see
"Resistors"). Density optimization is a follow-on.

## Recipe

```
python3 layout/bin/compose-cell.py layout/por_comparator/cell.json
python3 layout/bin/compose-cell.py layout/por_comparator/cell.json --check
```

`cell.json` is the only hand-maintained input. It calls `klt gen` once per
block (`mos_array`, `res_array`, `guard_ring`; outputs in `gen/`), places the
blocks with `placement.strategy: "explicit"`, routes with `klt gen-compose`
(`compose.request.json` / `compose.response.json`), then runs `klt drc`,
`klt extract` and `klt lvs` (`drc.json`, `extract.json`, `por_comparator.spice`,
`lvs.request.json`, `lvs.json`). `promo_stub.gds` and `promo_stub_v.gds` are
byte copies of the declare-only pad stubs the `bias_core_*` cells use.
`--check` rebuilds in a temp directory and compares `status`/counts/bbox
fields; it does not compare GDS bytes, so `por_comparator.gds` is committed as
evidence but is not itself diffed.

### Tool build

`layout/pdk.json` pins `klt` commit `0ce8c64842d9` (`0.6.0+g0ce8c64842d9`).
All evidence here was produced by exactly that commit, run without touching
the host's installed `klt`, which on the build host is a different, newer
build (`0.7.0+g6fd0278268cc`):

```
uvx --from "git+https://github.com/2AMLogic/klayout-tools@0ce8c64842d9" klt version --format json
# version 0.6.0+g0ce8c64842d9, git_commit 0ce8c64842d9cbcd7689d40ebfa3774355c1da4c,
# klayout 0.30.12 (expected 0.30.12)
```

To reproduce, put a `klt` wrapper that execs that `uvx` command first on
`PATH` before running `compose-cell.py`; with it `check_klt_pin()` stays
silent (no pin-drift warning). Deck: `sky130` curated deck,
`content_hash sha256:f8f2c3f48eada473dc34a7a8926c0b04fef446fb351a70a636ce43a9ca9c70ba`
(`released: false`). PDK variant `sky130A`; `layout/pdk.json`'s `open_pdks_commit`
is unchanged.

## Floorplan

Coordinates are um. Nothing is shared with, or edited in, any `bias_core*`
cell or `design/`.

- **NMOS row, y = 0**, orientation `none` (gates face north). Left to right:
  `XMENN` x=0, `XMDNB` 8, `XMBD` 14, `XMPASS` 22, `XMDIB` 28, `XMTAIL` 36,
  the `XMINA`/`XMINB` array 52, `XMDCMPO` 64, `XMI1N` 70, `XMI2N` 78.
- **PMOS row**, orientation `mirror_y` (gates face south), every origin set
  from its own gate-pad height so all PMOS gates land on y = 20: `XMENP` x=0,
  `XMENSRC` 40, the `XMLA`/`XMLB` array 46, `XMI1P` 70, `XMI2P` 78. `XMENP`
  sits directly above `XMENN`, `XMI1P` above `XMI1N`, `XMI2P` above `XMI2N`
  so each inverter's gate and drain pair is a short vertical li1 link.
- **Signal channel** y = 4..18 between the rows, one track per net.
- **Rails on met1**: `VDD` at y = 29 above the PMOS row, `VSS` at y = -6
  below the NMOS row, each spurring straight to the source pins and tap
  islands.
- **Bodies.** PMOS bulks: each PMOS (or the whole PMOS array) gets a
  `guard_ring` nwell tap island abutted at a 0.10 um nwell overlap
  (`bias_core_settle_flag`'s technique), tapped to `VDD`. NMOS bulks and the
  substrate: five p-tap islands `pst1..pst5` at x = 4, 18, 32, 58, 74 (y =
  -3.5) tapped to `VSS`, plus `pst_far` next to `XMHSW`.
- **Divider and hysteresis switch** (x >= 100): `XRTOP` (origin 100, 20),
  `XRBOT` (100, 12) and `XRHYS` (6869.65, 4) are straight resistor bodies;
  `XMHSW` (orientation `rotate_180`, origin 6880, -5) sits at the far end,
  next to `XRHYS`, where `SNSB` is. See "Long routes" for why that end is 6.9
  mm from the comparator.

### Resistors

Each resistor is its own `klt gen res_array` call (`flavor xhigh`, `num=1`,
`dummy=0`, `width_um=2.0`): one straight poly body, one device, no folding and
no segmenting, so each source resistor is exactly one extracted device. The
generator reproduced every length exactly (no quantization delta). Extracted
values, and the as-drawn geometry, independently of LVS:

| Source | Netlist `L`, `W` (um) | As drawn / extracted `L`, `W` (um) | Extracted `r_ohm` | Delta (L, W) |
|---|---|---|---|---|
| `XRTOP` | 7897.44, 2 | 7897.44, 2.0 | 7,897,440 | 0, 0 |
| `XRBOT` | 6769.23, 2 | 6769.23, 2.0 | 6,769,230 | 0, 0 |
| `XRHYS` | 775.0, 2 | 775.0, 2.0 | 775,000 | 0, 0 |

`r_ohm` is `klt extract`'s deck value (2 kohm/square x `L`/`W`, body only).
It is not a measured or PEX resistance: contact/head resistance, the PDK
model's width correction, temperature and process variation are not in it.
The netlist cards carry no `R`, only `L`/`W`, so the layout agrees with the
source exactly at the level the source is specified.

## Matching

Two pairs are meant to match: the differential pair `XMINA`/`XMINB` and the
mirror load `XMLA`/`XMLB`.

- **How they are matched.** Each pair is two units of **one** `mos_array`
  call (`rows=1 cols=2 topology=array dummy=1`; `nfet` `W=2 L=1` and `pfet`
  `W=4 L=1`), not two independent blocks. That gives, by construction:
  identical unit geometry and `L`/`W`; one orientation (`none` for the NMOS
  pair, `mirror_y` for the PMOS pair, same for both units); a fixed 2.24 um
  unit pitch; both units on the same y; and one dummy unit on each outside
  edge, so both active units see an identical neighbour on both sides
  (`XMINA`/`XMLA` = `U0`, `XMINB`/`XMLB` = `U1`). The `XMLA`/`XMLB` array
  sits in one nwell with one tap island.
- **What is not matched.** Routing is not symmetric: `U0` and `U1` connect to
  different nets (`SNS`/`VREF` on the gates, `NA`/`CMPO` on the drains),
  so their metal stacks, spurs and via pads differ in layer and length. There
  is no common-centroid (ABBA) arrangement, no shared diffusion, and no
  matched metal coverage or dummy poly beyond the dummy units. The dummy
  units' gates and source/drain pads are **not wired** (12 isolated li1
  pads, reported as `dead_metal` by `klt extract`): `mos_array` reports no
  ports for dummies, so they cannot be tied off (filed as
  [2AMLogic/klayout-tools#2904](https://github.com/2AMLogic/klayout-tools/issues/2904)).
  `klt extract` drops them as devices (`dummy_devices_dropped: 4`), which is
  why the device count is 21.
- **What LVS says about it.** Nothing about matching. `klt lvs` checks
  connectivity and `L`/`W`; it does not check orientation, spacing,
  surroundings or routing symmetry. Match quality here rests on the
  construction above and on a reviewer's look at the GDS, and has not been
  simulated or extracted with parasitics.

## Routing

Planes are named by `klt gen-compose` layer role (`metal` = li1, `metal2` =
met1, `metal3` = met2, `metal4` = met3, `metal5` = met4). Each net is a star
of legs from a hub pin, one plane per net, with the final approach to an
east/west-facing destination pin written out explicitly. Plane assignment was
solved by a scratch search over the pin and leg geometry (not committed):
two nets share a plane only when the layer's spacing holds between their
lines and between each other's via-stack pads; pads of adjacent pins 0.71 um
apart are what rule out putting both on met3 or above. `cell.json`'s
waypoints are the record.

| Net | Plane | Width (um) | Route length (um) | Notes |
|---|---|---|---|---|
| `VDD` | met1 (+ li1 spurs) | 0.17 | 8143.3 | rail y=29, long leg to `XRTOP` far end |
| `VSS` | met1 | 0.17 | 7906.0 | rail y=-6, long leg y=-28 to the far end |
| `N1` | met1 + li1 pair links | 0.17 | 6908.9 | long lane y=-24 to `XMHSW` gate |
| `BIAS_OKB` | met1 + li1 link | 0.17 | 194.3 | |
| `TN` | met1 | 0.17 | 25.6 | |
| `VDDA` | met1 | 0.17 | 31.0 | |
| `NBG` | met2 | 0.17 | 66.6 | |
| `CMPO` | met2 + li1 link | 0.17 | 106.9 | |
| `IBIAS` | met3 | 0.4 | 52.7 | + straight branch to the port pad |
| `SNS` | met3 + li1 link | 0.4 | 76.1 | |
| `BIAS_OK` | met4 + li1 link | 0.4 | 66.2 | |
| `NA` | met4 | 0.4 | 76.8 | |
| `VREF` | met4 | 0.4 | 33.4 | straight to the port pad |
| `SNSB` | li1 | 0.17 | 35.9 | divider tap, `XRBOT`/`XRHYS`/`XMHSW` |
| `POR_RAW` | li1 | 0.17 | 29.8 | |

Wired: all 15 nets (the six ports and nine internal), every MOS body tie,
every resistor substrate tie. Not wired: the dummy units (above).

### Long routes

The divider's `SNS` end (where the comparator senses) and its far end are one
resistor length apart, and the far end holds three connections: the `VDD` end
of `XRTOP`, the `SNSB` tap with `XMHSW`, and the `VSS` end of `XRHYS`. The
`SNS` end is placed beside the comparator, so `VDD`, `VSS` and `N1` (the
`XMHSW` gate) each have one long minimum-width lane (8143, 7906 and 6909 um).
Parasitics were not extracted. Order of magnitude only, by arithmetic on
drawn length: one 6.9 mm run of 0.17 um met1 is about 4e4 squares. The lanes
carry the divider's sub-uA current and a gate, so DC drop is negligible, but
the wire capacitance on `N1` loads the `XMI1P`/`XMI1N` output and the
hysteresis switching speed has not been simulated. The high-impedance node
(`SNS`) was deliberately kept short and the long runs put on low-impedance or
supply nets. A folded or tighter divider is a follow-on.

## Ports

The six subcircuit ports are promoted from declare-only 1.5 um li1 stubs
(`stub_*`), each routed to its net; the pad is the stub's `PAD` end.

| Port | Pad (x, y) um | Pad faces | Reaches |
|---|---|---|---|
| `VDD` | (-6.0, 29.0) | west | met1 `VDD` rail |
| `VSS` | (-6.0, -6.0) | west | met1 `VSS` rail |
| `BIAS_OK` | (-10.0, 7.5) | west | `XMENN`/`XMENP`/`XMPASS` gates |
| `IBIAS` | (16.63, -12.0) | south | `XMBD`/`XMPASS`/`XMDIB` drains |
| `VREF` | (55.16, 37.5) | north | `XMINB` gate |
| `POR_RAW` | (88.0, 0.5) | east | `XMI2P`/`XMI2N` drains |

Verified against the extracted netlist, not just by label: `klt extract`
reports, for each port net, the pad label and an interior label on the same
net (e.g. `BIAS_OK` at (-10.0, 7.5) and at the `XMENP` gate (0.67, 10.8);
`VREF` at (55.16, 37.5) and (55.16, 19.3)), with no merged-label warning and
no unexpected net. Per-net device-terminal counts agree with the schematic:
`VDD` 11 (4 sources, `XRTOP`, 6 PMOS bulks), `VSS` 25 (9 NMOS sources, `XRHYS`,
12 NMOS bulks, 3 resistor substrates), `BIAS_OKB` 6, `N1` 5, `CMPO` 5. A
second, independent check paired all 21 source cards with the 21 extracted
devices on class, `L`, `W` and the terminal nets (source/drain either way,
gate, bulk; resistor ends and substrate), 21 of 21. `VSS` and `VDD` are
separate nets with no merge.

`layout/bin/check-promotion.py layout/por_comparator/cell.json` composes a
dummy destination onto each pad: all six routed (`unrouted_nets: []`). Its
throwaway destination always uses a horizontal stub, and its own DRC reported
4 `li1.width.1` slivers on the two vertical-stub pads' harness-side stubs
only. That output is harness artefact, not this cell's DRC, and is not
committed.

## Verification detail

`klt drc --deck sky130`: `clean`, 0 violations.

`klt extract --deck sky130`: `status: extracted`, 21 devices, 15 nets, 15 pin
labels (the six ports and nine internal nets, each labelled).
`device_counts`: `{"nfet": 12, "pfet": 6, "res_xhigh_po": 3}`. Body/substrate
mapping as extracted: all 12 NMOS bulks on `VSS`; all 6 PMOS bulks on `VDD`,
including `XMLA`/`XMLB`, whose sources are `VDDA`; all three resistors'
substrate terminal on `VSS`. No `vsubs` net remains.

`klt lvs`: `match`, devices 21/21, nets 15/15, `mismatch_count: 3` (all
warnings: `device.geometry_not_compared`, `device.parameter_excluded`,
`device.placeholder_value`), `error_count: 0`. What was compared, from
`device_parameter_coverage`: MOS classes: `L` and `W` and all four
terminals including bulk; resistor class: `L` and `W` (via
`lvs.options.compare_parameters: {"res_xhigh_po": ["L", "W"]}`) and the three
terminals including the substrate. What was **not**:

- **`R` of the three resistors**, `device.placeholder_value`: the subckt-call
  reference form carries a literal `0`, so resistor *values* are paired on
  topology plus `L`/`W` only. A topology match is not resistance
  verification; the as-drawn and extracted values are in the table above and
  were checked against the netlist's `L`/`W` directly. Related:
  [2AMLogic/klayout-tools#2461](https://github.com/2AMLogic/klayout-tools/issues/2461)
  (closed; the disclosure this relies on),
  [#2905](https://github.com/2AMLogic/klayout-tools/issues/2905) (filed here:
  the extractor knows `r_ohm`, the reference converter does not).
- **`A`/`P` of the resistors** (`device.geometry_not_compared`, secondary
  parameters) and **`AS`/`AD`/`PS`/`PD` of the MOS** (netlist estimates like
  `as=0.58`, extracted from drawn diffusion): not compared, no effect on the
  verdict.
- **Source/drain assignment** of the symmetric MOS is not preserved and need
  not be (`XMHSW` is drawn `rotate_180`).

Negative control (scratch copy of the reference, not committed): changing
`XRHYS` `L` from 775.0 to 800.0 and `XMTAIL` `W` from 1 to 1.4 turns the
verdict to `mismatch` with `device.property` errors on `l_um` and `w_um`, so
`L`/`W` of both a resistor and a MOS really are compared.

## Known gaps

1. **No `hvi` thick-oxide marker is drawn** at the pinned build: all 18 MOS
   are the 5 V devices' `W`/`L` drawn in the 1.8 V domain's geometry, and
   neither `klt drc` nor `klt lvs` can see it, so the match is as clean as it
   would be with the marker present (same disclosure as the `bias_core_*`
   MOS cells, [2AMLogic/klayout-tools#1912](https://github.com/2AMLogic/klayout-tools/issues/1912)).
   The issue is closed upstream and a later `klt` (the host's `0.7.0+g6fd0278268cc`
   reports `voltage_flavor_mark_present: true` in a probe) draws the marker;
   redrawing this cell with it belongs to the pin bump that regenerates every
   `layout/*/` directory together. This cell is not 5 V sign-off.
2. **Floating dummy units** in both arrays (#2904, above).
3. **No substrate tap along the resistor bodies**: the three bodies run up to
   7.9 mm over p-substrate; the nearest taps are at the two ends of the
   divider (`pst1..pst5` near x=4..75, `pst_far` at x=6883). The extractor
   ties all three resistors' substrate terminal to `VSS`.
4. **Long single-plane lanes** (above) and the 8 mm footprint: uncompacted,
   unextracted, unsimulated.
5. **Not run:** `klt erc`. Parasitic extraction and a post-layout threshold
   campaign were added later (issue #124): see [`pex/README.md`](pex/README.md).
6. **Not a signoff citation.** `manifests/` is unchanged apart from the
   item-2 explanation in `manifests/README.md`; no citation points at this
   directory.
