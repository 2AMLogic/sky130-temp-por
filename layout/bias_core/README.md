# layout/bias_core

`bias_core` is `design/netlist/bias_core.spice`'s top-level subckt: `.subckt
bias_core VDD VSS IBIAS VREF BIAS_OK`, 50 devices across six device groups,
each already landed as its own standalone proof cell
([`bias_core_pnp8_leg`](../bias_core_pnp8_leg/README.md),
[`bias_core_xq1_xqr`](../bias_core_xq1_xqr/README.md),
[`bias_core_passives`](../bias_core_passives/README.md),
[`bias_core_settle_flag`](../bias_core_settle_flag/README.md),
[`bias_core_startup`](../bias_core_startup/README.md),
[`bias_core_mirror_amp`](../bias_core_mirror_amp/README.md)). This directory
is issue #40's own full-cell assembly: all six composed together as opaque
`blocks[].cell` siblings (`layout/bin/compose-cell.py`'s "existing composed
stream as a block" mechanism — see that script's own docstring, "Placing an
already-composed sibling cell") against `bias_core`'s own real subckt
interface.

## Result

All numbers below come from `klt 0.6.0+g0ce8c64842d9` (klayout-tools
`main` @ `0ce8c64842d9cbcd7689d40ebfa3774355c1da4c`, the `layout/pdk.json`
pin since issue #81; KLayout 0.30.12), rendered by
`python3 layout/bin/compose-cell.py layout/bias_core/cell.json`.

**`klt drc --deck sky130`: clean, 0 violations.** **`klt extract --deck
sky130`: 50 devices** (18 nfet + 16 pfet + 10 pnp + 4 res_xhigh_po + 2
cap_mim — matching `design/netlist/bias_core.spice`'s own device count
exactly), **27 nets, 27 pins**. `merged_net_labels[]` records only the
intended assembly-pin/sub-block-label joins (`VDD|vdd`, `VSS|vss`,
`IBIAS|ibias`, `VREF|vref`, `BIAS_OK|bias_ok`).

**`klt lvs` against `design/netlist/bias_core.spice`'s own `.subckt
bias_core`: `status: "match"` — 50/50 devices, 27/27 nets matched**, 0
errors. That is up from the pre-#81 baseline of 21/50 devices and 14/27
nets (41 layout nets). The reference netlist is unchanged. The match comes
with five warnings, and each one limits what it proves:

- `device.parameter_excluded`: the `PNP` compare is scoped to `NE` (the
  same scope the two PNP sub-cells use), so `AE` is **not** verified.
- `device.placeholder_value` ×2: the subckt-call reference carries `R=0` /
  `C=0` placeholders for the 4 `res_xhigh_po` and 2 MiM caps, so resistor
  and capacitor **values** are not compared.
- `device.geometry_not_compared` ×2: resistor `L/W/A/P` and MiM `A/P` are
  KLayout *secondary* parameters and are not compared.

So the match proves topology: every device's terminals land on the right
nets, with no opens and no shorts across the 27 nets. It does not prove
device sizing.

`python3 layout/bin/compose-cell.py layout/bias_core/cell.json --check`
reproduces this result byte-for-byte (exit 0), and so does each of the six
sub-block cells at the same pin.

**`klt erc` (T1 item 11 supply spec): `erc_status: clean`, 0 findings.**
Reproduce from the repo root:

    klt erc layout/bias_core/bias_core.gds \
         layout/bias_core/erc-supply-spec.json \
         --format json > layout/bias_core/erc.json

`VDD` and `VSS` each resolve to exactly **one** electrical island (zero
`erc.unconnected_net`, zero `erc.supply_short`) over 18 gate nets. The run
omits `--pdk` on purpose, so the top-level `status` is `not_checked` and
the command **exits 4**. The structural verdict is `erc_status`, not the
exit code. No `ties[]` are declared, so `erc.missing_tie` is **not
computed**. The spec rationale, including why it has no ties and what its
`devices[]` cuts do, is in
[`erc-supply-spec.md`](erc-supply-spec.md). The spec cannot carry it
inline because klt at this pin rejects unknown keys such as `_comment`.

**Pad-point island census:** `python3 layout/bin/pad-island-census.py
layout/bias_core/cell.json` exits 0, with the result committed as
`pad-island-census.json` and pinned to the GDS sha256. It probes all 15
connectivity/pin nets at 39 declared pads, and each net is exactly one
island. The census uses the ERC spec's graph, including the `devices[]`
cuts, so each island name also shows that the nets stay apart: `VDD,vdd`,
`VSS,vss`, `VREF,vref`, `ec`, `er`, `n2`, `na`, `nb`, `nbtop`, `nkg`,
`nokx`, `pb`, `pg`, `IBIAS,ibias` and `BIAS_OK,bias_ok`. One probe has a
weaker guarantee: `passives.nb` is a net that `bias_core_passives` wires
internally but cannot promote, because `klt gen-compose` refuses `pins[]`
on a port that its `connectivity[]` already wires. That block's
`compose.response.json` therefore reports no `nb` port. The probe is
recorded as `assembly_declaration_unpromoted_sibling_port`, and the #69
frame check cannot run for it. The landing is still independently
confirmed by the LVS match on `NB`. The census proves same-net
connectivity. Cross-net shorts are excluded by extract/LVS (27 separate
nets matched one-to-one), not by the census.

## Placement

All six sub-blocks are placed as pre-existing, already-verified GDS streams
(no `klt gen` calls in this cell.json at all — every `blocks[]` entry is a
`cell` reference, never a `generator`), each with its own compose-time
`ports[]` hand-declared at that block's exact reported coordinates
(`bias_core_*`'s own `compose.response.json`), so `klt gen-compose` sees
this composition exactly as any downstream caller of these six cells would:

| Block | Origin (µm) | Device group |
|---|---|---|
| `mirror_amp` | (0, 100) | current-mirror + error-amp (issue #35) |
| `xq1_xqr` | (150, 100) | `XQ1`/`XQR` reference PNPs (issue #36) |
| `pnp8_leg` | (200, 100) | `XQ8A..XQ8H` 8:1 PNP leg (issue #30) |
| `startup` | (1350, 100) | startup kick chain (issue #38) |
| `settle_flag` | (5450, 100) | settle-flag output stage (issue #39) |
| `passives` | (0, -50) | bias/ratio resistors + Miller caps (issue #37) |

The resulting composed bbox is **`x: -104..5533.86, y: -50..165.17`** —
still sparse by construction (`bias_core_passives` alone is ~5534µm wide,
and every block sits hundreds to thousands of µm from its neighbours to
leave room for the cross-block routing corridor described below). Each
device block's hand-declared `ports[]`/`bbox_um` are written in **that
block's own local frame**, exactly as its own `compose.response.json`
(or, for the two PNP blocks, `gen/array.gen.json`) reports them, because
`klt gen-compose`'s contract treats them that way:
`placement.origins_um` is the single translation into this cell's
assembly frame, so route landings land on the placed blocks' **real**
port geometry. An earlier revision of this cell.json pre-translated those
same entries into the assembly frame before handing them to the tool,
which applied the origin a second time — every route landing pad sat
100µm off each real pad, the assembly rails touched none of the blocks'
internal supply networks, and the composed bbox ballooned to
`x: -104..10940.99, y: -100..265.17`. That double-offset was
deliberately left in place at #40 time ("cosmetic"), but [#69]'s island
census disproved the "cosmetic" verdict and the entries were rewritten
back to the reported block-local coordinates — a real routing change, not
a coordinate cleanup: the VDD approach corridors were re-derived
(including a rise-at-`x=5445` column threading the gap between
`settle_flag`'s `bias_ok` stub and its `vdd` pad, a gap the old
phantom-landing routes never had to fit through), DRC re-verified clean,
and the pad-point island census re-run — committed as
`layout/bin/pad-island-census.py` +
`layout/bias_core/pad-island-census.json`. The declare-only top-level
promoted pins (`IBIAS`, `VREF`, `BIAS_OK`) land on the real pads too —
`IBIAS` at (58.63, 142.97), `VREF` at (13.63, 126.97), `BIAS_OK` at
(5443.585, 119.5) — where the pre-#69 run stamped them a full origin
higher (142.97+100, 126.97+100, 119.5+100 plus the x-translation for
`settle_flag`'s origin, e.g. a `BIAS_OK` pin at (10893.585, 219.5)).

`bias_core_pnp8_leg`'s `ec` escape stub is wired to `passives.ec` (issue
#81). Its `vss` reaches `VSS` through the block's own collector strap, the
same as in its standalone evidence.

## What is wired

Every net that crosses a device-group boundary in
`design/netlist/bias_core.spice` is wired. Each one is listed below with its
plane. Role names are the `klt` sky130 deck's routing roles: `metal` = li1,
`metal2` = met1, `metal3` = met2, and since klayout-tools#2738 `metal4` =
met3, `metal5` = met4, `metal6` = met5.

| Net | Plane (role) | Width (µm) | Pins |
|---|---|---|---|
| `VDD` | li1 (`metal`) | default | `mirror_amp` / `startup` / `settle_flag` / `passives` `vdd` + west `stub_VDD` |
| `VSS` | met1 (`metal2`) | default | `mirror_amp` / `startup` / `settle_flag` `vss` + west `stub_VSS` |
| `nkg` | met2 (`metal3`) | default | `startup` ↔ `settle_flag` |
| `n2` | met3 (`metal4`) | 0.4 | `passives` ↔ `mirror_amp` |
| `nb` | met3 (`metal4`) | 0.4 | `passives` (XRT/XR1 strap) ↔ `mirror_amp` |
| `ec` | met3 (`metal4`) | 0.4 | `passives` ↔ `pnp8_leg` |
| `VREF` | met3 (`metal4`) | 0.4 | `passives` ↔ `mirror_amp` (top-level pin) |
| `er` | met3 (`metal4`) | 0.4 | `passives` ↔ `xq1_xqr` |
| `nbtop` | met3 (`metal4`) | 0.4 | `passives` / `settle_flag` → `mirror_amp` |
| `nokx` | met4 (`metal5`) | 0.4 | `passives` (XCOK top plate) ↔ `settle_flag` |
| `pg` | met4 (`metal5`) | 0.4 | `passives` (XCC top plate) / `startup` → `mirror_amp` |
| `na` | met4 (`metal5`) | 0.4 | `xq1_xqr` / `settle_flag` → `mirror_amp` |
| `pb` | met5 (`metal6`) | 1.6 | `startup` / `settle_flag` → `mirror_amp` |

`IBIAS` and `BIAS_OK` are declare-only top-level pins on the one sub-block
pad each touches (`mirror_amp.ibias`, `settle_flag.bias_ok`). `VREF` used
to be declare-only too, but is now a real `connectivity[]` net named
`VREF`. A port may be promoted by `pins[]` or wired by `connectivity[]`,
not both, and the net has to reach `passives.vref` (XR2's node).

`nb` is a tenth net beyond the nine the issue named. The `mirror_amp` side
of `nb` (promoted by #56) has to meet XRT/XR1's shared strap inside
`bias_core_passives`. That strap is not a promoted port of that block (see
the census note above), so the assembly declares it at the strap's
midpoint (19.84, 1.0), read from the block's own GDS.

Two sub-block changes support this:

- **`bias_core_xq1_xqr`**: the auto-routed `Q0_B`–`Q1_B` met1 base bus ran
  across the middle of `Q1_E`'s emitter pad at y=1.7, exactly where the
  assembly must land `er`'s via ladder. A ladder there shorted `er` to
  `VSS` in a trial composition. That leg is now hand-routed along y=0.55,
  0.65 µm clear of the 0.42 µm landing pad. The cell still reaches LVS
  `match` (`layout/bias_core_xq1_xqr/lvs.json`).
- **`bias_core_pnp8_leg`**: no geometry change. The assembly now declares
  the block's existing `ec` escape stub (-5, 10) and its real composed bbox,
  both taken from that block's own `compose.response.json`.

None of this rests on `routed: true` alone. Every net is verified by the LVS
match (each reference net is matched to exactly one layout net, and no
layout net is left over), by `merged_net_labels[]` containing only the
intended joins, and by the pad-point island census.

## Layer plan

This is the plan the routes were built from. The waypoints in `cell.json`
are its concrete record.

**Constraint.** Before #81 the curated deck exposed three routable planes,
and `VDD` (li1), `VSS` (met1) and `nkg` (met2) used all three across the
shared corridor between the upper transistor row (y ≈ 94–165) and
`passives` (y = -50…-28). Every further net crossed one of them (#64).
klayout-tools#2738 added met3/met4/met5 as routing roles, so the nine
remaining nets (ten with `nb`) go on those three new planes and never
touch the lower three. `VDD`, `VSS` and `nkg` keep their existing routes
unchanged.

**Assignment rule.** No two nets on one plane may cross. Each plane
therefore gets a family of nets whose routes nest or sit side by side.

- **met3 (`metal4`): the vertical risers out of `passives`.** `n2`, `nb`,
  `ec`, `VREF`, `er` and `nbtop` all start on `passives`' li1 pads along
  y ≈ -49. Each rises on its own x column (`nbtop` x=-12, `nb` x=-10, `ec`
  x=378, `er` x=380, `VREF` x=1424), with `n2` running west along y=-30 to
  `mirror_amp`. Each then turns along its own y lane: `n2` -30, `nb`
  -38→122, `ec` 110, `er` -54→112, `VREF` 126, `nbtop` 126/130. Lanes are
  nested so that a net that rises further west turns at a higher or lower
  y than its neighbour and never crosses it. `er` runs under the passives
  row at y=-54, below every other riser's start, to reach x=380.
- **met4 (`metal5`): the nets whose `passives` end already sits on met4,
  plus `na`.** `pg` and `nokx` land on MiM top-plate contacts, which are
  met4 by construction (`passives`' `pg`/`nokx` ports are 71/20). Keeping
  them on met4 avoids a via ladder through the met3 bottom-plate level
  next to the caps. `pg` rises at x=1342 and runs west along y=116, `nokx`
  rises at x=5530 and runs west along y=88, and `na` runs along y=106/108
  (from `xq1_xqr`) and y=120 (from `settle_flag`). None of these lanes
  cross.
- **met5 (`metal6`): `pb` alone.** It spans the full upper row
  (`settle_flag` x≈5446 → `mirror_amp` x=16) along y=118, crossing the
  `pg` and `na` met4 lanes, so it takes the top plane by itself. Width is
  1.6 µm, sky130 `m5.1`'s minimum met5 width (the deck's own rule). The
  lower-plane 0.4 µm width is **not** reused on met5. The via4 landings
  are drawn by `klt gen-compose`'s `via5` role (physical via4, 71/44) and
  pass the deck's `via4.*`/`m5.*` rules.

Signal widths on met3/met4 are 0.4 µm, above `m3.1` (0.3 µm) and `m4.1`
(0.3 µm).

**How the plan was checked.** The waypoints were laid out with a scratch
maze search over the endpoint coordinates the sub-blocks report (that
helper was not committed; the `cell.json` waypoints are the record). Each
net was then added through `compose-cell.py`, where `klt gen-compose`
checks crossings and own-geometry collisions, followed by `klt drc`
(clean), `klt extract` and `klt lvs` (match).

## MiM capacitor clearance

`bias_core_passives` holds the two `sky130_fd_pr__cap_mim_m3_1` caps:
`XCC` (`PG`–`NZ`, 20×20 µm, capm at (1395.52, -49.5)–(1415.52, -29.5)) and
`XCOK` (`VDD`–`NOKX`, 6×6 µm, capm at (5527.36, -49.5)–(5533.36, -43.5)).
Both have their bottom plate on met3 and their top plate (capm, 89/44)
contacted by via3 up to met4. The only routes that touch them are the
intended ones: `pg` and `nokx` land on the met4 top-plate contacts, and
`VDD` lands on `XCOK`'s met3 bottom plate (`passives.vdd`). The
clearances below were measured on the committed GDS, with each
unrelated net checked against the plates:

| Check | Measured | Rule |
|---|---|---|
| unrelated met3 → met3 bottom plates | 2.725 µm | `m3.2` 0.3 µm |
| unrelated met3 → capm | 3.467 µm | (no capm–met3 spacing rule in the deck; `capm.3` is enclosure) |
| unrelated met4 → capm | > 20 µm (none within the search radius) | — |
| unrelated met4 → top-plate contact met4 | 1.562 µm | `m4.2` 0.3 µm |
| met4 overlapping capm that is not the plate's own net | 0 shapes | — |
| met5 (`pb`) → capm | > 20 µm | — |

The routing kept at least 2.7 µm (met3) and 1.5 µm (met4) clear of
each cap's plates and plate contacts, well above the 0.3 µm minimum
spacing. `klt drc` over the deck's `capm.*` rules (`capm.1`, `capm.2a`,
`capm.3`, `capm.4`, `capm.5`) is clean.

## Known klt gaps hit building this cell

- [`2AMLogic/klayout-tools#1962`](https://github.com/2AMLogic/klayout-tools/issues/1962) —
  `klt gen-compose` has no layer/track-assignment help for compositions
  with more mutually crossing nets than planes. Still open. This cell
  worked around it with the hand-made layer plan above, made possible by
  the extra planes from #2738.
