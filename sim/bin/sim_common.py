#!/usr/bin/env python3
"""Shared helpers for the bespoke `sim/*/run_*.py` experiment scripts.

`sim/bin/corner-run.py` drives exactly one deterministic deck per PVT point.
An experiment about a *distribution* (local mismatch, global process Monte
Carlo) needs the same deck resampled N times at a single process point, which
is a different axis -- those experiments ship a bespoke `run_*.py` script
instead of an `experiment.json` (see `sim/pnp-mismatch/run_pnp_mismatch.py`),
but still reuse `corner-run.py`'s PDK resolution, pin enforcement, xschem
netlisting, and tool-version/git-provenance helpers by import.

Ported from sky130-bandgap/sim/bin/sim_common.py (issue #17), **trimmed** to
the generically-reusable subset -- this file is ~700 lines in the precedent
because it accumulated helpers specific to that repo's own bandgap-core
resistor-array/trim topology (`chain_lines()`, `r1_segments_um()`,
`r2_segments_um()`, `substitute_arrays()`, `TARGET_LINES`, `load_base_body()`,
`dc_temp_sweep_control()`, `build_deck()`) across many follow-on
characterization issues that repo has and this repo does not yet have. None
of that is generic PDK/harness machinery -- it is keyed to bandgap-core's own
netlist node names (`VOUT`, `VBQ`, `VB`, `VA`) and its chained-resistor-array
trim ladder, which this repo's `bias_core`/`temp_core`/`por_*` cells do not
have. Porting it here would be dead code, not infrastructure; if a future
characterization issue for this repo needs the same pattern (e.g. this
repo's own resistor legs), port the relevant pieces then, against this
repo's own netlist, rather than carrying gf180/bandgap-shaped code that
nothing here calls.

Kept below (all repo/circuit-generic, actually used by
`sim/pnp-mismatch/run_pnp_mismatch.py` and/or `corner-run.py` itself):

    load_corner_run()    the importlib shim that loads corner-run.py (its
                          filename has a dash, so it can't be `import`ed
                          normally)
    run_ngspice()          runs one ngspice deck in a scratch dir, capturing
                          stdout+stderr and timeout status
    parse_measurements()   extracts `.meas`-style `let`/`print` results from
                          an ngspice log via `corner-run.py`'s `MEAS_RE`
    parse_samples()        parses the repeated `op`+`print` blocks of a
                          Monte Carlo loop's ngspice log into per-sample
                          dicts
    write_log()            writes the append-only per-point `.log` file
                          (header + .spiceinit + deck + ngspice output),
                          `name`-keyed
    render_log()            the shared tail-formatting skeleton underneath
                          every `write_log()`
    render_record_id_experiment() the `Record ID` + `Experiment` lines
                          shared verbatim across every bespoke script's
                          (and `corner-run.py`'s) `render_record()`
    render_pdk_tools_repo_state() the `PDK` (pin-state ternary) + `Tools` +
                          `Repo state` (dirty-tree ternary) lines from the
                          same block
    MismatchPoint          the shared 7-field `(corner_id, section, temp_c,
                          seed, samples, role, purpose)` dataclass shape
    add_common_args()      adds the `--author`/`--supersedes`/`--timeout`/
                          `--allow-pdk-mismatch`/`--dry-run` flags (and
                          `--samples` when requested) a bespoke script's
                          `parse_args()` needs
    build_mismatch_points() the N-point mismatch-sweep-plus-controls list
                          builder `pnp-mismatch/run_pnp_mismatch.py` uses
    mc_control_block()      the Monte Carlo `.control` dowhile-loop skeleton
                          (`setseed`/`set width`/`set height`/`let nruns`/
                          `dowhile run < nruns` ... `print`/`let run = run +
                          1`/`end`/`quit`/`.endc`/`.end`)
    mean()/stdev()/mv()     small numeric/formatting helpers
    seed_stability_checks() the paired same-point/different-seed sigma-drift
                          and worst-sample-changed check pair
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

BIN_DIR = Path(__file__).resolve().parent
SIM_DIR = BIN_DIR.parent
SPICEINIT_FILE = SIM_DIR / "spiceinit"


@dataclass(frozen=True)
class MismatchPoint:
    """One ngspice invocation: a (section, temperature, seed, N) tuple.

    Shared shape a mismatch-Monte-Carlo experiment's `Point` uses --
    `pnp-mismatch/run_pnp_mismatch.py` uses this directly. A future
    experiment sweeping an additional axis (e.g. a `config` selector) can
    subclass this and add just that one field rather than polluting this
    shared shape, mirroring how sky130-bandgap's own
    `monte-carlo-untrimmed/run_mc_untrimmed.py` extends it.
    """

    corner_id: str
    section: str
    temp_c: float
    seed: int
    samples: int
    role: str  # "mismatch" | "control" | "seed-check"
    purpose: str


def add_common_args(
    parser: argparse.ArgumentParser,
    *,
    timeout_default: int,
    samples_default: int | None = None,
) -> None:
    """Add the `--author`/`--supersedes`/`--timeout`/`--allow-pdk-mismatch`/
    `--dry-run` flags a bespoke `run_*.py` script's `parse_args()` needs (and,
    when `samples_default` is given, `--samples`).

    Callers add any script-specific flags to `parser` first, then call this
    to append the shared set -- `--samples` (when requested) is added first
    within this call, matching sky130-bandgap's own convention.
    """
    if samples_default is not None:
        parser.add_argument(
            "--samples", type=int, default=samples_default, help="Monte Carlo samples per point"
        )
    parser.add_argument("--author", default="", help="record author (default: git user.email)")
    parser.add_argument("--supersedes", default="", help="record id this run supersedes")
    parser.add_argument(
        "--timeout", type=int, default=timeout_default, help="per-point ngspice timeout (s)"
    )
    parser.add_argument(
        "--allow-pdk-mismatch",
        action="store_true",
        help="run even if the installed PDK differs from the sim/pdk.json pin",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing under sim/")


def build_mismatch_points(
    samples: int,
    *,
    mm_section: str,
    off_section: str,
    temps_c: list[float],
    seed_a: int,
    seed_b: int,
    n_control: int,
    corner_suffix: str,
    control_extra: str = "",
) -> list[MismatchPoint]:
    """The N-temperature mismatch-distribution sweep plus its two controls,
    ported from sky130-bandgap's shared `build_mismatch_points()` (issue
    #17): a per-temperature local-mismatch sweep on `mm_section`, one control
    point on `off_section` with `MC_MM_SWITCH=0` (samples capped at
    `n_control`), and a seed-B stability check re-using the 27 C mismatch
    point's temperature with `seed_b` in place of `seed_a`.

    `corner_suffix` is the one string that varies between callers with
    different sweep axes (e.g. a supply rail vs. no supply at all) -- it
    lands between the temperature and any point-role suffix in every corner
    id. `control_extra` appends caller-specific detail to the control
    point's `purpose=` text; the seed-check `purpose=` text is not
    parameterized.
    """
    control_n = min(n_control, samples)
    points = [
        MismatchPoint(
            corner_id=f"{mm_section}_{t:g}c_{corner_suffix}",
            section=mm_section,
            temp_c=t,
            seed=seed_a,
            samples=samples,
            role="mismatch",
            purpose="local-mismatch distribution at the nominal process point",
        )
        for t in temps_c
    ]
    points.append(
        MismatchPoint(
            corner_id=f"{off_section}_27c_{corner_suffix}_mm-off",
            section=off_section,
            temp_c=27.0,
            seed=seed_a,
            samples=control_n,
            role="control",
            purpose=(
                "control: identical deck on the plain `tt` section (MC_MM_SWITCH=0); "
                "every sigma must come back exactly 0, which is what proves the spread "
                "above is the mismatch switch and not solver noise" + control_extra
            ),
        )
    )
    points.append(
        MismatchPoint(
            corner_id=f"{mm_section}_27c_{corner_suffix}_seed-b",
            section=mm_section,
            temp_c=27.0,
            seed=seed_b,
            samples=samples,
            role="seed-check",
            purpose=(
                "seed-stability: same point, different setseed -- the samples must "
                "change while sigma must not, i.e. the reported spread is a property of "
                "the model, not of one lucky draw"
            ),
        )
    )
    return points


def mc_control_block(point: MismatchPoint, loop_body: list[str], prints: str) -> str:
    """The Monte Carlo `.control` dowhile-loop skeleton: `setseed`/`set
    width`/`set height`/`let nruns`/`dowhile run < nruns` around a
    caller-supplied `loop_body`, then `print {prints}`/`let run = run +
    1`/`end`/`quit`/`.endc`/`.end`.

    `loop_body` is inserted verbatim between `dowhile run < nruns` and
    `print {prints}` -- it covers everything from the per-experiment `reset`
    line through the per-experiment `let <name> = ...` measurement lines.
    Callers own their own two-space loop-body indentation.
    """
    return "\n".join(
        [
            ".control",
            f"setseed {point.seed}",
            "set width = 512",
            "set height = 100000",
            f"let nruns = {point.samples}",
            "let run = 0",
            "dowhile run < nruns",
            *loop_body,
            f"  print {prints}",
            "  let run = run + 1",
            "end",
            "quit",
            ".endc",
            ".end",
            "",
        ]
    )


def load_corner_run() -> ModuleType:
    """Import sim/bin/corner-run.py (the dash makes it non-importable normally).

    Registers the loaded module in `sys.modules` under its spec name
    ("corner_run") *before* `exec_module` runs -- required because
    `@dataclass`-decorated classes inside corner-run.py resolve type
    annotations through `sys.modules[cls.__module__]`, which fails on an
    unregistered module.
    """
    path = BIN_DIR / "corner-run.py"
    spec = importlib.util.spec_from_file_location("corner_run", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_cr_module: ModuleType | None = None


def _cr() -> ModuleType:
    """Lazily load+cache corner-run.py, for `parse_measurements()`'s `MEAS_RE`.

    Cached at module scope so repeated `parse_measurements()` calls (e.g. once
    per PVT corner in a sweep) don't re-exec corner-run.py's module body each
    time.
    """
    global _cr_module
    if _cr_module is None:
        _cr_module = load_corner_run()
    return _cr_module


def run_ngspice(run_dir: Path, name: str, deck: str, timeout: int) -> tuple[str, int, bool]:
    """Run one ngspice deck in `run_dir`, returning (log, returncode, timed_out)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    deck_path = run_dir / f"{name}.spice"
    deck_path.write_text(deck)
    shutil.copyfile(SPICEINIT_FILE, run_dir / ".spiceinit")
    try:
        proc = subprocess.run(
            ["ngspice", "-b", deck_path.name],
            cwd=run_dir,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        return proc.stdout + proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        return out + err, -1, True


def parse_measurements(log: str) -> dict[str, float]:
    """Extract `meas_<name> = <value>` results from an ngspice log."""
    return _cr().parse_measurements(log)


_PRINT_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)$")


