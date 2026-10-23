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
`sim/pnp-mismatch/run_pnp_mismatch.py`, `sim/bias-core-op-branch/run_op_branch.py`,
and/or `corner-run.py` itself):

    load_corner_run()    the importlib shim that loads corner-run.py (its
                          filename has a dash, so it can't be `import`ed
                          normally)
    parse_samples()        parses the repeated `op`+`print` blocks of a
                          Monte Carlo loop's ngspice log into per-sample
                          dicts
    render_log()            the shared `.log` tail-formatting skeleton,
                          called directly by both bespoke scripts (inline
                          in `run_op_branch.py`; from inside
                          `run_pnp_mismatch.py`'s own local `write_log()`)
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
    mean()/stdev()/mv()     small numeric/formatting helpers
    seed_stability_checks() the paired same-point/different-seed sigma-drift
                          and worst-sample-changed check pair
    say()/rate_tag()/scrub()/report_usable()/submit_request()
                          batch-fleet campaign-runner helpers shared by
                          por-comparator-thresholds and supply-ramp-top
"""

from __future__ import annotations

import argparse
import functools
import gzip
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

BIN_DIR = Path(__file__).resolve().parent


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


@functools.lru_cache(maxsize=1)
def _corner_run() -> ModuleType:
    return load_corner_run()


def corner_id(proc: str, temp: float, vf: float) -> str:
    """Record/run-directory key for one (process, temperature, supply) corner, e.g. tt_27c_1.80v."""
    return f"{proc}_{_corner_run().fmt_temp(temp)}c_{vf:.2f}v"


def fmt(x, spec: str = ".4g", unit: str = "") -> str:
    """Format a number for a report table; None -> "n/a"."""
    return "n/a" if x is None else f"{x:{spec}}{unit}"


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


# --------------------------------------------------------------------------
# batch-fleet campaign helpers (sim/por-comparator-thresholds, sim/supply-ramp-top)
# --------------------------------------------------------------------------

_print_lock = threading.Lock()


def say(msg: str) -> None:
    """Print one line atomically (campaign runners submit from a thread pool)."""
    with _print_lock:
        print(msg, flush=True)


def rate_tag(rate: float) -> str:
    return "r" + f"{rate:g}".replace("+", "")


def scrub(text: str, run_dir: Path, repo_root: Path) -> str:
    """Make a build-tree log portable: build dir -> <build>, repo prefix dropped, home -> <home>."""
    text = text.replace(str(run_dir), "<build>")
    text = text.replace(str(repo_root) + os.sep, "")
    return re.sub(r"/home/[^/\s]+", "<home>", text)


def report_usable(report_path: Path) -> bool:
    """True when a klt report.json exists and carries per-corner results (the retry-failed predicate)."""
    try:
        return report_path.is_file() and "corners" in json.loads(report_path.read_text())
    except json.JSONDecodeError:
        return False


def submit_prepared(d: Path, netlist: str, request: dict, submit_msg: str, done_label: str, retry=None) -> dict:
    """Archive d's earlier attempt, write netlist.spice + request.json, run `klt sim --backend batch`.

    An earlier attempt's report.json/klt.stderr is archived to attemptN/, never
    overwritten. `submit_msg`/`done_label` are the texts after "[submit] " and
    "[done]   " in the log lines. `retry(proc, n)`, if given, is called after
    each klt run (n = 1, 2, ...) and returns True to run klt again on the same
    request (e.g. a bounded launch-refusal wait); only the last run's output is
    written to report.json/klt.stderr.
    """
    d.mkdir(parents=True, exist_ok=True)
    if (d / "report.json").is_file():  # archive an earlier attempt, never overwrite
        n = 1
        while (d / f"attempt{n}").exists():
            n += 1
        (d / f"attempt{n}").mkdir()
        for name in ("report.json", "klt.stderr"):
            if (d / name).is_file():
                shutil.move(str(d / name), str(d / f"attempt{n}" / name))
    (d / "netlist.spice").write_text(netlist)
    (d / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    cmd = ["klt", "sim", str(d / "request.json"), "--backend", "batch", "-o", str(d / "out"), "--format", "json"]
    say(f"[submit] {submit_msg}")
    runs = 0
    while True:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=4 * 3600)
        runs += 1
        if not (retry and retry(p, runs)):
            break
    (d / "report.json").write_text(p.stdout)
    (d / "klt.stderr").write_text(p.stderr)
    try:
        status = json.loads(p.stdout).get("status", "?")
    except json.JSONDecodeError:
        status = "NO-JSON"
    say(f"[done]   {done_label}: exit {p.returncode}, report status {status}")
    return {"exit": p.returncode, "status": status}


def submit_request(
    variant_name: str,
    rate: float,
    run_dir: Path,
    netlist: str,
    request: dict,
    label: str,
    points: int,
) -> dict:
    """Write netlist.spice + request.json under run_dir/variant/rate_tag and run `klt sim --backend batch`.

    `label` is the text after the rate tag in the [submit] log line (e.g. ""
    or " (axis)"); `points` is the caller's own point count.
    """
    tag = rate_tag(rate)
    res = submit_prepared(
        run_dir / variant_name / tag, netlist, request,
        f"{variant_name} {tag}{label}: {points} points -> batch fleet", f"{variant_name} {tag}",
    )
    return {"variant": variant_name, "rate": rate, "tag": tag, **res}


def klt_version() -> str:
    p = subprocess.run(["klt", "--version"], capture_output=True, text=True)
    return p.stdout.strip() or p.stderr.strip()


DUT_NETLIST = Path(__file__).resolve().parents[2] / "design" / "netlist" / "temp_por_top.spice"

# Fleet-runner workaround: the runner ignores options.ngspice_init, so the setting
# from sim/spiceinit is carried in the netlist itself.  Change it here only.
NOMODCHECK_CONTROL = ".control\nset ng_nomodcheck\n.endc\n"


def drop_end(text: str) -> str:
    """Drop the `.end` line(s) so the netlist can be embedded in a wrapper deck."""
    return "\n".join(ln for ln in text.splitlines() if ln.strip().lower() != ".end") + "\n"


def load_dut_netlist(path: Path = DUT_NETLIST) -> str:
    """Read a committed DUT export with its `.end` dropped."""
    return drop_end(Path(path).read_text())


def netlist_tb_head(sch: Path, out_dir: Path, pdk) -> str:
    """Netlist a testbench via `klt netlist`; keep only the testbench part (the DUT comes from the committed export)."""
    cr = sys.modules.get("corner_run") or load_corner_run()
    produced = cr.netlist_with_klt(sch, out_dir, pdk)
    text = produced.read_text().replace(str(BIN_DIR.parent.parent) + os.sep, "")
    head = text.split("\n* expanding")[0]
    return drop_end(head)


def load_manifest(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def load_wave(path: Path) -> dict[str, list[float]]:
    """Load a klt waveform JSON (optionally gzip) into {lowercased name: samples}.

    Raises ValueError on a malformed document, ragged row or non-numeric value.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as fh:
        doc = json.load(fh)
    try:
        names = [v["name"].lower() for v in doc["variables"]]
        rows = doc["points"]
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"malformed waveform document: {e!r}") from e
    if not names or not isinstance(rows, list):
        raise ValueError("malformed waveform document: no variables or points not a list")
    cols: dict[str, list[float]] = {n: [] for n in names}
    for i, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(names):
            raise ValueError(f"malformed waveform row {i}: expected {len(names)} values, got {len(row) if isinstance(row, (list, tuple)) else type(row).__name__}")
        for n, x in zip(names, row):
            try:
                cols[n].append(float(x))
            except (TypeError, ValueError) as e:
                raise ValueError(f"malformed waveform row {i}: non-numeric value {x!r} for {n}") from e
    return cols