- [`2AMLogic/klayout-tools#2210`](https://github.com/2AMLogic/klayout-tools/issues/2210) /
  [`#2218`](https://github.com/2AMLogic/klayout-tools/issues/2218) —
  `routed: true` checks landings against caller-declared coordinates only,
  and no `klt` verb exposes island membership. The in-repo backstop is the
  pad-point census (`layout/bin/pad-island-census.py`).
- [`2AMLogic/klayout-tools#2881`](https://github.com/2AMLogic/klayout-tools/issues/2881) —
  filed for #81: `klt gen-compose` refuses `pins[]` on a port its own
  `connectivity[]` already wires. A composed cell therefore cannot expose an internally
  wired net as a port without adding a stub branch, which is why
  `passives.nb` is assembly-declared (see the census note above).
- [`2AMLogic/klayout-tools#2822`](https://github.com/2AMLogic/klayout-tools/issues/2822) —
  already tracked: `klt erc`'s spec rejects unknown top-level keys at this
  pin, so a spec can no longer carry inline rationale (`_comment`). It now lives in
  [`erc-supply-spec.md`](erc-supply-spec.md).
- [`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894) —
  closed (as of the `klt 0.6.0` pin). The PNP collector straps land, and
  `ec`/`er` are now wired here.

## What's next

`bias_core` is the first full-cell assembly to reach LVS `match`.
`temp_core`, `por_comparator`, `por_output_chain` and `temp_por_top`
remain the layout work tracked from
[#4](https://github.com/2AMLogic/sky130-temp-por/issues/4). Sizing
verification of the passives (resistor and MiM values) needs a reference
form that carries real `R`/`C`, or a PEX run (T1 item 7). The match above
does not cover it.
