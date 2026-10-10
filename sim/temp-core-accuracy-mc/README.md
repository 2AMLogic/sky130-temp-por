# temp-core-accuracy-mc -- temp_core temperature error under mismatch (issue #105)

Full-signal-path mismatch Monte Carlo of `temp_core` (PTAT/CTAT vs temperature,
-40...125 C, process corners and supply), reported as **temperature error in
degC**, untrimmed and with a 1-point (27 C) gain trim, with a per-term
attribution (PNP pair, amplifier offset, PTAT-gain resistor ratio, branch-current
mirror, everything else) and an all-terms aggregate. It is **evidence only**:
DR-003 row 2 (`[TBD-1]`) is not touched and nothing under `spec/` changes.
`experiment.json` states the claim, the 3-sigma convention, the PVT + MC matrix,
the term list, the operating-point guards and the unmeasured terms.

Read the newest `records/<id>.md` for results. Records are append-only: a re-run
mints a new id and a correction names what it supersedes (`--supersedes`).

## What is (and is not) in the aggregate

Only **local** device mismatch from the PDK model library (`<corner>_mm`
sections, `monte_carlo.vary = mismatch`) is sampled. Global process Monte Carlo,
systematic/gradient mismatch, dynamic (cold-start) behaviour, trim-ladder
resolution and the readout chain are **not** measured; the record repeats this
list under "Not measured". Operating-point trust (the cold-start branch question)
is taken from the #86 solver-sweep record
`sim/temp-core-startup-solver/records/20261010-200708-47b96e5` and inherits its
limits; this campaign adds physical guards on every sample instead of repeating
that sweep.

## Method in four lines

1. One `klt sim` request per **term** (`nominal`, `none`, `pnp`, `amp`, `res`,
   `mirror`, `other`, `all`), 5 `_mm` process sections x 3 supplies x N samples,
   submitted to the Spot batch fleet. The runner never launches ngspice over a
   grid and never falls back to a local grid.
2. Exactly one device group has mismatch live in a term run; the others are
   instantiated through `mmoff_*` wrapper subckts that zero the model library's
   mismatch-sigma `.param`s in the wrapper scope. Controls: `none` (everything
   wrapped) must equal `nominal` exactly; every term row must be nonzero.
3. Temperature is swept **inside** each ngspice process (`dc temp -40 125 1`):
   klt derives the per-sample seed from the corner index, so a klt temperature
   axis would give a different device realisation at each temperature.
4. Error in degC = (PTAT_sample - PTAT_nominal) / S, with S the same-corner
   nominal full-range slope; 3 sigma = 3 x sample standard deviation per corner.
   Samples failing a physical operating-point guard at any of -40/27/125 C are
   excluded, counted and disclosed.

## Cold start (from a clean checkout)

Prerequisites are machine-level: `ngspice`, the pinned sky130A PDK
(`volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b`),
`python3` (3.9+, standard library only) and `klt` on `PATH`. Monte Carlo goes to
the 2am EDA batch fleet (`KLT_SIM_BACKEND=batch`); on a host with no fleet access
`run` records a refusal and the affected terms are NOT-RUN -- it does not fall back
to a local grid.

```bash
# 0. debug only: a SINGLE-corner LOCAL probe (a few samples; not evidence)
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py probe --run-id dbg --term nominal --term all --n 3

# 1. commit first: the runner refuses to start from a dirty tree (provenance-clean records)
# 2. submit every term to the fleet (default N = 200 per corner, seed 20261010)
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py run
#    resume after an interrupted/refused submit (terms with a usable report.json are skipped):
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py run --run-id <id> --resume

# 3. grade, write sim/temp-core-accuracy-mc/{records,netlist-snapshots,corners}/<new id>
python3 sim/temp-core-accuracy-mc/run_accuracy_mc.py record --run-id <id>
```

Raw fleet outputs land in the git-ignored `sim/build/temp-core-accuracy-mc/<run id>/`;
`record` copies what is evidence (scrubbed netlists and requests, per-sample CSVs,
nominal point logs) into the tracked tree. `record` refuses to overwrite an existing
record id and refuses a run made from a dirty tree.

## Layout

| Path | Content |
|---|---|
| `experiment.json` | claim, 3-sigma convention, PVT + MC settings, terms, guards, unmeasured terms |
| `run_accuracy_mc.py` | runner (`run`, `probe`, `record`); builds the per-term deck and request |
| `records/<id>.{md,json}` | the evidence record and its machine-readable twin |
| `netlist-snapshots/<id>/` | generated deck and request for every term |
| `corners/<id>/` | `samples-<term>.csv` (every sample, valid flag and guard reason) and `nominal_*.log` |
