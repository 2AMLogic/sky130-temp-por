# Work Log Archive — 2026-08

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

### 2026-08-27

- **PR #26**: docs: fix dangling canary-variant.md reference in ee-key MANIFEST
- **PR #24**: ratification: install the two-key reviewer variant (EE key + market key)
- **Issue #25** (closed): ratification/ee-key/MANIFEST.md references nonexistent ratification/canary-variant.md

### 2026-08-26

- **PR #23**: temp_core: re-characterize startup/branch selection with a transient-from-0V testbench
- **PR #21**: bias_core: the spurious high-current DC point is a cold-.op solver artifact, not a second stable state (#19)
- **Issue #22** (closed): temp_core: re-characterize startup/branch selection with a transient-from-0V testbench (same class as #19)
- **Issue #19** (closed): bias_core: spurious high-current DC solution at tt/27C at supply extremes (2.97V, 3.63V)

### 2026-08-25

- **PR #20**: feat: port sim harness (PVT corner grid + mismatch Monte Carlo) from sky130-bandgap
- **Issue #17** (closed): Port sim harness (PVT corner grid + mismatch Monte Carlo) from sky130-bandgap for sky130-temp-por
- **Issue #16** (closed): [Epic #542] 4B — Chipalooza Challenge #4 (Sky130) brief document + sign-off
- **Issue #10** (closed): Assemble temp_por_top: wire bias_core/temp_core/por_comparator/por_output_chain to the ratified pad interface (T1 item 1, sub-issue 5/5)
- **Issue #9** (closed): Port por_output_chain schematic (deglitch/pulse/RESETn drive + startup-assist) from gf180-temp-por (T1 item 1, sub-issue 4/5)
- **Issue #8** (closed): Port por_comparator schematic (POR threshold + hysteresis) from gf180-temp-por (T1 item 1, sub-issue 3/5)
- **Issue #7** (closed): Port temp_core schematic (PTAT/CTAT sensing) from gf180-temp-por (T1 item 1, sub-issue 2/5)
- **Issue #5** (closed): T1 item 1: commit the design sources (first increment toward bronze)

### 2026-08-24

- **Issue #6** (closed): Port design/ netlist export tooling + bias_core schematic from gf180-temp-por (T1 item 1, sub-issue 1/5)

### 2026-08-20

- **Issue #1** (closed): Porting plan: what carries over from gf180-temp-por
