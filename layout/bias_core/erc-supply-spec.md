# `erc-supply-spec.json` — rationale

`erc-supply-spec.json` is the `klt erc` supply spec for the `bias_core`
full-cell assembly. It is this repo's T1 item 11 (power delivery,
structural) supply-spec read (issue #66), graded via `manifests/` (see
`manifests/README.md`, item 11). `layout/bin/pad-island-census.py` builds
its connectivity graph from the same `stackup`/`vias`/`devices`.

This rationale used to sit inline as a `_comment` key. Since issue #81's pin
bump (`klt 0.6.0+g0ce8c64842d9`), `klt erc` rejects unknown spec keys
(`unknown field '_comment' ... allowed here: devices, nets, stackup, ties,
ties_disclosure, vias`; tracked upstream as klayout-tools#2822), so the
rationale moved here.

## Reproduce

From the repo root (paths are echoed verbatim into the report's `file` /
`spec` fields and resolved repo-root-relative by `klt signoff`):

    klt erc layout/bias_core/bias_core.gds \
         layout/bias_core/erc-supply-spec.json \
         --format json > layout/bias_core/erc.json

The run deliberately omits `--pdk`, following the fleet's item-11 worked
example. Antenna-ratio grading is not item 11's subject (klayout-tools
`docs/cli/erc.md` → "Item 11 does not grade the ERC envelope's own status";
klayout-tools#1994). With no `--pdk`, the command **always exits 4** and
the top-level `status` is `not_checked`. The structural read that the item
grades is `erc_status` (klayout-tools#2179). Read `erc_status`, not the
exit code.

## Stackup and vias

- `stackup[0]` must carry `role: "gate"` (klt erc's contract), so the stack
  starts at poly. `active_layer: "65/20"` (diff) makes the antenna
  denominator `poly ∩ diff` instead of raw poly, which keeps poly with no
  gate oxide out of `gates[]` (klayout-tools#1979).
- Conductors are li1/met1/met2/met3/met4/met5 (67/20 … 72/20). **met5
  (72/20) and via4 (71/44) were added in #81**: the `pb` route now runs
  on met5 (`metal6` role, klayout-tools#2738), and leaving them out would
  split `pb`'s island at its via4 ladders.
- Layer numbers are checked against both the sky130A `.lyp`
  (poly.drawing 66/20, diff 65/20, li1 67/20, met1..met5 68/20..72/20,
  licon1 66/44, mcon 67/44, via 68/44, via2 69/44, via3 70/44, via4 71/44)
  and klayout-tools' curated sky130 deck. Neither source is another PDK's
  spec.
- `label_layer` is declared only on the layers that carry **supply** text:
  li1 67/5 (`VDD`/`VSS`/`vdd`/`vss`), met1 68/5 (`VSS`/`vdd`/`vss`) and met3
  70/5 (`vdd` at the passives met3 landing). met2 69/5, met4 71/5 and met5
  72/5 carry signal-pin text only, so they are not declared.

## Device-body cuts (`devices[]`, added in #81)

A conductor role holds geometry, and nothing in the stackup alone separates
a wire from a device body drawn on the same layer. Before #81 this did not
matter, because no supply-adjacent net reached those bodies. With every
cross-block net wired, the uncut graph merged distinct LVS nets:
`VDD,nokx` and `pg,nz` across the two MiM caps, and `VREF,er`,
`ec,nb,nbtop` and `n2,nz` across the poly resistors. These were graph
artifacts, not shorts; LVS keeps all 27 nets separate. The spec now cuts
those bodies out, the way klayout-tools#2183's `devices[]` is meant to be
used:

- `res_poly_body`: `66/13` (`poly.res`, sky130's poly-resistor ID mark,
  the `poly_res` layer in sky130.lvs) is cut from `poly`. The 4
  `res_xhigh_po` bodies then separate their two terminals.
- `mim_m3_top_plate_contact`: `89/44` (capm, the `cap_mim_m3_1` top plate)
  is cut from `via3`. The via3 that contacts the top plate lands on capm,
  not on the met3 bottom plate. Without the cut, the graph (which has no
  capm conductor) connects it to the bottom plate it overlaps.

`provenance.devices[].body_area_um2` in `erc.json` shows each cut removed
real geometry (non-zero).

## Nets

`VDD` and `VSS`, both `kind: "supply"`, are named exactly as the
`.subckt bias_core VDD VSS IBIAS VREF BIAS_OK` interface spells them.
Matching is case-sensitive and per label text, so they match the two
stub-promoted top-level pins (`VDD` at (-100, 10) µm and `VSS` at
(-104, 14) µm on 67/5). The lowercase `vdd`/`vss` texts are sub-block-local
pin labels and are deliberately left undeclared. The census shows them on
the same islands (`VDD,vdd` / `VSS,vss`). `erc.unconnected_net` fires on
zero matching islands **and** on more than one, so zero findings of that
rule is exactly the "one island per supply" verdict. A short between the
two would report as `erc.supply_short`.

## `ties[]` and `ties_disclosure` (added in #90)

Declared: one nwell -> `VDD` tie.

    "ties": [{ "name": "nwell_vdd", "well_layer": "64/20",
               "well_excludes": ["82/44"], "tap_layer": "65/44",
               "tap_is_dedicated": true, "connect_to": "li1", "net": "VDD" }]

- `well_layer` 64/20 is sky130 `nwell.drawing`; `tap_layer` 65/44 is
  sky130's own dedicated `tap` marker, hence `tap_is_dedicated` (no
  `tap_requires`: this stream draws no `nsdm` 93/44, and a probe with
  `tap_requires: ["93/44"]` gave 19 findings for that reason alone).
- `well_excludes: ["82/44"]` (klayout-tools#2339, well-side class
  selector) drops the wells that interact with the PNP marker. The
  marker distinguishes them, so `well_excludes_boxes` (literal geometry,
  #2540) is not used.
- Measured at `klt 0.6.0+g0ce8c64842d9` against the committed GDS
  (sha256 `9c414f91...7ab68e`). Blanket probe, no exclusion: 2
  `erc.missing_tie` findings, "tap is not connected to declared net
  'VDD'", on exactly the merged nwell shapes that interact with 82/44:
  `bias_core_xq1_xqr` (149.85, 99.85)-(158.99, 103.55) um and
  `bias_core_pnp8_leg` (199.85, 99.85)-(218.23, 107.35) um (18 merged
  nwell shapes in total, 2 with the marker). Their wells tie to their own
  nodes (PNP bases) by design. With the exclusion: 0 findings; the
  selection keeps 16 of 18 shapes, so it is neither degenerate nor
  hides ordinary wells. Removing `well_excludes` reproduces the 2
  findings.
- The excluded PNP tubs are not tie-graded by this run.

Disclosed, not declared: `ties_disclosure.kind: "unexpressible"`,
`undeclared_classes: ["p_substrate"]` (klayout-tools#2541). sky130's
p-type substrate is native with no drawn well layer, so a VSS substrate
tie cannot be declared (klayout-tools#2186's documented limitation). The
report records `erc.missing_tie:["p_substrate"]` under
`erc_coverage.inapplicable` (`ties_disclosed_unexpressible`). That is the
caller's word, not a check: the substrate tie was **not** verified.

`erc_status` stays `clean` (VDD/VSS still one island each; no
`erc.unconnected_net` or `erc.supply_short`). `klt signoff` now grades
item 11 `met`, with the p_substrate class carried in the citation's
`power_delivery.disclosed_undeclared_tie_classes`.

## Provenance

The committed `erc.json` was generated with `klt 0.6.0+g0ce8c64842d9`
(klayout-tools `main` @ `0ce8c64842d9cbcd7689d40ebfa3774355c1da4c`,
clean build), the commit pinned in `layout/pdk.json` and installed by
`.github/workflows/signoff-manifest.yml`, against `layout/pdk.json`'s
pinned sky130A install.