# --------------------------------------------------------------------------
# waveform primitives shared by the supply-ramp and brown-out checkers
# --------------------------------------------------------------------------


def interp_cross(t0, y0, t1, y1, level):
    """Time ``level`` is crossed on the segment (t0,y0)-(t1,y1); t1 for a flat segment."""
    if y1 == y0:
        return t1
    return t0 + (level - y0) * (t1 - t0) / (y1 - y0)


def crossings(t, y, level, direction, t_from=0.0):
    """Interpolated crossing times of ``level`` ('rise' or 'fall'), t > t_from."""
    out = []
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        a, b = y[i - 1], y[i]
        if direction == "rise" and a < level <= b:
            out.append(interp_cross(t[i - 1], a, t[i], b, level))
        elif direction == "fall" and a > level >= b:
            out.append(interp_cross(t[i - 1], a, t[i], b, level))
    return out


def interp_at(t, y, when):
    """Piecewise-linear value of y at ``when`` (clamped to the end samples)."""
    if when <= t[0]:
        return y[0]
    if when >= t[-1]:
        return y[-1]
    lo, hi = 0, len(t) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if t[mid] <= when:
            lo = mid
        else:
            hi = mid
    return y[lo] + (when - t[lo]) * (y[hi] - y[lo]) / (t[hi] - t[lo]) if t[hi] != t[lo] else y[hi]


def schmitt(t, y, lo, hi, init_high=False, t_from=0.0):
    """(rise_times, fall_times) of a two-threshold detector over t > t_from, starting in ``init_high``."""
    state = init_high
    rises, falls = [], []
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        a, b = y[i - 1], y[i]
        if not state and b >= hi:
            rises.append(interp_cross(t[i - 1], a, t[i], b, hi) if a < hi else t[i])
            state = True
        elif state and b <= lo:
            falls.append(interp_cross(t[i - 1], a, t[i], b, lo) if a > lo else t[i])
            state = False
    return rises, falls


def write_gz_rows(path: Path, header: str, rows) -> None:
    """Write ``header`` then one ``%.6g`` CSV line per row to a gzip file (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header] + [",".join(f"{x:.6g}" for x in r) for r in rows]
    with gzip.open(path, "wt", compresslevel=9) as fh:
        fh.write("\n".join(lines) + "\n")


def decimate(cols, keep_dt, thresholds, keep_at=None):
    """Change-triggered decimation of column-major ``cols`` (``cols[0]`` is time).

    Keep the first and last sample, plus any sample where ``dt >= keep_dt`` since the last kept
    row, or a column with a non-None entry in ``thresholds`` (aligned with ``cols``) moved by at
    least that much, or ``keep_at(t)`` is true.  Returns kept rows (row-major).
    """
    n = len(cols[0])
    trig = [(k, th) for k, th in enumerate(thresholds) if k and th is not None]
    rows = [[c[0] for c in cols]]
    last = rows[0]
    for i in range(1, n - 1):
        cur = [c[i] for c in cols]
        if (keep_at is not None and keep_at(cur[0])) or cur[0] - last[0] >= keep_dt or any(abs(cur[k] - last[k]) >= th for k, th in trig):
            rows.append(cur)
            last = cur
    rows.append([c[n - 1] for c in cols])
    return rows
