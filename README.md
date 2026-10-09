# sky130-temp-por

A temperature sensor + power-on-reset (POR) pair on
[SkyWater sky130](https://github.com/google/skywater-pdk), a 130 nm CMOS
open PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

![fleet burndown](https://raw.githubusercontent.com/2AMLogic/2am/main/fleet-metrics/charts/sky130-temp-por.svg)

**Status: schematic complete and netlisted; verification and layout
in progress.** `design/` has a full, netlist-checked schematic hierarchy
(four leaf cells plus the assembled `temp_por_top`); `sim/` has testbench
harnesses with recorded PVT-corner results; `layout/` has all six
`bias_core` sub-blocks fully assembled and routed, with clean DRC and a
50-device/27-net LVS match. Structural power-delivery signoff remains open
because the ERC supply specification does not yet declare well/substrate ties.
`spec/` is partially ratified: DR-003 finalized the operating-temperature
and supply rows through the two-key process, while the remaining target rows
are still explicit placeholders (`spec/README.md`,
`spec/decision-records/`, `ratification/`). See "Target specification"
below for the maturity-ladder detail. sky130 is fully supported by the
toolchain, so there is no tooling prerequisite.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result under PVT corners. Where the agents hit friction with the
open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction is
filed as a public issue against the tool itself, so the fix benefits everyone
using sky130, not just this repo.

## Why this block, on this PDK

This is a port of
[gf180-temp-por](https://github.com/2AMLogic/gf180-temp-por), the fleet's
proven temp/POR block: same block, second PDK. The PDK is the variable, not
the design — the architecture, spec structure, and testbench discipline carry
over from the gf180 repo, so anything that behaves differently here is
attributable to sky130's devices, deck, or models rather than to the circuit.
Work starts from that repo's `spec/`, schematics, and decision records, not
from a blank page.

The one thing that expressly does **not** port is the numbers at the heart of
the block: POR trip points and brown-out behavior depend on device thresholds
and their corners, and sky130's differ from gf180mcu's. VPOR↑/VPOR↓, the
hysteresis window, and the temperature-sensing element's characteristics must
be re-derived against sky130 models, and supply-ramp-rate coverage belongs in
the testbench matrix from the start — a POR that is only ever simulated with
one ramp rate has not been verified at all.

## Target specification (partially ratified — DR-003, issue #78; remaining rows TBD)

Ratified by [DR-003](spec/decision-records/DR-003-ratify-target-spec-recommendation.md)
through the two-key path, per the operator ruling of 2026-10-02 on issue #31:
**only** the operating-temperature and supply rows are final. Every other row
is an explicit placeholder (`[TBD-n]`, numbering per DR-003) until measured;
no T1 tier is awarded and no draft number below is a ratified target.
The supply value follows [DR-001](spec/decision-records/DR-001-supply-flavor.md),
which is itself still `proposed`; DR-003 is what ratifies the supply row.
DR-001 and DR-002 remain `proposed`.

| Parameter | Target | Stretch | Status |
|---|---|---|---|
| Operating temperature | −40…+125 °C | — | ratified (DR-003) |
| Temperature error, untrimmed | [TBD-1] | [TBD-1] | not ratified |
| Sensor output | [TBD] (draft: analog PTAT + CTAT pads) | [TBD] (draft: digital out via SAR pairing) | not ratified |
| POR thresholds VPOR↑ / VPOR↓ | [TBD-2] (re-derive against sky130 models) | — | not ratified |
| POR hysteresis | [TBD-3] | — | not ratified |
| Supply | 2.97–3.63 V (3.3 V ±10 %) | — | ratified (DR-003) |
| Iq (block total) | [TBD-4] por-iq / [TBD-5] temp-iq / [TBD-6] iq-total | [TBD-4..6] | not ratified |
| Supply-ramp coverage | [TBD] (draft: ramp-rate sweep in the POR testbench matrix) | — | not ratified |

Port parity note: the targets deliberately mirror `gf180-temp-por`'s ratified
spec where a target is device-independent. Where sky130's devices make a
target inappropriate rather than merely harder — the threshold rows above
being the expected cases — change it and record why in a decision record.

Maturity ladder: spec ratified → schematic simulated across PVT →
layout DRC/LVS-clean → post-layout re-verification → shuttle seat →
measured silicon. **Current position: schematic complete and netlisted,
with per-cell PVT sim results recorded in `sim/`; spec ratification and
layout are both advancing in parallel rather than in strict ladder order —
DR-003 has ratified the operating-temperature and supply rows while the
remaining target rows stay open, and `layout/` has a fully
routed `bias_core` assembly with clean DRC and a 50-device/27-net LVS match.
The remaining layout-side T1 gap is structural power-delivery evidence for
well/substrate ties, and the other top-level cells are not yet laid out, so no
single ladder rung is complete yet.**

## Repo layout

```
spec/          decision records + ratification process (target spec partially ratified: rows 1 and 6 under DR-003)
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## CI

`signoff-manifest.yml` gates signoff-report freshness; `self-checks.yml` runs fast stdlib-only self-checks (census unit test, ramp-checker selftest, committed-netlist invariants, sim JSON well-formedness). No SPICE, layout composition, or xschem netlist-vs-schematic check runs in CI -- see [manifests/README.md](manifests/README.md#what-ci-covers-and-does-not).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
