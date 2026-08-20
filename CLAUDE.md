# sky130-temp-por — agent instructions

Open-source canary block: a temperature sensor + power-on-reset (POR) pair on
SkyWater sky130, a 130 nm CMOS open PDK, designed and verified by AI agents.

- **PDK**: SkyWater sky130 (open PDK, google/skywater-pdk, distributed via
  open_pdks). Open-source flow: xschem + ngspice for design/sim,
  klayout-tools (`klt`) for layout work. sky130 is fully supported by the
  toolchain — there is no tooling prerequisite; design work can start.
- **The PDK is the variable, not the design.** This block is a port of the
  fleet's proven
  [gf180-temp-por](https://github.com/2AMLogic/gf180-temp-por) *on purpose*.
  Anything that breaks should be assumed to be the PDK, the deck, or the
  tools before it is assumed to be the circuit. Start from that repo's
  `spec/`, schematics, and decision records rather than from a blank page.
- **Thresholds do not port.** POR trip points and brown-out behavior depend
  on sky130's device thresholds and their corners, which differ from
  gf180mcu's. VPOR↑/VPOR↓ and the hysteresis window must be re-derived
  against sky130 models — never carried numerically from the gf180 spec —
  and supply-ramp-rate coverage belongs in the testbench matrix from the
  start, because the block's whole job is correct behavior across
  temperature and supply ramp.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and describe
  the gap, not the design.
- **Verification is the product**: no claim without a testbench. PVT corners
  on every recorded result — especially apt here, since the deliverable is
  behavior across temperature and supply ramp; `sim/` results are append-only
  evidence.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
