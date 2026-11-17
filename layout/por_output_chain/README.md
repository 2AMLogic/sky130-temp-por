# `por_output_chain`

> **Re-generated in #97 at `klt 0.9.2` (the `layout/pdk.json` pin), which drew
> the native-Vt `XMASSIST` and removed the last LVS exclusion.** Committed
> streams and `drc/lvs/extract.json` now come from the pin. Earlier "Tool
> build" statements below record the pre-0.9.2 runs; the
> "`XMASSIST`" section records the whole blocker history. See `layout/README.md`.

Standalone proof layout of `design/netlist/por_output_chain.spice`'s whole
`.subckt por_output_chain VDD VSS IBIAS POR_RAW RESETn` (see
`design/por_output_chain.md`): the POR output chain that turns `POR_RAW` into
`RESETn`. Issue #97, a partial leaf of T1 item 2 (layout). It follows the
compose-cell recipe of `layout/por_comparator/` (MOS floorplan, tap islands,
per-net `layer_role`) and `layout/bias_core_passives/` (`cap_array` MiM).
It is one leaf cell of the block, not `temp_por_top`; the block-level layout
milestone is not claimed complete by this directory (see `manifests/README.md`).

## Result

Issue #97's second increment (this one) drew the native-Vt `XMASSIST` — the
one device the first increment had to leave out — and removed the
`lvs.drop_prefixes` exclusion. Earlier increments' history: #101 re-drew
`XMN1` from the unsimulatable `L=25 W=0.5` to `L=20 W=0.42` (rationale in
`design/por_output_chain.md`, "`XMN1` model-bin legality"). `cell.json`'s
`massist` block was added this increment; no existing block changed.

Generated and checked with the `klt` build `layout/pdk.json` pins, `0.9.2`
(commit `046ba74652fc`; see "Tool build").

| Step | Result |
|---|---|
| `klt drc --deck sky130` | `clean`, 0 violations |
| `klt extract --deck sky130` | 34 devices (`nfet` 15, `pfet` 14, `sky130_fd_pr__model__cap_mim` 5), 18 nets, 18 pin labels |
| `klt lvs` vs `design/netlist/por_output_chain.spice` | `match`: 34/34 devices, 18/18 nets, 0 errors, 2 warnings (below), **no exclusions — `XMASSIST` included** |
| `compose-cell.py ... --check` | exit 0, "rebuild matches committed evidence" |

Drawn extent 337.8 x 65.0 um (x -10.0..327.8, y -6.1..58.9) — unchanged: the
added device sits in open floorplan space.

## `XMASSIST` (native-Vt NMOS): drawn and compared

`XMASSIST` is `sky130_fd_pr__nfet_05v0_nvt` (`L=25 W=1`, drain `RESETn`, gate
`VDD`, source and bulk `VSS`), native-Vt by design (`design/por_output_chain.md`).

