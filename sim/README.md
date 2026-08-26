# sim/ — the simulation harness and its evidence records

This directory holds the reproducible xschem + ngspice + sky130 harness and the
results it produces. Two rules from the root `CLAUDE.md` shape everything here:

- **Verification is the product.** No claim without a testbench. Every recorded
  result carries the PVT corner matrix (−40/27/125 °C, ±10 % supply, process
  corners) unless the record states why a subset was used — the runner
  *enforces* that by refusing to write a subset record without a
  `--subset-reason`.
- **`sim/` is append-only evidence.** Records are never edited or deleted. A
  re-run — even one that corrects a mistake — mints a new record id; a
  correction points at what it replaces via a `Supersedes` field. The runner
  refuses to start if the record id it would mint already exists on disk.

The harness itself (`sim/bin/`, `sim/pdk.json`, `sim/spiceinit`, `sim/xschemrc`)
is ported from [`sky130-bandgap`](https://github.com/2AMLogic/sky130-bandgap)'s
own `sim/` (issue #17), whose directory layout, record-id scheme, and
summary-record fields it reuses unchanged, so the two repos' evidence trails
read as one house convention. Anything specific to *this* repo's own design
(the experiments under `sim/*/` themselves) is new, not ported.

---

## Quick start (cold machine)

```bash
# 1. install the pinned PDK (~1 min; see sim/pdk.json for the pin)
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. sanity-check the toolchain and PDK resolution
python3 sim/bin/corner-run.py --print-env

# 3. run the harness smoke test over the full PVT matrix (45 points, ~2 min)
python3 sim/bin/corner-run.py sim/bias-core-smoke

# 4. run the PNP mismatch Monte Carlo (local + global-process, ~2 min)
python3 sim/pnp-mismatch/run_pnp_mismatch.py
```

Prerequisites, all machine-level (not vendored here): `ngspice`, `xschem`,
`volare`, `python3` (3.9+, standard library only).

### Driving the tools by hand

```bash
source sim/bin/pdk-env.sh      # exports PDK_ROOT, PDK, SKY130_MODEL_LIB, XSCHEM_RCFILE
xschem --rcfile "$XSCHEM_RCFILE" sim/bias-core-smoke/testbench/tb_bias_core_smoke.sch
cp sim/spiceinit ./.spiceinit  # ngspice needs these settings to read PDK libs
```

`sim/bin/pdk-env.sh` is a thin wrapper around `corner-run.py --print-env`, so
interactive sessions and the runner resolve the PDK identically.

---

## How the harness is wired

| Piece | File | Role |
|---|---|---|
| PDK pin | `sim/pdk.json` | open_pdks commit, variant, model-library path, the process-corner names that actually exist in the PDK library |
| ngspice settings | `sim/spiceinit` | `ngbehavior=hsa` etc. required to read the sky130 libs; copied into the scratch run dir as `.spiceinit` |
| xschem config | `sim/xschemrc` | project-local rc that sources the PDK's own xschemrc (so `sky130_fd_pr/*.sym` resolves) plus `design/*.sym`, and keeps generated netlists out of the tracked tree |
| corner runner | `sim/bin/corner-run.py` | netlist → deck → ngspice → parse → record |
| shared helpers | `sim/bin/sim_common.py` | generic helpers bespoke Monte Carlo scripts reuse (PDK resolution glue, log rendering, mismatch-point sweep builders) |
| env helper | `sim/bin/pdk-env.sh` | `source` it for interactive xschem/ngspice work |
| experiment | `sim/<slug>/experiment.json` | what is being claimed, which corners, which measurements and their limits |

**PDK resolution order**: `$PDK_ROOT` → `volare path` → `default_pdk_root` from
`sim/pdk.json`; variant from `$PDK` → `variant` in `sim/pdk.json`. The runner
resolves the PDK directory symlink back to its volare version hash and
**refuses to run against a version other than the pin** unless
`--allow-pdk-mismatch` is passed — in which case the record says so.

**What the runner injects** (so one testbench serves the whole matrix): the
`.lib <models> <corner>` include, `.temp`, `.param vsup=<supply>`, `.option`s
from the manifest, and the `.control` block that runs the analyses, evaluates
each measurement expression into a `meas_<name>` vector and prints it. The
testbench schematic therefore contains no corner, no temperature, no numeric
supply and no analysis block.

**Per-corner artifacts**: each corner's `.log` embeds the exact deck that was
fed to ngspice (prefixed with `|`) plus raw stdout/stderr, so a record is
auditable without regenerating anything. Scratch decks and xschem output live
in the gitignored `sim/build/`; only the netlist snapshot, the per-corner logs
and the record are committed.

---

## Directory / naming convention

```
sim/
  README.md                          # this file
  pdk.json                           # PDK version pin
  spiceinit                          # ngspice init settings
  xschemrc                           # project-local xschem config
  bin/
    corner-run.py                    # PVT corner runner
    sim_common.py                    # shared helpers for bespoke run_*.py scripts
    pdk-env.sh                       # `source` for interactive use
  build/                             # gitignored scratch (decks, xschem netlists)
  <experiment-slug>/                 # e.g. bias-core-smoke, pnp-mismatch
    experiment.json                  # manifest: claim, corners, measurements, limits
                                      # (corner-runner experiments only -- bespoke
                                      # Monte Carlo scripts skip this, see below)
    testbench/                       # xschem schematic(s) / bespoke .spice deck(s)
    netlist-snapshots/
      <record-id>.spice              # frozen netlist used for this record
    corners/
      <record-id>/
        <corner-id>.log              # deck + raw ngspice output per point
    records/
      <record-id>.md                 # append-only summary record (human)
      <record-id>.json               # same record, machine-readable
```

- **`<experiment-slug>`** — kebab-case name for the claim under test. One
  directory per distinct claim, not per run.
- **`<record-id>`** — `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` in UTC. The same id
  ties together the netlist snapshot, the per-corner logs and both record
  files for one run. Re-runs mint a new id.
- **`<corner-id>`** — `<process>_<temp>c_<supply>v` for PVT-matrix experiments
  (e.g. `ss_-40c_2.97v`), or a Monte-Carlo-specific id (e.g.
  `tt_mm_27c_nosupply`) for bespoke scripts.
- **`testbench/`** is not versioned per record. If a testbench change could
  affect comparability across records, say so in the new record (the frozen
  netlist snapshot is what actually pins what ran).

## Summary record fields

Each run writes `records/<record-id>.md` (and a `.json` twin with every parsed
number, limit and verdict, for tooling):

| Field | Meaning |
|---|---|
| Record ID | matches the filename, the snapshot and the `corners/` subdirectory |
| Experiment | slug + title from the manifest |
| Claim | which spec parameter/line this substantiates — `spec/target-spec.md` does not exist yet in this repo (`spec/porting-plan.md` §4 item 4), so every current record is harness bring-up / pre-spec evidence, stated as such in its own claim text |
| Netlist provenance | `schematic` (`design/…`, `sim/…/testbench/…`) — `extracted` (post-layout) is not used yet, no layout exists in this repo |
| PDK | variant + open_pdks commit actually used, whether it matches `sim/pdk.json`, and the model library path |
| Tools | ngspice / xschem / OS / python versions used |
| Repo state | short sha, branch, and whether the working tree was dirty at run time |
| Corner matrix run | the (process, temperature, supply) points actually executed; must be the full PVT matrix unless a subset reason is recorded |
| Statistical convention | N samples and sigma level for distribution claims (e.g. Monte Carlo mismatch); `N/A` for corner-matrix claims |
| Result | per-corner pass/fail with measured values, plus an overall verdict |
| Links | testbench, manifest, netlist snapshot, raw logs, json record |
| Timestamp / author | UTC timestamp and who (human or agent) ran it |
| Supersedes | prior `<record-id>` this corrects or re-runs; `(none)` otherwise |

### Append-only rule

`records/*` files are never edited or deleted after creation — this applies
even to typo fixes, because the append-only guarantee is the whole point of an
evidence trail. Corrections mint a new record that references the prior one via
**Supersedes**. A record whose overall verdict is FAIL is still valid,
committed evidence (see `sim/bias-core-smoke/`'s own first record) — it is not
edited, loosened, or deleted just because the result was unwelcome; a genuine
circuit finding gets a follow-up issue instead (see that experiment's own
`experiment.json` `notes` field).

---

## Current experiments

| Experiment | Kind | What it proves |
|---|---|---|
| `sim/bias-core-smoke/` | `sim/bin/corner-run.py` + `experiment.json` | Harness bring-up for issue #17: the ported runner drives THIS repo's own `design/bias_core.sch` through xschem/ngspice across the full 45-point PVT matrix (5 process × 3 temp × 3 supply). Not a spec claim (no `spec/target-spec.md` yet). |
| `sim/bias-core-startup/` | `sim/bin/corner-run.py` + `experiment.json` | Issue #19: `bias_core` reaches its intended branch (`VREF` ≈ 1.25 V, ~1 µA quiescent, `BIAS_OK` asserted) from a **physical 0 V cold start** — a `tran … uic` supply ramp instead of a cold `.op` — at every point of the full 45-point PVT matrix. This is the branch-selection claim `bias-core-smoke`'s `.op` cannot make (see below). Not a spec claim. |
| `sim/bias-core-op-branch/` | bespoke `run_op_branch.py` | Issue #19: diagnoses the two `.op` FAILs in `bias-core-smoke`'s first record. Sweeps the supply in 10 mV steps at `tt`/27 °C under four *numerical* variants of the same circuit (KLU vs. sparse solver, gmin vs. source stepping, `.nodeset` seed) and checks each off-branch point for **physicality** (supply-current sign, internal-node magnitude). Verdict: solver artifact, not a second stable state. |
| `sim/pnp-mismatch/` | bespoke `run_pnp_mismatch.py` | Confirms both `MC_MM_SWITCH=1` (local mismatch) and `MC_PR_SWITCH=1` (global process Monte Carlo) produce non-degenerate samples against this repo's own PNP topology — a single `sky130_fd_pr__pnp_05v5_W3p40L3p40` vs. the real 1-vs-8-parallel array `bias_core`/`temp_core` actually use (not sky130-bandgap's small/large device-size pair, which this design does not have). |

Both are the first, concrete increment of `spec/porting-plan.md` §4 item 1
(sim-harness port) — infrastructure and harness-liveness evidence, not the
full PVT + mismatch-MC + ramp-rate + brownout testbench matrix `spec/porting-plan.md`
§3 describes, which is later, multi-issue scope across all four leaf cells and
`temp_por_top`.

### Experiments that do not go through the corner runner

`corner-run.py` runs **one deterministic deck per PVT point**. A claim about a
*distribution* — local mismatch, global process Monte Carlo — needs the same
deck resampled N times at a single process point, which is a different axis.
Those experiments ship a bespoke run script next to their testbench instead of
an `experiment.json` (`sim/pnp-mismatch/run_pnp_mismatch.py` and
`sim/bias-core-op-branch/run_op_branch.py` today — the second one's extra axis
is *numerical settings*, not samples: the same deck re-solved under a different
linear solver / continuation method, which a PVT manifest has no way to
express). Such a script still has to behave like the harness:

- reuse `sim/bin/corner-run.py`'s PDK resolution and **pin enforcement**
  (import it via `sim_common.load_corner_run()`; don't re-implement it), so a
  record is reproducible the same way;
- mint the same `<record-id>`, refuse to overwrite anything under
  `sim/<slug>/`, and write **both** the `.md` and the `.json` twin;
- commit the netlist snapshot and one raw log per ngspice invocation, with the
  exact deck embedded in the log;
- carry a **control point that must fail if the mechanism under test is not
  actually active** (`sim/pnp-mismatch/` re-runs its deck on the plain `tt`
  section with both `MC_MM_SWITCH` and `MC_PR_SWITCH` off, where every sigma
  must come back ~0). A Monte Carlo harness that silently sampled nothing
  would otherwise produce a plausible record.
  `sim/bias-core-op-branch/` carries the same kind of guard for a
  non-statistical mechanism: an `artifact_reproduced[…]` check that re-derives
  the exact off-branch `VREF` values `sim/bias-core-smoke/`'s record reports
  (so a run that stopped exercising the artifact fails loudly instead of
  quietly reporting "all good"), plus a determinism control that re-runs one
  deck unchanged, so a branch difference between two numerical variants cannot
  be dismissed as run-to-run noise.

### Runner options

| Flag | Effect |
|---|---|
| `--print-env` | print PDK env exports and exit |
| `--process tt,ss` / `--temp 27` / `--supply 3.3` | override a matrix axis (marks the run a subset) |
| `--quick` | run the manifest's `quick_subset` only |
| `--subset-reason "…"` | **required** for any subset; recorded verbatim |
| `--supersedes <record-id>` | record which prior record this replaces |
| `--author`, `--timeout` | record author (default `git config user.email`), per-corner ngspice timeout |
| `--allow-pdk-mismatch` | run against a non-pinned PDK; the record flags it |
| `--dry-run` | netlist, print the corner list and one deck, write nothing under `sim/<slug>/` |

Exit status: `0` all checks passed, `2` a record was written but something
failed, `1` harness/setup error (no record written).

---

## Writing a new experiment

1. `mkdir -p sim/<slug>/{testbench,netlist-snapshots,corners,records}`
2. Draw the testbench in xschem (`--rcfile sim/xschemrc`). Leave out the
   corner include, `.temp`, the numeric supply (use `'vsup'`) and any
   `.control` block — the runner owns those. Name the nets you intend to
   measure; connectivity by `lab_pin` label is fine. `design/*.sym` cells
   resolve by their repo-relative name (`sim/xschemrc` puts `design/` on the
   symbol search path).
3. Write `sim/<slug>/experiment.json` (see `sim/bias-core-smoke/experiment.json`
   for a worked example). Process-corner names must appear in `sim/pdk.json`
   `process_corners` (`tt`, `ss`, `ff`, `sf`, `fs`, `ll`, `hh` — the last two
   are the resistor/cap-skew axis, orthogonal to the MOS/BJT corners; `*_mm`
   mismatch and `mc` global-process sections also exist in the library and are
   used by bespoke scripts, not by `corner-run.py`'s own manifest validation).
4. Run it: `python3 sim/bin/corner-run.py sim/<slug>`
5. Commit the produced record, netlist snapshot and per-corner logs. (The
   root `.gitignore` ignores `*.log` globally but un-ignores
   `sim/*/corners/**/*.log`, which is committed evidence.)

## `bias-core-smoke` — the harness's own testbench

`sim/bias-core-smoke/` is not a spec claim. It instantiates
`design/bias_core.sym` on a supply and reads its untrimmed DC operating point
open-circuit. `VREF`, `IBIAS`, `BIAS_OK` and the supply current are all
process/temperature-dependent, so this experiment proves the PDK models load,
xschem netlists this repo's own `design/` sources headlessly, ngspice parses
the deck, and the corner/temperature/supply knobs actually reach the
simulator (asserted by the `vref` spread check, not just eyeballed).

Its own first committed record is `overall: FAIL` — 43/45 corners pass, and the
two that don't (`tt_27c_2.97v`, `tt_27c_3.63v`) report `VREF` railed near `VDD`
and a *negative* milliamp supply current. [Issue
#19](https://github.com/2AMLogic/sky130-temp-por/issues/19) investigated those
two points; `sim/bias-core-op-branch/` is the answer, and it is **not** a second
stable state of `bias_core`: every off-branch `.op` point measured there is
non-physical (the supply *sinking* milliamps from a passive network, internal
nodes hundreds of millions of volts outside the rails), the off-branch supply
points are isolated single-step islands rather than a contiguous region, and
they move — or vanish entirely — when only the linear solver or the
continuation method changes. What the record actually caught is that **a cold
`.op` is not a sound branch-selection method for a self-biased cell**: the deck
has no initial state, so which branch ngspice reports is chosen by its own
convergence-aid continuation. `sim/bias-core-startup/` is the method that *can*
make a branch claim (ramp the supply from 0 V and integrate forward), and it
reaches the intended branch at all 45 PVT points.

The FAILing record is kept as-is, not edited or re-run to force a PASS — `sim/`
is append-only evidence, and a FAIL a full PVT sweep actually found is exactly
the kind of result CLAUDE.md's "verification is the product" instruction exists
to surface. It is still doing its job as the harness bring-up check it was
written to be; it is simply not evidence about `bias_core`'s startup, and the
two later experiments say so with their own testbenches rather than by editing
it.

## Branch selection: how to characterize a self-biased cell here

Every cell in this block with a ΔVBE loop (`bias_core` today, `temp_core` next)
has, by construction, at least two mathematical solutions to its DC network
equations: the intended one and the degenerate zero-current one its on-die kick
circuit exists to break out of. Issue #19 established the house rules for
simulating that class of cell — all four are conclusions from
`sim/bias-core-op-branch/`'s own measurements, not received wisdom:

1. **A cold `.op` cannot make a branch claim.** It has no initial state, so the
   branch it lands on is chosen by ngspice's convergence-aid continuation (gmin
   stepping, source stepping) rather than by the circuit. Change the linear
   solver and the answer can change with it.
2. **Use a supply ramp from 0 V (`tran … uic`) when the claim is about which
   branch the cell reaches.** That is a physical power-up: it starts from the
   all-zero state the silicon starts from and integrates the cell's own
   trajectory forward. `sim/bias-core-startup/` is the worked example.
3. **A `.nodeset` seed is a convenience, not a substitute.** Measured on the
   two flagged corners, seeding recovered one of the two; disabling gmin
   stepping recovered both. If you use a seeded `.op` because it is cheap,
   report the result as "the solver found the seeded branch", not as "the
   circuit selects this branch".
4. **Guard every operating-point measurement with a physicality check.** Two
   cheap ones catch this whole failure class: the supply current must be
   *positive* (a passive network cannot deliver power into its only source),
   and every node must sit inside the rails plus about a volt. A settle flag
   is *not* such a guard — in the artifact points here `BIAS_OK` read
   rail-high, and `IBIAS` sat at compliance, in a "solution" the circuit
   cannot occupy.
5. **A transient is not automatically safe either — tighten `reltol`.** The
   first run of `sim/bias-core-startup/` (record `20260825-235846-f4f73a5`,
   kept and superseded, not deleted) used ngspice's default `reltol=1e-3` and
   came back 43/45: two corners ended their ramp reporting a *negative*
   settled supply current, i.e. the same impossible state, with no warning in
   the log. Re-running those two decks with nothing changed but
   `.option reltol=1e-4` puts both on the intended branch. A ~1 µA cell whose
   ΔVBE nodes can excursion to 10⁸ V is simply not safely converged at the
   default relative tolerance — so that option is part of the experiment's
   deck, and rule 4's guard is what caught the need for it.