def parse_samples(log: str, vectors) -> list[dict[str, float]]:
    """Parse the repeated `op` + `print` blocks of a Monte Carlo loop.

    A new sample starts whenever a vector name that is already in the current
    sample repeats.
    """
    wanted = set(vectors)
    samples: list[dict[str, float]] = []
    current: dict[str, float] = {}
    for line in log.splitlines():
        m = _PRINT_LINE.match(line.strip())
        if not m or m.group(1) not in wanted:
            continue
        name, value = m.group(1), float(m.group(2))
        if name in current:
            samples.append(current)
            current = {}
        current[name] = value
    if current:
        samples.append(current)
    return [s for s in samples if wanted <= set(s)]


def render_record_id_experiment(record_id: str, slug: str, title: str) -> list[str]:
    """`Record ID` + `Experiment` lines shared verbatim across every
    experiment's `render_record()`.

    Split out from `render_pdk_tools_repo_state()` below rather than combined
    into one "header" helper because every caller's own `Claim` / `Netlist
    provenance` lines render between the two blocks.
    """
    return [
        f"- **Record ID**: {record_id}",
        f"- **Experiment**: `{slug}` — {title}",
    ]


def render_pdk_tools_repo_state(r: dict) -> list[str]:
    """`PDK` (pin-state ternary) + `Tools` + `Repo state` (dirty-tree
    ternary) lines shared verbatim across every experiment's
    `render_record()`."""
    pdk = r["pdk"]
    pin_state = "matches sim/pdk.json pin" if pdk["matches_pin"] else "**MISMATCH vs sim/pdk.json pin**"
    tools = r["tools"]
    return [
        f"- **PDK**: {pdk['variant']} @ open_pdks `{pdk['installed_commit']}` ({pin_state}); "
        f"models `{pdk['lib_file']}`",
        f"- **Tools**: {tools['ngspice']}; {tools['xschem']}; {tools['platform']}",
        f"- **Repo state**: `{r['git']['sha']}` on `{r['git']['branch']}`"
        + (" (working tree dirty at run time)" if r["git"]["dirty"] else " (clean working tree)"),
    ]


