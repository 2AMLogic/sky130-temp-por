# temp_por_top — block-level assembly (issue #240, T1 item 2)

`cell.json` places the four committed leaf streams (`bias_core`,
`por_comparator`, `por_output_chain`, `temp_core`) as `blocks[].cell` siblings,
stacked in y, and wires the nets `design/temp_por_top.sch` connects between
them in a left-hand channel, one metal plane per crossing net:

| Net | Plane (klt role) | Note |
| --- | --- | --- |
| VDD / VSS | met3 / met4 (`metal4`/`metal5`) | trunks at x=-150 / -200 |
| IBIAS | met5 (`metal6`) | only plane that clears `bias_core`'s own IBIAS pad |
| VREF | met1 (`metal2`) | `bias_core` does not promote VREF; port derived from its met3 label via `ports_from_labels` (leaf untouched) |
| BIAS_OK, POR_RAW | met2 (`metal3`) | |
| RESETn | met1 (`metal2`) | `por_output_chain` -> `temp_core` EN |

VDD, VSS, RESETn, PTAT and CTAT are declared as top-level pins. No padring,
seal ring or other chip-level structure (out of scope).

Reproduce (klt `758c6e2`, the CI pin; `layout/pdk.json`'s older
`klt_commit_pin` is stale):

    python3 layout/bin/compose-cell.py layout/temp_por_top/cell.json --check

The rebuilt GDS is byte-identical to the committed one.

## Results (recorded, not all passing)

- **DRC: 351 violations, all `poly.endcap.diff.1`** — exactly the sum of the
  leaves' counts (bias_core 102, por_comparator 66, temp_core 99,
  por_output_chain 84) when the committed leaf GDS are checked with the pinned
  klt. None come from the top-level routing. The leaf `drc.json` files say
  `clean` because they were produced by klt 0.6.0, before klayout-tools#2936
  added the endcap rule/generator fix. Fixing needs the leaf streams
  regenerated (out of scope here).
- **ERC (`erc.json`, `erc-supply-spec.json` = bias_core's spec): 2
  `erc.missing_tie`**, both `temp_core` nwells with no VDD tap. VDD and VSS
  are each one island at the top. The p-substrate tie class is not checkable
  (see `layout/bias_core/erc-supply-spec.md`).
- **LVS: `match`, 152/152 devices, 71/71 nets — with `XMASSIST` excluded**
  (`lvs.drop_prefixes`), because klt cannot draw or compare the native-Vt
  device ([#97](https://github.com/2AMLogic/sky130-temp-por/issues/97)). So
  this is **not** a full-block match. Also disclosed by klt: `PNP` compared on
  `NE` only; resistor/MiM values not compared (reference `R=0`/`C=0`
  placeholders); `topology.flattened` (reference flattened).
- LVS needs `extract.hierarchical_cells` + `lvs.flatten_layout`: flat
  extraction collapsed leaf-internal nets whose labels recur across leaves
  (`pb`/`PB`, `nz`/`NZ`, ...), giving a false 120/152 mismatch.

Items 3, 4 and 11 of the signoff manifest still cite `bias_core` only, because
the top does not pass them cleanly.
