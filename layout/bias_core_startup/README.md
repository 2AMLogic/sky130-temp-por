# `bias_core_startup`

Standalone proof-of-concept layout for `design/netlist/bias_core.spice`'s
`XKS0..XKS4`/`XKA`/`XKAN`/`XKPD`/`XKICK` device group — `design/bias_core.md`'s
startup kick chain. Issue #38 (part of #34, a device-group split of "T1 item
2/10 continued", itself a follow-on from #30/#36/#37), decomposed for size
from #34. Follows the compose-cell recipe `layout/bias_core_pnp8_leg/`
(#30/PR #33) established, and mirrors `layout/bias_core_settle_flag/`'s
own all-MOS, multi-block, per-net-`layer_role` recipe (#39/PR #46) —
this is the second sub-block in this repo to reach a full `klt lvs`
`match`.

| Device | Ports (device-card order: `D G S B`) | Size |
|---|---|---|
| `XKS0` | `VDD` `VDD` `KS1` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=1` |
| `XKS1` | `KS1` `KS1` `KS2` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=1` |
| `XKS2` | `KS2` `KS2` `KS3` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=1` |
| `XKS3` | `KS3` `KS3` `KS4` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=1` |
| `XKS4` | `KS4` `KS4` `NKG` `VSS` | `nfet_g5v0d10v5`, `L=8` `W=1` |
| `XKA` | `NKM` `PB` `VDD` `VDD` | `pfet_g5v0d10v5`, `L=4` `W=1` |
| `XKAN` | `NKM` `NKM` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=2` |
| `XKPD` | `NKG` `NKM` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=8` |
| `XKICK` | `PG` `NKG` `VSS` `VSS` | `nfet_g5v0d10v5`, `L=4` `W=1` |

`XKS0..XKS4` is a 5-stage diode-connected NFET stack, each device's own gate
tied to its own drain (`XKS1 KS1 KS1 KS2 VSS`), chained `VDD -> KS1 -> KS2 ->
KS3 -> KS4 -> NKG` — the placement below respects that series ordering
rather than treating the five devices as an independent matched array.
`XKA`/`XKAN`/`XKPD` form the kick node's own pull-down/mirror network around
`NKM`, and `XKICK` injects the kick pulse onto `PG`, gated by `NKG`. Ten
nodes cross this group's boundary: `VDD`, `VSS`, `KS1`, `KS2`, `KS3`, `KS4`,
`NKG`, `NKM`, `PB`, `PG` — exactly the Test Plan's own net list.

## Recipe

Each device is its own single-instance `klt gen mos_array` call (`rows=1
cols=1 dummy=0 gate_contact=true`, `flavor` per device) rather than a matched
array — these nine devices do not match each other the way `bias_core_pnp8_leg`'s
8:1 ratio leg does, and `XKS0..XKS4`'s own `L=8 W=1` sizing is shared only by
construction (a diode chain), not by any matching intent. `layout/bin/compose-cell.py
layout/bias_core_startup/cell.json` runs the full `gen` -> `gen-compose` ->
`drc` -> `extract` -> `lvs` chain and writes every step's response next to
this file, same shape as the sibling recipes. Re-verify with:

```
python3 layout/bin/compose-cell.py layout/bias_core_startup/cell.json --check
```

`reference.spice` is a hand-extracted, byte-for-byte copy of
`design/netlist/bias_core.spice`'s own nine device cards, wrapped in a
10-port `.subckt` — not an xschem export, since the design's own `.subckt
bias_core` is the whole cell, not this group alone.

## Floorplan

`placement.strategy: "explicit"`. Drawn extent 89.04 x 8.82 um (bbox
`x0=-35.0 y0=0.0 x1=54.04 y1=8.82`) — one long, low row.

- **`XKS0..XKS4` sit in one row** (`kpd`, `ks4`, `ks3`, `ks2`, `ks1`, `ks0`
  left to right), `orientation: "none"`, placed so each stage's `U0_S`
  (west-facing) meets the next stage's `U0_D`/`U0_G` (east-facing) directly
  across a small gap — `mos_array`'s `S` is always drawn on the block's own
  west edge and `D` on its east edge, so the chain's `VDD -> KS1 -> KS2 ->
  KS3 -> KS4 -> NKG` direction runs **right to left** (`ks0` rightmost,
  `kpd`/`ks4` leftmost) for every adjacent pair to land on opposite-facing
  ports without a reach-around.
- **`kick` and `kan` are `orientation: "mirror_x"`** (negates local x and
  swaps `U0_S`/`U0_D`'s east/west facing), so their own `U0_S` faces the
  chain/tap it needs to reach directly. Note `klt`'s own `offset_um`
  semantics for a mirrored block: `origins_um` places the block's
  **pre-mirror local `x=0` corner** — i.e. the resulting `bbox_x1`, not
  `bbox_x0` — so the block extends further **negative** x from its own
  declared origin.
- **`XKA`'s PFET well is tied to `VDD` by nwell-merging** `nwell_tap` with
  `ka` (bboxes overlap by design — see `layout/bias_core_settle_flag/README.md`'s
  own "0.10um nwell overlap" worked example and the `gf180-temp-por`
  precedent this repo carries forward). An **NMOS** body/substrate tie needs
  no such per-device treatment: it is a globally synthesized net regardless
  of any drawn contact (confirmed empirically against this repo's own `klt`
  build — two `mos_array` NFETs 100um apart with no shared geometry both
  extract `body=vsubs`, the *same* net), so `psub_tap` only needs **one**
  routed strap into the real `vss` bus anywhere, not one per NFET. A PFET's
  well is **not** globally synthesized this way, so `XKA`'s own well tie is
  real, physical nwell-merging, not routing alone.

## Routing

Per-net `connectivity[].layer_role`
([`klayout-tools#1655`](https://github.com/2AMLogic/klayout-tools/issues/1655)),
the same technique `bias_core_settle_flag`'s own README documents: every net
routes on the base `"metal"` (li1) role **except** `nkm`, which is given its
own `"metal2"` (met1) role so its bundle route — connecting `kpd.U0_G`,
`kan.U0_D`, `kan.U0_G`, and `ka.U0_D` — does not cross `nkg`'s own li1
"attic" run (`kick.U0_G -> kpd.U0_D`, which detours north to `y=10.0` to
clear `XKPD`'s own tall (`W=8`) block) at the shared `x≈2.42` column both
nets' own routers would otherwise need to cross.

Every leg is steered explicitly through `connectivity[].legs[]`
([`klayout-tools#1529`](https://github.com/2AMLogic/klayout-tools/issues/1529))
rather than left to the automatic nearest-first spanning tree.
`compose.response.json` records `routed: true` for every net **and** for
every named leg.

**`vdd`'s own `ka.U0_S -> nwell_tap.TAP_E` leg is short and direct, not an
attic route — deliberately.** An earlier attempt routed `ka.U0_S` up to the
same long `y=13.0` attic bus the rest of `vdd` uses (mirroring
`bias_core_settle_flag`'s own `nwt_mpok.TAP_N -> mpok.U0_S` technique, which
uses a long horizontal run well above the row instead of a short direct
hop). That failed `gen-compose`'s own interior-crossing check (`"backbone's
0.17um-wide drawn path crosses ... through its own pin's block"`) — `ka`'s
`U0_S` port faces **west**, so forcing an immediate vertical departure
toward the attic disagreed with the port's own facing direction. The short
direct hop to `nwell_tap.TAP_E`, in the port's own facing direction, is what
actually routes.

**The two `nwell_tap`/`ka` bbox overlap needed for the nwell merge (above)
initially put `nwell_tap`'s own guard-ring li1 too close to `ka`'s own li1
even with no wire between them** — two `li1.space.1` violations, reported
against `nwell_tap`'s own ring geometry, independent of any routed net.
Reducing the raw bbox/nwell overlap from ~0.22um to ~0.10um (nudging
`nwell_tap`'s origin 0.12um further west, matching the
`bias_core_settle_flag`-documented "~0.10um nwell overlap, li1 clear"
convention) cleared both without breaking the nwell merge itself.

### Known klt gap: `from_stage` promotion of gate-contact pins through a bundle net (filed, worked around)

An earlier draft of this cell.json used the `"stages"`/`blocks[].from_stage`
two-pass technique (`docs/cli/gen-compose.md`'s own pattern, also used by
`sky130-trng`'s `layout/ro_stage/cell.json`) to move `nkm` off the base
`"metal"` role after it crossed `nkg`: label the four target ports
declare-only via `pins[]` in a first stage, then re-place that stage's whole
composed output as one opaque block (`{"id": "core", "from_stage": "core"}`)
in a second stage and route `nkm` there at `"metal2"`. That reproducibly
failed — `gen-compose` reported **every one of the six pairwise candidate
legs** among the four promoted ports as `routed: false`, each citing a
same-layer `li1.space.1`-style spacing violation against `"block 'core''s
own drawn geometry"`, at coordinates that resolve to the promoted ports'
own reported positions. Switching to the **single-pass, per-net
`connectivity[].layer_role`** technique documented above — routing the
identical four ports directly, in one `gen-compose` call, no `from_stage`
indirection — resolved it with the *same* underlying device geometry, no
floorplan change. Filed generically, with the full reduced repro (the
failing `"stages"` cell.json and the exact `gen-compose` response), as
[`2AMLogic/klayout-tools#1917`](https://github.com/2AMLogic/klayout-tools/issues/1917).
Not currently blocking anything in this repo — the workaround is the
landed recipe, not a stopgap.

## Verification

Reproduced with `--check` (rebuild into a temp dir, diff the verdict-bearing
fields) at the `klt` build `layout/pdk.json` pins.

- **`klt drc --deck sky130`: clean, 0 violations.**
- **`klt extract --deck sky130`: 9 devices, 10 nets.** `device_counts` reads
  `{"nfet": 8, "pfet": 1}` (eight `XKS0..XKS4`/`XKAN`/`XKPD`/`XKICK` NFETs,
  one `XKA` PFET). The ten nets are exactly the ten boundary nodes — `vdd`,
  `vss`, `ks1`, `ks2`, `ks3`, `ks4`, `nkg`, `nkm`, `pb`, `pg` — matching the
  Test Plan's own net list.
- **`klt lvs` against `reference.spice`: `match`** — 9/9 devices, 10/10
  nets, 10/10 pins, `mismatch_count: 0`, `error_count: 0`.

As with `bias_core_settle_flag`, two things this match does not assert:

1. **Source/drain assignment is not preserved, and is not meant to be** — a
   4-terminal MOS is S/D symmetric and `NetlistComparer` treats it so.
2. **`AS`/`AD`/`PS`/`PD` are not compared** — the extracted values come from
   the drawn diffusion and the design's own cards carry xschem's estimates;
   `klt lvs` compares `L`/`W` and topology, not the parasitic-area
   parameters.

## The one thing this layout does not yet say

Same disclosure as `bias_core_settle_flag`: `klt gen` **cannot draw sky130's
`hvi` (75/20) thick-oxide marker**, so every device in this cell is the
design's 5V `g5v0d10v5` `W`/`L` drawn in the 1.8V domain's geometry.
`klt drc`'s sky130 deck reads no `hvi` rule, and `klt lvs` deliberately maps
both voltage flavours onto one device class, so the `match` above is exactly
as clean as it would be with the marker present. Filed generically as
[`2AMLogic/klayout-tools#1912`](https://github.com/2AMLogic/klayout-tools/issues/1912);
the **topology** of this device group is verified against the schematic and
the floorplan is not expected to change when the gap closes, but this cell
must not be treated as 5V-domain sign-off until it is redrawn with the
marker and re-run against a deck that checks the `hvi` thresholds.