def render_log(header_lines, pdk, rc, timed_out, stamp, sections, raw) -> str:
    """Shared `.log` tail skeleton: caller's `header_lines` + pdk/exit/
    timestamp + `(label, text)` `sections` + raw ngspice output."""
    lines = [
        *header_lines,
        f"# pdk: {pdk.variant} @ open_pdks {pdk.installed_commit} ({pdk.lib_file})",
        f"# ngspice exit: {rc}{' (TIMEOUT)' if timed_out else ''}",
        f"# run (UTC): {stamp:%Y-%m-%dT%H:%M:%SZ}",
        "",
    ]
    for label, text in sections:
        lines += [f"# ==== {label} ====", *[f"| {ln}" for ln in text.splitlines()], ""]
    lines += ["# ==== ngspice stdout+stderr ====", raw.rstrip(), ""]
    return "\n".join(lines)


def write_log(
    corners_dir: Path,
    name: str,
    record_id: str,
    pdk,
    stamp,
    deck: str,
    raw: str,
    rc: int,
    timed_out: bool,
) -> Path:
    """Write the append-only per-point `.log` file, return its `Path`.

    Header + exact `.spiceinit` + exact deck + raw ngspice stdout/stderr,
    `name`-keyed.
    """
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{name}.log"
    init_text = SPICEINIT_FILE.read_text()
    sections = [(".spiceinit (exact)", init_text), ("deck (exact input given to ngspice)", deck)]
    header = [f"# point: {name}", f"# record: {record_id}"]
    path.write_text(render_log(header, pdk, rc, timed_out, stamp, sections, raw))
    return path


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def mv(value: float) -> str:
    """Format a volt-scale value as a millivolt string with 4 decimal places."""
    return f"{value * 1e3:.4f}"