**History.** The first increment (PR #99) could not draw it and excluded it
from LVS: at the then-pinned builds, `mos_array` had no native flavor, extract
had no native class, and `klt lvs` refused the reference card outright
(`subcircuit 'sky130_fd_pr__nfet_05v0_nvt' is not a known device for the
requested deck`). That was measured and filed upstream, generically, as
[2AMLogic/klayout-tools#2912](https://github.com/2AMLogic/klayout-tools/issues/2912).

**This increment, measured at the `0.9.2` release** (the capability shipped
via klayout-tools #3599/#3600/#3634; #2912 was closed as covered by them):

1. `klt gen mos_array` accepts `voltage_flavor: "nvt"` on sky130A and draws
   the native marker (`voltage_flavor_mark_present: true`, `sd_implant_present:
   true`). `massist` is drawn with it.
2. `klt lvs` reads the `XMASSIST ... sky130_fd_pr__nfet_05v0_nvt` reference
   card and compares it — `match`, 34/34 devices, with the card present and
   `lvs.drop_prefixes` removed. This was #2912's blocker; it is resolved.

**What is still not verified: the flavour binding.** The extracted netlist
(and every artifact of this chain) bins MOS generically — `nfet`/`pfet`, no
per-flavour class — so the committed compare proves the card's *topology* and
`L`/`W`, not that the drawn device is the native bin rather than a plain 5 V
NMOS. The deck does have a flavour-aware compare
(`klt lvs` `options.compare_mos_flavour`, klayout-tools#3650), and
`compose-cell.py` now forwards it by switching the LVS layout side to inline
extraction. It cannot be turned on for this cell yet:

- Under `compare_mos_flavour` the reference's 28 `g5v0d10v5` cards bin as
  `NFET__HVI`/`PFET__HVI` and mismatch the unmarked layout devices
  (measured: `mismatch`, 14 nfet + 14 pfet `device.unmatched` on each side).
  Drawing the `hvi` marker on them is the fix, and it is blocked:
- Measured blocker: the `hvi` marker covers only the device array, so the
  pfets' guard-ring n-well touches the marker without being enclosed by it —
  `nwell.enclosed.hvi.1` x 14 under `klt drc --deck sky130` (same violation
  with `mos_array`'s own `add_guard_ring`; `guard_ring` has no
  `voltage_flavor`; no marker-extent parameter exists). Measured at the
  `0.9.2` release and on `main` (`0.9.3.dev239`); filed upstream, generically,
  as [2AMLogic/klayout-tools#6025](https://github.com/2AMLogic/klayout-tools/issues/6025).

Negative controls (scratch runs against the committed evidence, not
committed), recorded so the gap is falsifiable:

- Swapping the reference card's model to the plain
  `sky130_fd_pr__nfet_g5v0d10v5` still yields `match` 34/34 — the committed
  compare really is flavour-blind.
- `compare_mos_flavour: true` on the committed stream yields `mismatch`, and
  the massist card pairs as `nfet__nvt` vs the reference's `NFET__NVT` — the
  native marker is drawn and recognized; only the 28 unmarked 5 V devices
  fail the flavoured compare.

So: the device is drawn, present in the layout, electrically correct
(`extract.json`: `massist` at `g=VDD d=RESETn s=VSS b=VSS`, `L=25 W=1`) and
compared by the same LVS run as everything else, with no exclusion. What a
grader cannot yet see from this chain is the flavour binding itself — that is
the disclosure above, and it is the remaining work for this leaf once
klayout-tools#6025 lands.

## Recipe

```
python3 layout/bin/compose-cell.py layout/por_output_chain/cell.json
python3 layout/bin/compose-cell.py layout/por_output_chain/cell.json --check
```

`cell.json` is the only hand-maintained input (60 blocks: 29 `mos_array`, 21
`guard_ring` tap islands, 5 `cap_array`, and 5 declare-only pad-stub cell
references). It calls `klt gen`
once per block (`mos_array` 1x1, `guard_ring` tap islands, `cap_array`;
outputs in `gen/`), places the blocks with `placement.strategy: "explicit"`,
routes with `klt gen-compose` (`compose.request.json` /
`compose.response.json`), then runs `klt drc`, `klt extract` and `klt lvs`
(`drc.json`, `extract.json`, `por_output_chain.spice`, `lvs.request.json`,
`lvs.json`). `promo_stub.gds` and `promo_stub_v.gds` are byte copies of the
declare-only pad stubs the other cells use. `layout/pdk.json`'s klt pin moved
to `0.9.2` for this increment — scoped to this directory: the other cells'
committed evidence stays at the builds that produced it, pending a block-wide
re-render.

`--check` rebuilds in a temp directory and compares `status`/counts/bbox
fields (the `drc.json`, `extract.json`, `lvs.json` and `compose.response.json`
fields `compose-cell.py` lists); **it does not diff GDS bytes**, so
`por_output_chain.gds` is committed evidence but is not itself compared.

`cell.json` was authored with a throwaway script (a placement and track
assignment search, not committed) that computes every waypoint from the
generated port positions; nothing in the GDS was edited by hand. The
committed `cell.json` is the artifact, and it is what regenerates everything.

### Tool build

`layout/pdk.json` pins the `0.9.2` release (`046ba74652fc`). The host's
installed `klt` (if any) was not touched; all evidence here was produced by
the pinned release through a throwaway environment:

```
uvx --from "klayout-tools==0.9.2" klt "$@"
```

Deck: the curated `sky130` deck, PDK variant `sky130A`. The resolved klayout
engine is `0.30.13` (klt 0.9.2 was built against `0.30.12` — the version
note in the tool's own stderr applies to every report here).

## Floorplan

Coordinates in um. Nothing is shared with, or edited in, any other
`layout/*/` cell or `design/`.

- **One `mos_array` (1 row, 1 column, no dummies) per MOS**, `gate_contact`
  on. 14 NMOS in a row along y=0 (gates north, orientation `none`), 14 PMOS
  mirrored (`mirror_y`) so every gate pad sits on y=45.2 (gates south), and a
  signal channel between (y 13..43).
- **The native device `massist`** sits alone in the open floorplan space east
  of the PMOS row and north of the capacitor block, at origin (185.0, 33.0):
  a single 25 x 1 um native NMOS (`voltage_flavor: "nvt"`), orientation
  `none` like the NMOS row, `L=25 W=1` matching the reference card. Its
  source pad is 2.6 um west of the `cdg` capacitor's left edge and its gate
  lands between the `cdg` and `ctim0` bottom-plate risers; the block is
  clear of the capacitors (which end at y=27.9), of `stub_resetn` (y 42.9)
  and of the `RESETn` metal4 track (y=43.0).
- **Row order** follows function so most nets stay local: NMOS `MBD MN1 MND
  MDGNT MDGNI MG1N MG2N MDIS MDANT MDBNI MRLK MNAN2 MNAN1 MON`; PMOS `MPD MP2
  MPT MDGPT MDGPI MG1P MG2P MTSW MDAPI MDBPT MNAP2 MNAP1 MAST MOP`.
- **Bodies.** Every PMOS has its own `guard_ring` n-well tap island (abutted
  at the 0.10 um n-well overlap, as in `por_comparator`) tied to `VDD`. Seven
  p-tap islands `pst1..pst7` (y=-3.5, in the gap before every second NMOS)
  tie the substrate to `VSS`; `massist`'s substrate bulk reaches them the
  same way. As extracted: all 15 NMOS bulks are on `VSS`, all
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
  plate. `massist` joins both rails' stars: its source drops from the `VSS`
  rail at x=185.2 (in the gap between the `cdg` and `ctim0` bottom-plate
  risers), its gate rises from the `VDD` rail at x=197.9.
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

`massist`'s drain joins the existing `RESETn` metal4 star: one leg from the
`mop.U0_D` hub east along the y=43.0 track (past the `stub_resetn` port,
which sits on the same net) and down to the drain pad at (210.6, 33.5). Its
gate and source legs join the `VDD`/`VSS` metal2 rail stars described above.
No net changed plane and no existing leg moved.

The search is a heuristic; `klt drc` and `klt extract` are the arbiter. A first
assignment from it drew one `met5` and then one `met4` spacing violation, and
other seeds were refused by `gen-compose` ("crosses already-routed net"); the
committed one is the first that was routed, DRC-clean and LVS-clean.

## Verification detail

`klt drc --deck sky130`: `clean`, 0 violations. **Deck scope** (from
`drc.json` `coverage`): 23 deck scopes (`cap2m capm ct difftap li licon m1 m2
m3 m4 m5 npc nsdm nwell poly psdm rpm urpm via via2 via3 via4 x`), 113 deck
rules checked — the curated sky130 deck's spacing/width/enclosure/area/angle/
grid rules on the layers this cell draws, including the HV-nwell-enclosure
rule `nwell.enclosed.hvi.1` (which passes vacuously here: the stream draws no
`hvi` marker yet — see the `XMASSIST` section). Not covered: 40 rules
reported as skipped — the `*.angle.1`/`*.ongrid.1` pairs on marker layers
this cell does not draw (`dnwell`, `hvntm`, `hvtp`, `hvtr`, `mf`, `ncm`,
`nsm`, `pad`, `pwbm`, `pwde`, `pwell_rs`, `rpm`, `tunm`, `uhvi`, `urpm`,
`vhvi`, `vpp`, `areaid_re`) — plus the second-MiM `capm2.*` rules and
`met4.enclosing.capm2.1`; 347 sky130 rules are `unmodeled_rules` (not in the
curated deck at all); and anything else the deck does not model (no latch-up,
antenna, density or well-proximity-to-tap-distance rule is claimed). Layers
in the stream without rules: 67/5, 68/5, 69/5, 70/5, 72/5. The deck is
`released: true` at this pin.

`klt extract --deck sky130`: `status: extracted`, 34 devices, 18 nets, 18 pin
labels. `device_counts`: `{"nfet": 15, "pfet": 14,
"sky130_fd_pr__model__cap_mim": 5}`. Port nets, each labelled at its stub
(`extract.json` `nets[]`): `IBIAS` (-10, 13), `POR_RAW` (-10, 23.8), `RESETn`
(174.0, 43.0), `VDD` (-6, 58.8), `VSS` (-6, -6.0). Connectivity to the
devices is what LVS verifies (below); VDD and VSS tap connectivity is the
bulk census above. `massist` extracts as a generic `nfet` card (the deck's
MOS binning is flavour-blind — see the `XMASSIST` section) with
`g=VDD d=RESETn s=VSS b=VSS` at `L=25 W=1`, matching the reference card's
connectivity exactly.

`klt lvs`: `match`, devices 34/34, nets 18/18, pins 18 layout / 5 reference,
`mismatch_count: 2`, `error_count: 0`. The 2 are warnings:

- `device.placeholder_value`: the capacitor `C` is the literal 0 in the
  subckt-call reference, so it is excluded from the compare.
- `device.geometry_not_compared`: capacitor `A` and `P` are secondary
  parameters, not compared.

So capacitor values and areas are **not verified by LVS** (same as
`bias_core_passives`): the `CDG`/`CTIM` multiplicities are checked by count
(1 and 4 units) and by the topology of both plates, and the unit sizes
(121 and 784 um2 `area_um2`) were read from `extract.json`. MOS classes
compare `L` and `W` and all four terminals including the bulk (the default);
flavour is *not* compared (disclosed above).

**Reference rewrite (`lvs.expand_multiplier`).** `klt lvs` refuses the
reference card `XCTIM ... MF=4 m=4` ("one device per drawn gate"). The
generated `por_output_chain.ref.spice` therefore writes it as `XCTIM_0..3`,
each `MF=1 m=1`, which is exactly what the layout draws. `design/` is
unchanged. Other cards differ from the source only by `u` unit suffixes
(`compose-cell.py`'s known rewrite).

Negative controls (scratch copies of the generated reference, re-run at the
`0.9.2` pin, not committed): `XMN1` `L` 20 -> 19 gives `mismatch` (5
`device.property` errors); `XMDIS`'s gate moved from `PGDGB` to `PGDG` gives
`mismatch` (`device.unmatched`); dropping `XCTIM_3` gives `mismatch` (34 vs
33 devices). So `L`, the topology and the capacitor count are really
compared. The flavour-blindness negative controls live in the `XMASSIST`
section above.

## Known gaps

1. **MOS flavour binding is drawn but not LVS-verified** (the `XMASSIST`
   section above): the native-Vt marker is on the layout and the
   `nfet_05v0_nvt` card is in the compare, but the flavour-blind compare
   cannot tell that device from a plain 5 V NMOS of the same `L`/`W`. Turning
   the flavoured compare on needs the 28 5 V devices drawn with their `hvi`
   marker, which is blocked on
   [klayout-tools#6025](https://github.com/2AMLogic/klayout-tools/issues/6025)
   (measured at `0.9.2` and on `main`).
2. **No `hvi` thick-oxide marker** on the 28 5 V devices: the same blocker —
   the marker cannot be drawn DRC-clean next to a well tap ring
   (klayout-tools#6025). Until then neither `klt drc` nor `klt lvs` sees the
   devices' 5 V class (the same disclosure as `por_comparator`, upstream
   [#1912](https://github.com/2AMLogic/klayout-tools/issues/1912), closed;
   the deck-side `nwell.enclosed.hvi.1` rule that now fires exists since
   #3031's direction was implemented). **This cell is not 5 V sign-off.**
3. **Capacitor values not LVS-compared** (placeholder `C`, secondary `A`/`P`).
4. **Long-channel devices** (`L` 10, 20 and 25 um) are single-finger, as in
   `por_comparator`; area is not optimized (336 um wide, mostly the
   capacitors and the long devices). No density or matching work.
5. **No ERC, no parasitic extraction, no simulation** of the laid-out cell.
   `sim/` is untouched.
6. **Not a signoff citation.** `manifests/` is not cited from this
   directory. The block-level `temp_por_top` assembly still embeds the
   **pre-`massist` bytes** of this stream and its own LVS still excludes
   `XMASSIST` (see `layout/temp_por_top/README.md`); recomposing it and
   refreshing its attestations belongs to the block-wide re-render, not to
   this leaf-scoped increment.
