# spec

- [`porting-plan.md`](porting-plan.md) — what carries over from
  [`gf180-temp-por`](https://github.com/2AMLogic/gf180-temp-por)'s
  architecture and spec structure, what must be re-derived against sky130
  device models, and the PVT/ramp-rate testbench matrix the POR and sensor
  testbenches must cover before design starts. The first deliverable this
  repo produces — see the repo README and `CLAUDE.md`.
- [`decision-records/`](decision-records/) — one file per decision, using
  the format in `decision-records/TEMPLATE.md`. `DR-001` and `DR-002` are
  the two new decisions the porting plan above required (supply flavor,
  architecture carryover).

No `target-spec.md` exists yet — per the porting plan §4, that is a future
deliverable, populated from device-characterization evidence rather than
asserted ahead of it.