def seed_stability_checks(
    a: dict,
    b: dict,
    vector: str,
    seed_a: int,
    seed_b: int,
    tol: float,
    *,
    sample_field: str = "max_abs",
    sample_label: str = "magnitude",
    sample_unit: str = "mV",
    sample_scale: float = 1e3,
    sample_precision: int = 4,
) -> list[dict]:
    """Two-check seed-stability block for one Monte Carlo vector.

    Compares a run seeded with `seed_a` against a second run seeded with
    `seed_b`: `seed_sigma_stable[vector]` checks the sigma drift stays within
    `tol`, `seed_sample_differs[vector]` checks the worst-sample value
    (`stats[vector][sample_field]`) actually changed between seeds -- i.e.
    the second draw wasn't a no-op.
    """
    sa = a["stats"][vector]["sigma"]
    sb = b["stats"][vector]["sigma"]
    drift = abs(sb / sa - 1.0) if sa else float("inf")
    sample_a = a["stats"][vector][sample_field]
    sample_b = b["stats"][vector][sample_field]
    return [
        {
            "name": f"seed_sigma_stable[{vector}]",
            "pass": drift <= tol,
            "detail": (
                f"sigma(seed {seed_b}) / sigma(seed {seed_a}) = "
                f"{(sb / sa) if sa else float('nan'):.3f} "
                f"({mv(sb)} mV vs {mv(sa)} mV; tolerance +/-{tol:.0%})"
            ),
        },
        {
            "name": f"seed_sample_differs[{vector}]",
            "pass": sample_a != sample_b,
            "detail": (
                f"worst-sample {sample_label} differs between the two seeds "
                f"({sample_a * sample_scale:.{sample_precision}f} {sample_unit} vs "
                f"{sample_b * sample_scale:.{sample_precision}f} {sample_unit}), i.e. the "
                "draw really did change"
            ),
        },
    ]
