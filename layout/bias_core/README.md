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

**`klt drc --deck sky130`: clean, 0 violations.** **`klt extract --deck
sky130`: 50 devices** (18 nfet + 16 pfet + 10 pnp + 4 res_xhigh_po + 2
cap_mim — matching `design/netlist/bias_core.spice`'s own device count
exactly), **43 nets, 43 pins** — down from 50/50 before [#69]'s
landing-frame fix, and the delta is exactly that fix: each block's supply
island used to sit electrically separate from its rail, and the re-landed
routes merge them (extract's own `merged_net_labels[]` now records the
intended joins — `VDD|vdd`, `VSS|vss`, plus `IBIAS|ibias`, `VREF|vref`,
`BIAS_OK|bias_ok`, each one assembly-level pin label merging with the
corresponding sub-block's internal label on the *same* net). **`klt lvs`
against `design/netlist/bias_core.spice`'s own `.subckt bias_core`:
mismatch — 21/50 devices, 14/27 nets matched.** This is a real, partial
match, not the single "PNP collector-strap gap" the parent issue's own text
anticipated — see "What is not wired" below for the full, verified
root-cause breakdown, and
[#64](https://github.com/2AMLogic/sky130-temp-por/issues/64) for the
tracked follow-up that completes the remaining wiring.

`python3 layout/bin/compose-cell.py layout/bias_core/cell.json --check`
reproduces this result byte-for-byte.

**`klt erc` (T1 item 11 supply spec, issue #66): `erc_status: clean`, 0
findings — now on rails that reach the blocks' internal supply networks.**
`klt erc layout/bias_core/bias_core.gds
layout/bias_core/erc-supply-spec.json --format json` (reproduce from the
repo root; the spec's own `_comment` block documents and justifies every
field) reports `VDD`/`VSS` each resolving to exactly **one** continuous
electrical island under the declared stackup — zero `erc.unconnected_net`,
zero `erc.supply_short` — over 21 gate nets with the `active_layer` fix
(`poly ∩ diff`) applied (the pre-#69 run reported 22: the two separate
`nkg` islands and the island carrying the unconnected block-local `vdd`
pin each counted as their own gate net; the re-landed routes merge them,
one island per declared supply). The run omits `--pdk` on purpose
(antenna grading is not item 11's subject; the top-level `status` reads
`not_checked` and the command exits `4`), and declares no `ties[]`, so
`erc.missing_tie` is *not computed* — the spec's `_comment` records why
(sky130's native substrate makes a VSS tie undeclarable, and the blanket
`nwell → VDD` probe on this exact GDS reports exactly 2 findings
post-#69 — the two PNP device-group blocks' by-design tubs, see below —
where the pre-#69 probe reported 18 conflated ones, 0/18 reaching VDD:
the landing fix is what let every other n-well's taps reach VDD through
the connected supply network).

**Pad-point island census (issue #69's acceptance check, committed as
evidence):** `python3 layout/bin/pad-island-census.py
layout/bias_core/cell.json` re-runs the census that found the bug — it
builds the same `LayoutToNetlist` connectivity graph `klt erc` builds,
then probes a window at every pad the cell.json itself declares as a pin
of a connectivity net (each pad at its block-local declared port
coordinates, translated by `placement.origins_um` applied exactly once).
Committed as
`layout/bias_core/pad-island-census.json` (pinned to the GDS's sha256):
every probed net is one electrical island — the `VDD` rail shares the
island of `mirror_amp`/`startup`/`settle_flag`/`passives`'s real `vdd`
pads *and* the west `stub_VDD` pin (expanded island name `VDD,vdd`),
`VSS` likewise (`VSS,vss`), and `nkg` is a single shared island
rather than the two separate ones the pre-#69 census found. The upstream
coordinate-trust gap that let the pre-#69 composition report
`routed: true` while landing on pads that touched nothing is
[2AMLogic/klayout-tools#2210](https://github.com/2AMLogic/klayout-tools/issues/2210);
the cleanliness of a rerun is graded by `manifests/README.md`'s item-11
row.

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

`bias_core_pnp8_leg` has zero wired connections in this composition (both of
its own nets, `vss`/`ec`, are blocked — see below); it is placed purely to
be present as 8 real, if unconnected, PNP devices in the extracted netlist.

## What is wired

- **`VDD`** (top-level pin): a 4-way bus — `mirror_amp` → `startup` →
  `settle_flag` → `passives`, on `"metal"` (li1), routed through a shared
  west-of-everything stub (`stub_VDD`, a small declare-only `promo_stub.gds`
  block) for external visibility.
- **`VSS`** (top-level pin): a 3-way bus — `mirror_amp` → `startup` →
  `settle_flag` (not `passives`/`pnp8_leg`/`xq1_xqr` — see below), on
  `"metal2"` (met1), same `stub_VSS` external-pin mechanism.
- **`nkg`**: `startup` ↔ `settle_flag`, on `"metal3"` (met2), routed through
  a dedicated high lane (`y=200`, clear of every block's own bbox and of the
  `VDD`/`VSS` buses' own corridor) since this net does not need to reach
  `passives` at all.
- **`IBIAS`**, **`VREF`**, **`BIAS_OK`** (top-level pins): each declare-only,
  pointing directly at the one sub-block that touches it
  (`mirror_amp.ibias`, `mirror_amp.vref`, `settle_flag.bias_ok`) — no new
  metal drawn, matching every other single-touch-net promotion in this
  repo's own `bias_core_*` cells. **`VREF` is declare-only here — it is
  `bias_core_mirror_amp`'s own `vref` pin, not (yet) wired to
  `bias_core_passives`'s own `vref` pin** (`XR2`'s own node in the design);
  see below.

Each of these was verified electrically, not just via `klt
gen-compose`'s `routed: true` (`docs/cli/gen-compose.md`'s own "Geometry
is advisory" caveat: a routed, DRC-clean leg is not by itself proof of
correct connectivity — the pre-#69 composition was fully `routed: true`
while touching none of the blocks' real pads, which is exactly how that
gap survived until #69's island census). Post-#69 the verification is
`klt extract`'s own net-merge report listing the *intended* joins —
`VDD|vdd`, `VSS|vss` (each rail merging with the sub-block pads' internal
labels onto one net) and no unintended `supply_short` between them — plus
the committed pad-point island census (`pad-island-census.json`), which
probes every declared pad directly and shows one island per net *with*
`nkg` shared between `startup` and `settle_flag`. The upstream gap that
made `routed: true` trustable on nothing more than caller-declared
coordinates is
[2AMLogic/klayout-tools#2210](https://github.com/2AMLogic/klayout-tools/issues/2210).

## What is not wired

Every other net that crosses a device-group boundary in
`design/netlist/bias_core.spice` — `pg`, `pb`, `n2`, `na`, `nbtop`, `vref`
(the `mirror_amp` ↔ `passives` half), `nokx`, plus both PNP groups' own
`ec`/`er`/(the rest of) `vss` — is left unrouted this increment. Three
distinct, independently-confirmed root causes, not one:

1. **Insufficient routing layers for the number of mutually-crossing nets.**
   The curated sky130 deck exposes exactly 3 routable planes (`"metal"`/
   `"metal2"`/`"metal3"`). This composition needs on the order of 10
   cross-block nets, most of whose bounding boxes span most of the assembly
   (several sub-blocks sit far apart; `passives` alone is ~5534µm wide). At
   most 3 mutually-non-crossing nets can share one plane — `VDD`/`VSS`/
   `nkg` already claim all three across the shared corridor between the
   upper transistor cluster and `passives`, and every further net collided
   with one of those three (`klt gen-compose`'s own `crosses already-routed
   net '<name>'` diagnostic) no matter which layer or waypoint path was
   tried. `klt gen-compose` offers no assignment help for this — filed
   generically as
   [`2AMLogic/klayout-tools#1962`](https://github.com/2AMLogic/klayout-tools/issues/1962)
   per this repo's own friction protocol.
2. **A handful of pre-existing raw device pads reject *any*
   externally-approaching route outright**, independent of the layer-budget
   problem above (`klt gen-compose`'s own #1527 "own drawn geometry"
   self-collision check): `mirror_amp`'s own `nb` pin, and both
   `settle_flag`'s `na`/`nbtop` pins, sit too close to that sub-block's own
   already-drawn metal for a new externally-arriving leg to land without
   risking a silent short. This is the *same class* of gap issue #56 already
   fixed for six *other* pins on these same three sub-blocks (a declare-only
   west-edge metal stub, wired as an additional branch off the pin's own
   already-routed net, entirely inside that sub-block's own `cell.json` —
   see `bias_core_mirror_amp/README.md`'s own "Full-cell assembly pins
   (issue #56)" section) — `nb`/`na`/`nbtop` were not in #56's own scope and
   remain unfixed. `passives`'s own `pg`/`nokx` pins hit a related but
   distinct obstacle (their ports sit on a MiM cap's own top-plate `met4`
   layer, not `li1` — resolved *within this cell.json* via
   `connectivity[].layer_role: "cap_top_via_metal"` plus an explicit
   `width_um: 0.42` floor, confirmed DRC-clean and short-free in isolation —
   but still excluded from the final wiring set here purely by the
   layer-budget problem in (1) above, not by this obstacle).
3. **`ec`/`er` (the PNP collector/base/emitter buses on `pnp8_leg`/
   `xq1_xqr`) remain blocked by the already-tracked
   [`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894)** —
   confirmed directly, in this issue's own investigation, to extend to
   *any* leg leaving either block's own `Q*_B`/`Q*_E` ports, not only the
   collector strap the parent issue's own text anticipated. Two failure
   modes were reproduced: (a) composing the `bjt_array` generator alongside
   a new stub *within the same `gen-compose` call* (the technique that fixed
   finding 2's pins) is refused outright — `klt gen-compose` detects the
   block's own closed collector ring and rejects any leg from a non-tap
   port before even considering where the new pin would land; (b) treating
   `pnp8_leg`/`xq1_xqr` as opaque `blocks[].cell` siblings (hiding the ring
   from the composing call, since an opaque stream reports no `ports[]`
   beyond what this cell.json hand-declares) lets `klt gen-compose` draw a
   route and report `routed: true` with a clean `klt drc` — but `klt
   extract` then shows the tapped net silently merged with the ring's own
   internal base/collector bus (`er|vss` in one reproduction), the exact
   `#1894` finding-2 failure mode, just triggered from outside the block
   instead of from within it. `xq1_xqr`'s own `na` pin is the one exception:
   it is *already* a declare-only top-level promotion inside `xq1_xqr`'s own
   `cell.json` (an existing, previously-drawn pad, not a new leg), so it
   carries none of this risk — but it was left out of the final wiring set
   here purely by the layer-budget problem in (1), the same way `passives`'s
   `pg`/`nokx` were.

See [#64](https://github.com/2AMLogic/sky130-temp-por/issues/64) for the
tracked follow-up covering all three findings.

## Known klt gaps hit building this cell

- [`2AMLogic/klayout-tools#1894`](https://github.com/2AMLogic/klayout-tools/issues/1894) —
  already tracked (see `layout/README.md`'s own "Known klt gaps" section);
  finding 3 above extends its confirmed blast radius from "the collector
  strap only" to "any externally-approaching leg on either PNP group's own
  `Q*_B`/`Q*_E` ports".
- [`2AMLogic/klayout-tools#1962`](https://github.com/2AMLogic/klayout-tools/issues/1962) —
  new, filed this issue: `klt gen-compose` has no layer/track-assignment
  help for a composition with more mutually-crossing nets than available
  routing planes.
- [`2AMLogic/klayout-tools#2210`](https://github.com/2AMLogic/klayout-tools/issues/2210) —
  `klt gen-compose`'s `routed: true` verifies landings against the
  caller-declared port coordinates only, with no connectivity check that a
  leg's landing pin ever touches the placed block's internal net. #69's
  landing-frame fix survived precisely because of this gap (the pre-#69
  composition reported every net `routed: true` while touching none of the
  blocks' real pads); this cell now also commits a pad-point island census
  (`layout/bin/pad-island-census.py` → `pad-island-census.json`) as the
  in-repo backstop, and no `klt` verb exposes island membership today —
  filed generically as
  [2AMLogic/klayout-tools#2218](https://github.com/2AMLogic/klayout-tools/issues/2218).

## What's next

[#64](https://github.com/2AMLogic/sky130-temp-por/issues/64) tracks wiring
the remaining `pg`/`pb`/`n2`/`na`/`nbtop`/`vref`/`nokx` nets (findings 1 and
2 above) once a channel-routing/layer-assignment plan (by hand or via
`klayout-tools#1962`) is worked out, plus promoting `mirror_amp`'s `nb` and
`settle_flag`'s `na`/`nbtop` pins the same way issue #56 already did for six
other pins on these sub-blocks. `ec`/`er` (finding 3) stay blocked on the
upstream `#1894` fix. With `bias_core` now composed (even partially),
`temp_core`, `por_comparator`, `por_output_chain`, and `temp_por_top` remain
the layout work tracked from [#4](https://github.com/2AMLogic/sky130-temp-por/issues/4).
