# sky130-temp-por

A temperature sensor + power-on-reset (POR) pair on
[SkyWater sky130](https://github.com/google/skywater-pdk), a 130 nm CMOS
open PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: just opened.** Nothing is designed yet. sky130 is fully supported
by the toolchain, so there is no tooling prerequisite — work starts with the
porting plan (issue #1).

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

## Target specification (DRAFT — engineering to ratify, see issue #1)

| Parameter | Target | Stretch |
|---|---|---|
| Operating temperature | −40…+125 °C | — |
| Temperature error, untrimmed | ±3 °C | ±1.5 °C with 1-point trim |
| Sensor output | analog PTAT + CTAT pads | digital out via SAR pairing |
| POR thresholds VPOR↑ / VPOR↓ | re-derive against sky130 models | — |
| POR hysteresis | ≥ 100 mV | — |
| Supply | confirm against sky130 flavors (1.8 V core vs 3.3/5 V devices) | — |
| Iq (block total) | < 20 µA | < 5 µA |
| Supply-ramp coverage | ramp-rate sweep in the POR testbench matrix | — |

Port parity note: the targets deliberately mirror `gf180-temp-por`'s ratified
spec where a target is device-independent. Where sky130's devices make a
target inappropriate rather than merely harder — the threshold rows above
being the expected cases — change it and record why in a decision record.

Maturity ladder: spec ratified → schematic simulated across PVT →
layout DRC/LVS-clean → post-layout re-verification → shuttle seat →
measured silicon. **Current position: pre-spec.**

## Repo layout

```
spec/          ratified spec + decision records
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
