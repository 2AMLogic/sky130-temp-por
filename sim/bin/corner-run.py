#!/usr/bin/env python3
"""PVT corner runner for sky130-temp-por.

Netlists an xschem testbench, runs a process/voltage/temperature matrix through
`klt sim` against the pinned sky130 PDK, and writes an append-only evidence
record under sim/<experiment-slug>/. See sim/README.md for the record format
and the rules the runner enforces.

Usage
-----
    sim/bin/corner-run.py sim/bias-core-smoke                # full PVT matrix -> fleet
    sim/bin/corner-run.py sim/bias-core-smoke --quick \\
        --subset-reason "harness liveness check"            # quick_subset -> local klt
    sim/bin/corner-run.py sim/bias-core-smoke --process tt --temp 27 --supply 3.3 \\
        --subset-reason "one-point probe"                   # single point -> local klt
    sim/bin/corner-run.py sim/bias-core-smoke --dry-run      # print the klt requests
    sim/bin/corner-run.py --print-env                       # PDK env exports

One request builder serves both backends. A full or multi-point matrix is
submitted as ONE `klt sim --backend batch` request per sweep (never per-corner
calls) and the record carries the fleet's own PDK stamp, engine and job id. A
single point and --quick run as `klt sim --backend local`, one request per point;
`--backend local` on a grid is refused before anything launches. A failed submit
is an error quoting klt verbatim; there is no local fallback.

The runner never edits or deletes an existing record: it refuses to start if
the record id it would mint already exists on disk.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# sim_common.py lives alongside this file (sim/bin/) so it resolves whether
# this module is run directly (Python auto-prepends the script's own
# directory to sys.path) or loaded via sim_common.load_corner_run()'s
# importlib shim (whose only caller already put sim/bin on sys.path before
# importing sim_common in the first place) -- issue #191.
import sim_common
import evidence_store

SIM_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SIM_DIR.parent
PDK_PIN_FILE = SIM_DIR / "pdk.json"
SPICEINIT_FILE = SIM_DIR / "spiceinit"
XSCHEMRC_FILE = SIM_DIR / "xschemrc"
BUILD_DIR = SIM_DIR / "build"


class HarnessError(RuntimeError):
    """A problem the operator has to fix; never produces a record."""


# --------------------------------------------------------------------------
# PDK resolution
# --------------------------------------------------------------------------


@dataclass
class Pdk:
    pin: dict
    root: Path
    variant: str
    dir: Path
    installed_commit: str
    lib_file: Path

    @property
    def matches_pin(self) -> bool:
        return self.installed_commit == self.pin["open_pdks_commit"]


def load_pin() -> dict:
    if not PDK_PIN_FILE.exists():
        raise HarnessError(f"missing PDK pin file: {PDK_PIN_FILE}")
    return json.loads(PDK_PIN_FILE.read_text())


def resolve_pdk(pin: dict) -> Pdk:
    root_env = os.environ.get("PDK_ROOT", "").strip()
    if root_env:
        root = Path(root_env).expanduser()
    else:
        # One tree only: $PDK_ROOT or the pinned default (~/.ciel). No probe of
        # any other install, so a shadowing tree cannot be picked up (#188).
        root = Path(pin["default_pdk_root"]).expanduser()
    variant = os.environ.get("PDK", "").strip() or pin["variant"]
    pdk_dir = root / variant
    if not pdk_dir.is_dir():
        raise HarnessError(
            f"no PDK at {pdk_dir}\n"
            f"  install the pinned version with: {pin['install_command']}\n"
            f"  (or set PDK_ROOT / PDK to an existing install)"
        )
    lib_file = pdk_dir / pin["ngspice_lib"]
    if not lib_file.is_file():
        raise HarnessError(f"no ngspice model library at {lib_file}")
    return Pdk(
        pin=pin,
        root=root,
        variant=variant,
        dir=pdk_dir,
        installed_commit=installed_commit(pdk_dir),
        lib_file=lib_file,
    )


def installed_commit(pdk_dir: Path) -> str:
    """Recover the ciel version hash by resolving the PDK symlink."""
    parts = pdk_dir.resolve().parts
    if "versions" in parts:
        idx = parts.index("versions")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return "unknown"


def pdk_mismatch_message(pdk: Pdk, pin: dict) -> str:
    return (
        f"installed PDK {pdk.dir} is open_pdks {pdk.installed_commit}, "
        f"but sim/pdk.json pins {pin['open_pdks_commit']}\n"
        f"  install the pin: {pin['install_command']}"
    )


def print_env(pdk: Pdk) -> None:
    print(f"export PDK_ROOT={pdk.root}")
    print(f"export PDK={pdk.variant}")
    print(f"export SKY130_MODEL_LIB={pdk.lib_file}")
    print(f"export XSCHEM_RCFILE={XSCHEMRC_FILE}")


# --------------------------------------------------------------------------
# tool versions
# --------------------------------------------------------------------------


def first_line(cmd: list[str]) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        return "not found"
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=60
        )
    except (subprocess.SubprocessError, OSError) as exc:  # pragma: no cover
        return f"error: {exc}"
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip().lstrip("*").strip()
        if line:
            return line
    return "unknown"


def tool_versions() -> dict:
    return {
        "ngspice": first_line(["ngspice", "-v"]),
        "xschem": first_line(["xschem", "--version"]),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
    }


# --------------------------------------------------------------------------
# git provenance
# --------------------------------------------------------------------------


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def git_state() -> dict:
    sha = git("rev-parse", "--short", "HEAD") or "nogit"
    dirty = bool(git("status", "--porcelain"))
    return {
        "sha": sha,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "dirty": dirty,
    }


def default_author() -> str:
    for var in ("SIM_AUTHOR", "LOOM_AGENT"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return git("config", "user.email") or "unknown"


# --------------------------------------------------------------------------
# experiment manifest
# --------------------------------------------------------------------------


@dataclass
class Measurement:
    name: str
    expr: str
    unit: str = ""
    min: float | None = None
    max: float | None = None
    note: str = ""
    # Index into the manifest's real analyses (non-`let` entries of deck.analyses)
    # that produces this measurement's vectors. Only matters for a deck with more
    # than one analysis (two dc sweeps): each sweep is its own request.
    analysis: int = 0


@dataclass
class Experiment:
    dir: Path
    raw: dict
    measurements: list[Measurement] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.raw["slug"]

    @property
    def schematic(self) -> Path:
        return (self.dir / self.raw["schematic"]).resolve()


def load_experiment(path: Path) -> Experiment:
    exp_dir = path.resolve()
    manifest = exp_dir / "experiment.json"
    if not manifest.is_file():
        raise HarnessError(f"no experiment.json in {exp_dir}")
    raw = json.loads(manifest.read_text())
    for key in ("slug", "claim", "schematic", "corners", "measurements"):
        if key not in raw:
            raise HarnessError(f"{manifest}: missing required key {key!r}")
    exp = Experiment(dir=exp_dir, raw=raw)
    exp.measurements = [Measurement(**m) for m in raw["measurements"]]
    if not exp.schematic.is_file():
        raise HarnessError(f"{manifest}: schematic not found: {exp.schematic}")
    return exp


# --------------------------------------------------------------------------
# corner matrix
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Corner:
    process: str
    temp_c: float
    supply_v: float

    @property
    def id(self) -> str:
        temp = f"{self.temp_c:g}"
        return f"{self.process}_{temp}c_{self.supply_v:.2f}v"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.id


def fmt_temp(value: float) -> str:
    return f"{value:g}"


def unique_in_order(values) -> list:
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def build_matrix(exp: Experiment, args: argparse.Namespace, pin: dict) -> tuple[list[Corner], bool]:
    corners = exp.raw["corners"]
    if args.quick:
        subset = exp.raw.get("quick_subset")
        if not subset:
            raise HarnessError(f"{exp.slug}: --quick needs a quick_subset in experiment.json")
        return [Corner(p, float(t), float(v)) for p, t, v in subset], True

    process = args.process or corners["process"]
    temps = args.temp if args.temp is not None else corners["temperature_c"]
    supplies = args.supply if args.supply is not None else corners["supply_v"]

    known = set(pin["process_corners"])
    unknown = [p for p in process if p not in known]
    if unknown:
        raise HarnessError(
            f"process corner(s) {unknown} are not in sim/pdk.json process_corners "
            f"{sorted(known)}; add them there once verified against the PDK "
            f"library sections"
        )

    matrix = [
        Corner(p, float(t), float(v))
        for p in process
        for t in temps
        for v in supplies
    ]
    is_subset = (
        list(process) != list(corners["process"])
        or [float(t) for t in temps] != [float(t) for t in corners["temperature_c"]]
        or [float(v) for v in supplies] != [float(v) for v in corners["supply_v"]]
    )
    return matrix, is_subset


# --------------------------------------------------------------------------
# netlisting
# --------------------------------------------------------------------------


def netlist_body(netlist: Path) -> list[str]:
    """Strip the trailing .end so the deck can wrap the netlist.

    Also rewrites the absolute path xschem stamps into its `** sch_path:`
    comment to a repo-relative one, so netlist snapshots are byte-comparable
    across machines and checkouts.
    """
    text = netlist.read_text().replace(str(REPO_ROOT) + os.sep, "")
    return [ln for ln in text.splitlines() if ln.strip().lower() != ".end"]


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------


def evaluate_measurements(exp: Experiment, values: dict[str, float]) -> tuple[list[dict], bool]:
    """Grade measured values against the manifest's min/max windows.

    Both backends (fleet and local klt) go through this, so they apply the
    same pass/fail rules and emit the same per-measurement check schema.
    """
    checks = []
    ok = True
    for m in exp.measurements:
        value = values.get(m.name)
        passed = value is not None
        reason = "" if passed else "measurement not reported by the simulator"
        if passed and m.min is not None and value < m.min:
            passed, reason = False, f"below min {m.min:g}"
        if passed and m.max is not None and value > m.max:
            passed, reason = False, f"above max {m.max:g}"
        checks.append(
            {
                "name": m.name,
                "expr": m.expr,
                "unit": m.unit,
                "value": value,
                "min": m.min,
                "max": m.max,
                "pass": passed,
                "reason": reason,
            }
        )
        ok = ok and passed
    return checks, ok


# --------------------------------------------------------------------------
# klt netlist + batch backend (klt sim --backend batch)
# --------------------------------------------------------------------------


def netlist_with_klt(schematic: Path, out_dir: Path, pdk: Pdk) -> Path:
    """Netlist via `klt netlist` (headless flags, bounded run) -- never raw xschem."""
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = out_dir / (schematic.stem + ".spice")
    cmd = [
        "klt", "netlist", str(schematic),
        "-o", str(produced),
        "--rcfile", str(XSCHEMRC_FILE),
        "--pdk", pdk.variant,
        "--pdk-root", str(pdk.root),
        "--timeout-s", "300",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=360, stdin=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise HarnessError("klt not found on PATH; netlisting needs klayout-tools (klt netlist)")
    if proc.returncode != 0 or not produced.is_file():
        raise HarnessError(
            "klt netlist failed\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  rc: {proc.returncode}\n"
            f"  stdout: {proc.stdout.strip()}\n"
            f"  stderr: {proc.stderr.strip()}"
        )
    return produced


def batch_axes(matrix: list[Corner]) -> tuple[list[str], list[float], list[float]]:
    """The (process, temperature, supply) axes of a cross-product matrix.

    One `klt sim` request spans a full cross product; an explicit point list
    (e.g. a quick_subset) is not expressible as one grid request.
    """
    process = unique_in_order(c.process for c in matrix)
    temps = sorted({c.temp_c for c in matrix})
    supplies = sorted({c.supply_v for c in matrix})
    if len(matrix) != len(process) * len(temps) * len(supplies):
        raise HarnessError(
            "the batch backend submits one grid request, but this corner list is not a "
            "full process x temperature x supply cross product; run it with --backend local"
        )
    return process, temps, supplies


def build_batch_netlist(exp: Experiment, body: list[str], matrix: list[Corner]) -> str:
    """Netlist for the fleet: klt supplies .lib, .temp and the supply alter.

    The netlist carries `set ng_nomodcheck` in its own .control block (the same
    line sim/spiceinit gives the local path): the runner ignores
    options.ngspice_init (sim_common.FLEET_NOTE), and without it ngspice's BSIM
    parameter check aborts the deck before simulating on this repo's native
    nfet_05v0_nvt device (`pdits negative`, XMASSIST) -- the mechanism every
    bespoke campaign already ships (glitch-top, iq-top, ...)."""
    deck = exp.raw.get("deck", {})
    supplies = sorted({c.supply_v for c in matrix})
    nominal = supplies[len(supplies) // 2]
    head = [
        f"* {exp.slug} batch netlist -- generated by sim/bin/corner-run.py, do not edit",
        "* .lib / .temp / supply value are applied per corner by klt sim; vsup below is only",
        "* the placeholder the testbench's supply source references before klt's alter.",
        f".param vsup={nominal}",
    ]
    for name, value in (deck.get("params") or {}).items():
        head.append(f".param {name}={value}")
    for opt in deck.get("options") or []:
        head.append(f".option {opt}")
    return "\n".join(head + body + [sim_common.NOMODCHECK_CONTROL, ".end", ""])


HELPER_RE = re.compile(r"^let\s+([A-Za-z_]\w*)\s*=\s*(.+)$", re.IGNORECASE)


@dataclass
class SweepUnit:
    """One analysis and the measurements it owns: one `klt sim` request."""

    name: str
    analysis: str
    measurements: list[Measurement]


def split_analyses(exp: Experiment) -> tuple[list[str], dict[str, str]]:
    """Separate `deck.analyses` into real analyses and `let` helper definitions.

    A `let nlast = ...` entry is not an analysis: it is a name the measurement
    expressions use. klt takes expressions, not control statements, so the helper
    is inlined into every expression that reads it (see `request_expr`).
    """
    real: list[str] = []
    helpers: dict[str, str] = {}
    for entry in exp.raw.get("deck", {}).get("analyses") or ["op"]:
        m = HELPER_RE.match(entry.strip())
        if m:
            helpers[m.group(1)] = m.group(2).strip()
        else:
            real.append(entry.strip())
    if not real:
        raise HarnessError(f"{exp.slug}: deck.analyses has no analysis, only `let` helpers")
    return real, helpers


# klt evaluates each measurement as `let <name> = <expr>` in the plot that holds the
# circuit's node vectors, so a measurement named like a node (`ptat`, `vref`,
# `bias_ok`) REPLACES that vector with a one-element scalar and every later
# expression reading `v(<node>)` or `length(v(<node>))` sees the scalar (found as
# `ptat_settled` = 0 and `bias_ok` ~ 2 mV on a powered circuit). The old local deck
# avoided this with a `meas_` prefix; the request carries it too and
# `results_from_reports` strips it.
MEAS_PREFIX = "meas_"


def request_expr(expr: str, helpers: dict[str, str]) -> str:
    """The measurement expression as klt sees it.

    `let` helpers are inlined (`v(x)[nlast]` -> `v(x)[length(v(x))-1]`); a `dcN.`
    plot qualifier is dropped because each sweep is its own request with a single
    plot.
    """
    for name, body in helpers.items():
        expr = re.sub(rf"(?<![\w.]){re.escape(name)}(?!\w)", lambda _m, b=body: b, expr)
    return re.sub(r"(?<![\w.])dc\d+\.", "", expr)


def sweep_units(exp: Experiment) -> list[SweepUnit]:
    """One unit per real analysis that owns at least one measurement."""
    real, _ = split_analyses(exp)
    for m in exp.measurements:
        if not 0 <= m.analysis < len(real):
            raise HarnessError(
                f"{exp.slug}: measurement {m.name!r} names analysis {m.analysis}, "
                f"but the deck has {len(real)} analysis(es)"
            )
    units = []
    for i, analysis in enumerate(real):
        owned = [m for m in exp.measurements if m.analysis == i]
        if owned:
            units.append(SweepUnit(name=f"sweep{i + 1}" if len(real) > 1 else "", analysis=analysis, measurements=owned))
    return units


def build_batch_request(
    exp: Experiment,
    pdk: Pdk,
    matrix: list[Corner],
    timeout: int,
    capacity_wait_s: float = 0,
    unit: SweepUnit | None = None,
    backend: str = "batch",
) -> dict:
    """The klt sim request for one sweep unit of `exp` over `matrix`.

    The same builder serves both backends (`backend` is "batch" or "local"); only
    the `backend` field and the `batch` block differ.
    """
    deck = exp.raw.get("deck", {})
    _, helpers = split_analyses(exp)
    if unit is None:
        unit = sweep_units(exp)[0]
    kind, _, args = unit.analysis.partition(" ")
    analysis = {"kind": kind.lower(), "args": args.strip()}
    process, temps, supplies = batch_axes(matrix)
    corners: dict
    supply_param = deck.get("supply_param")
    if supply_param:
        # The supply is a `.param` the testbench's PWL stimulus reads, so an `alter`
        # of the source would not move it; one parameter row per supply instead.
        corners = {"process": process, "params": {supply_param: supplies}, "temperature_c": temps}
    else:
        corners = {
            "process": process,
            "supply_v": {deck.get("supply_source", "v1"): supplies},
            "temperature_c": temps,
        }
    request: dict = {
        "netlist": "netlist.spice",
        "backend": backend,
        "models": {"pdk": pdk.variant, "lib": pdk.pin["ngspice_lib"]},
        "corners": corners,
        "analysis": analysis,
        "measurements": [
            {
                "name": MEAS_PREFIX + m.name,
                "expr": request_expr(m.expr, helpers),
                **({"unit": m.unit} if m.unit else {}),
            }
            for m in unit.measurements
        ],
        "options": {"timeout_s": timeout, "keep_artifacts": True},
    }
    if backend == "batch":
        batch: dict = {"runner_version_check": "warn"}
        if capacity_wait_s:
            batch["capacity_wait_s"] = capacity_wait_s
        request["batch"] = batch
    return request


# One parser for the repo, and it lives in `sim_common` so the other seven runners can
# compare their runners' stamp with the pin too (issue #333).  This name stays as the
# module's own alias: `fleet_pdk_commit` is what this file's callers and tests use, and a
# re-export is a delegation, not the second copy issue #333 exists to remove.
fleet_pdk_commit = sim_common.fleet_pdk_commit


def fleet_pdk_block(fleet_commit: str, local_commit: str, pin: dict) -> dict:
    """The fleet overlay of a BATCH record's `pdk` block: whose install
    `installed_commit` describes, and how it compares with the `sim/pdk.json` pin.

    On a batch record the fleet ran the simulator, so `installed_commit` is the runner's
    and this host's is parked under `local_installed_commit` -- which is also what tells
    `sim_common.render_pdk_tools_repo_state()` that this line's pin state is the fleet's.

    The verdict is three-state (`sim_common.fleet_pin_verdict()`), not the bool this path
    used to compute as `installed_commit != pin["open_pdks_commit"]`: `fleet_pdk_commit()`
    returns the string `"unknown"` for a runner that reported no 40-hex commit, which
    compares unequal to any pin -- so an *unstamped* fleet run was recorded and printed as
    `**MISMATCH vs sim/pdk.json pin**` and exited 3.  Unverifiable is not wrong
    (issue #333).  `matches_pin` stays beside it as the two-state form older readers and
    already-written records use, derived from the verdict so they cannot disagree.
    """
    verdict = sim_common.fleet_pin_verdict([fleet_commit], pin)
    return {
        "local_installed_commit": local_commit,
        "fleet_matches_pin": verdict,
        "matches_pin": verdict == "match",
        "fleet_pin_limit": sim_common.PIN_COMMIT_LIMIT,
    }


def _report_corner_key(c: dict, supply_param: str | None = None) -> tuple:
    supply = c.get("supply_v")
    if isinstance(supply, dict) and supply:
        supply = next(iter(supply.values()))
    elif supply_param:
        supply = (c.get("params") or {}).get(supply_param)
    return (c.get("process"), float(c["temperature_c"]), float(supply))


def results_from_report(
    exp: Experiment, matrix: list[Corner], report: dict, corners_dir: Path, timeout: int
) -> list[dict]:
    """Per-corner result dicts from a single-sweep report (see `results_from_reports`)."""
    return results_from_reports(exp, matrix, [(sweep_units(exp)[0], report)], corners_dir, timeout)


def results_from_reports(
    exp: Experiment,
    matrix: list[Corner],
    unit_reports: list[tuple[SweepUnit, dict]],
    corners_dir: Path,
    timeout: int,
) -> list[dict]:
    """Join each sweep's klt report.json by (process, temperature, supply) and grade.

    A corner missing from any sweep's report leaves that sweep's measurements
    without a value, which `evaluate_measurements` fails, and marks the corner
    errored; so a missing corner, sweep or measurement can never pass. Limits are
    graded here, not by klt, so both backends share one pass/fail rule.
    """
    supply_param = exp.raw.get("deck", {}).get("supply_param")
    keyed = []
    for unit, report in unit_reports:
        by_key = {}
        for c in report.get("corners", []):
            try:
                by_key[_report_corner_key(c, supply_param)] = c
            except (KeyError, TypeError, ValueError):
                continue
        keyed.append((unit, by_key))
    results = []
    for corner in matrix:
        values: dict = {}
        statuses: list[str] = []
        runtime = 0.0
        diagnostics: list = []
        errored = False
        for unit, by_key in keyed:
            rc = by_key.get((corner.process, corner.temp_c, corner.supply_v))
            status = "missing" if rc is None else rc.get("status", "?")
            label = f"{unit.name}={status}" if unit.name else status
            statuses.append(label)
            if rc is None or status in ("error", "errored"):
                errored = True
            if rc is not None:
                runtime += float(rc.get("runtime_s") or 0.0)
                diagnostics += rc.get("diagnostics", [])
                owned = {m.name for m in unit.measurements}
                values.update(
                    {
                        m["name"].removeprefix(MEAS_PREFIX): m["value"]
                        for m in rc.get("measurements", [])
                        if m.get("value") is not None and m["name"].removeprefix(MEAS_PREFIX) in owned
                    }
                )
        checks, ok = evaluate_measurements(exp, values)
        log_path = corners_dir / f"{corner.id}.log"
        results.append(
            {
                "corner_id": corner.id,
                "process": corner.process,
                "temperature_c": corner.temp_c,
                "supply_v": corner.supply_v,
                "ngspice_exit": 1 if errored else 0,
                "timed_out": False,
                "killed_by_signal": None,
                "killed_by_signal_name": None,
                "elapsed_s": round(runtime, 3),
                "timeout_s": timeout,
                "measurements": checks,
                "pass": ok and not errored,
                "log": str(log_path.relative_to(REPO_ROOT)),
                "batch_status": ", ".join(statuses),
                "diagnostics": diagnostics,
            }
        )
    return results


def write_batch_corner_log(res: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# corner: {res['corner_id']}",
        f"# process={res['process']} temp={fmt_temp(res['temperature_c'])}C "
        f"supply={res['supply_v']:.2f}V",
        f"# klt sim corner status: {res['batch_status']}",
        f"# result: {'PASS' if res['pass'] else 'FAIL'}",
        "",
    ]
    for d in res["diagnostics"]:
        lines.append(f"# diagnostic [{d.get('severity')}] {d.get('code')}: {d.get('message')}")
    log_path.write_text("\n".join(lines) + "\n")


def submit_batch(
    exp: Experiment,
    matrix: list[Corner],
    netlist: str,
    request: dict,
    run_dir: Path,
    subdir: str = "batch",
) -> tuple[dict, dict]:
    """Submit the grid as one `klt sim --backend batch` request.

    Returns (report, fleet) where `fleet` carries what the fleet reported about
    itself. A submit that yields no usable report is a HarnessError quoting klt
    verbatim: there is no local fallback.

    Waiting out a fleet capacity refusal is klt's job, armed by the request's
    batch.capacity_wait_s (written by `build_batch_request`); there is no
    caller-side resubmit loop here.
    """
    d = run_dir / subdir
    outcome = sim_common.submit_prepared(
        d, netlist, request, f"{exp.slug}: {len(matrix)} points -> batch fleet", exp.slug,
    )
    report_path = d / "report.json"
    if not sim_common.report_usable(report_path):
        raise HarnessError(
            f"batch submit produced no usable report (klt exit {outcome['exit']}, "
            f"status {outcome['status']}); not falling back to a local grid\n"
            f"  klt stdout (verbatim): {report_path.read_text().strip()}\n"
            f"  klt stderr (verbatim): {(d / 'klt.stderr').read_text().strip()}"
        )
    report = json.loads(report_path.read_text())
    prov = report.get("provenance") or {}
    env = report.get("environment") or {}
    remote = env.get("remote") or {}
    pdk_prov = prov.get("pdk") or {}
    # `provenance.pdk` describes the PDK the *client* resolved, not the runner's:
    # the runner executes against its own /opt/pdk, whose stamp is reported under
    # remote.worker_environment.pdk. Cite the runner's stamp; only when the fleet
    # reports none is the commit "unknown" (never the client's, which would
    # make an unverified fleet look pinned). `sim_common.runner_pdk()` is the one
    # reader of that field for every runner in the repo (issue #328).
    runner_pdk = sim_common.runner_pdk(remote)
    runner_stamp = runner_pdk.get("stamp_text") or ""
    return report, {
        "pdk": {
            "installed_commit": fleet_pdk_commit(runner_stamp),
            "lib_file": f"{request['models']['lib']} (resolved on the runner)",
        },
        "ngspice": f"{env.get('engine', 'ngspice')} {env.get('engine_version', '?')} (fleet)",
        "batch": {
            "job_id": remote.get("job_id"),
            "klt_client": sim_common.klt_version(),
            "runner_klt": remote.get("runner_klt_version"),
            "fleet_pdk_name": runner_pdk.get("variant") or pdk_prov.get("name"),
            "fleet_pdk_version": runner_stamp or "not reported by the runner",
            "client_pdk_version": pdk_prov.get("version"),
            "models_lib_sha256": env.get("models_lib_sha256"),
            "status": report.get("status"),
            "remote": remote,
        },
    }


def run_local(
    exp: Experiment,
    pdk: Pdk,
    corner: Corner,
    netlist: str,
    request: dict,
    run_dir: Path,
    subdir: str,
) -> dict:
    """Run ONE corner as one `klt sim --backend local` request; return its report.

    Local execution is for a single point (never a grid): the caller guarantees
    `request` spans exactly one corner. A run that yields no usable report is a
    HarnessError quoting klt verbatim.
    """
    d = run_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / "netlist.spice").write_text(netlist)
    (d / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    sim_common.say(f"[local]  {exp.slug}: {corner.id}")
    saved = os.environ.get("PDK_ROOT")
    os.environ["PDK_ROOT"] = str(pdk.root)  # klt local resolves the PDK from here
    try:
        proc = sim_common.run_local_probe(d)
    finally:
        if saved is None:
            os.environ.pop("PDK_ROOT", None)
        else:
            os.environ["PDK_ROOT"] = saved
    report_path = d / "report.json"
    if not sim_common.report_usable(report_path):
        raise HarnessError(
            f"local klt sim produced no usable report for {corner.id} (klt exit {proc.returncode})\n"
            f"  klt stdout (verbatim): {report_path.read_text().strip()}\n"
            f"  klt stderr (verbatim): {(d / 'klt.stderr').read_text().strip()}"
        )
    return json.loads(report_path.read_text())


# --------------------------------------------------------------------------
# spread checks (is the harness actually corner-aware?)
# --------------------------------------------------------------------------


def spread_checks(exp: Experiment, results: list[dict]) -> list[dict]:
    out = []
    for check in exp.raw.get("spread_checks") or []:
        name = check["measurement"]
        values = [
            c["value"]
            for r in results
            for c in r["measurements"]
            if c["name"] == name and c["value"] is not None
        ]
        spread = (max(values) - min(values)) if len(values) > 1 else 0.0
        passed = len(values) > 1 and spread >= float(check["min_spread"])
        out.append(
            {
                "measurement": name,
                "min_spread": float(check["min_spread"]),
                "observed_spread": spread,
                "n": len(values),
                "pass": passed,
                "note": check.get("note", ""),
                "reason": (
                    ""
                    if passed
                    else (
                        "fewer than two corner points"
                        if len(values) < 2
                        else "spread below min_spread -- corners may not be taking effect"
                    )
                ),
            }
        )
    return out


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------


def render_record(record: dict) -> str:
    r = record
    lines = [f"# Record {r['record_id']}", ""]
    lines += sim_common.render_record_id_experiment(
        r["record_id"], r["experiment"]["slug"], r["experiment"]["title"]
    )
    lines.append(f"- **Claim**: {r['experiment']['claim']}")
    lines.append(
        f"- **Netlist provenance**: {r['experiment']['provenance']} "
        f"(`{r['experiment']['provenance_source']}`)"
    )
    lines += sim_common.render_pdk_tools_repo_state(r)
    if r.get("batch"):
        b = r["batch"]
        lines.append(
            f"- **Backend**: `klt sim --backend batch` (fleet job `{b['job_id']}`); "
            f"klt client `{b['klt_client']}`, runner klt `{b['runner_klt']}`; "
            f"runner PDK `{b['fleet_pdk_name']}` stamp `{b['fleet_pdk_version']}` "
            f"(client-side PDK: {b.get('client_pdk_version')}); "
            f"client-staged models lib sha256 `{b['models_lib_sha256']}`"
        )
        if len(b.get("submissions") or []) > 1:
            lines.append(
                "  - Fleet submissions (one per sweep): "
                + "; ".join(f"`{x['request']}` job `{x['job_id']}` ({x['status']})" for x in b["submissions"])
            )
    elif r.get("backend") == "local":
        lines.append(
            f"- **Backend**: `klt sim --backend local` (one request per point on this host); "
            f"klt client `{r['local']['klt_client']}`; PDK models lib `{r['pdk']['lib_file']}`"
        )

    matrix = r["matrix"]
    lines.append("- **Corner matrix run**:")
    lines.append(f"  - Process: {', '.join(matrix['process'])}")
    lines.append(
        "  - Temperature: " + ", ".join(f"{fmt_temp(t)} °C" for t in matrix["temperature_c"])
    )
    lines.append("  - Supply: " + ", ".join(f"{v:.2f} V" for v in matrix["supply_v"]))
    lines.append(f"  - {matrix['n_points']} corner point(s) executed")
    axes_product = (
        len(matrix["process"]) * len(matrix["temperature_c"]) * len(matrix["supply_v"])
    )
    if matrix["n_points"] != axes_product:
        lines.append(
            "  - Explicit point list (not the full cross product of the axes above): "
            + ", ".join(f"`{p}`" for p in matrix["point_ids"])
        )
    if matrix["is_subset"]:
        lines.append(f"  - **Subset of the full PVT matrix.** Reason: {matrix['subset_reason']}")
    else:
        lines.append(
            "  - Full PVT matrix declared in `experiment.json` "
            "(−40/27/125 °C × ±10 % supply × process corners)"
        )
    lines.append(f"- **Statistical convention**: {r['experiment']['statistical_convention']}")

    lines.append("- **Result**:")
    for res in r["corners"]:
        parts = []
        for c in res["measurements"]:
            value = "n/a" if c["value"] is None else f"{c['value']:.6g}{c['unit']}"
            parts.append(f"{c['name']}={value}")
        verdict = "PASS" if res["pass"] else "FAIL"
        detail = "; ".join(parts)
        why = ""
        fails = [c["reason"] for c in res["measurements"] if not c["pass"] and c["reason"]]
        if res["ngspice_exit"] != 0:
            fails.append(f"simulator status {res.get('batch_status', 'error')}")
        if fails:
            why = f" — {'; '.join(fails)}"
        lines.append(f"  - {res['corner_id']}: {verdict} ({detail}){why}")
    for sc in r["spread_checks"]:
        verdict = "PASS" if sc["pass"] else "FAIL"
        lines.append(
            f"  - corner-sensitivity check on `{sc['measurement']}`: {verdict} "
            f"(observed spread {sc['observed_spread']:.6g} over {sc['n']} points, "
            f"required ≥ {sc['min_spread']:g})"
            + (f" — {sc['reason']}" if sc["reason"] else "")
        )
    lines.append(f"  - **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")

    lines += sim_common.record_footer_lines(
        r, "sim/bin/corner-run.py", nested=True, links=[
            ("Testbench", r["links"]["testbench"]),
            ("Netlist snapshot", r["links"]["netlist_snapshot"]),
            ("Raw per-corner logs (artifact store manifest)", r["links"]["artifact_manifest"]),
            ("Stored-object summary", r["links"]["artifact_summary"]),
            ("Machine-readable record", r["links"]["json"]),
            ("Experiment manifest", r["links"]["manifest"]),
        ])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def csv_floats(value: str) -> list[float]:
    return [float(v) for v in csv_list(value)]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PVT corner runner for sky130-temp-por (see sim/README.md)"
    )
    p.add_argument("experiment", nargs="?", help="path to sim/<experiment-slug>/")
    p.add_argument("--print-env", action="store_true", help="print PDK env exports and exit")
    p.add_argument("--process", type=csv_list, help="process corners (default: manifest)")
    p.add_argument("--temp", type=csv_floats, help="temperatures in °C (default: manifest)")
    p.add_argument("--supply", type=csv_floats, help="supply voltages (default: manifest)")
    p.add_argument("--quick", action="store_true", help="run the manifest's quick_subset only")
    p.add_argument(
        "--subset-reason",
        default="",
        help="why a subset of the full PVT matrix is acceptable (required for subsets)",
    )
    p.add_argument("--supersedes", default="", help="record id this run supersedes")
    p.add_argument("--author", default="", help="record author (default: git user.email)")
    p.add_argument("--timeout", type=int, default=300, help="per-corner simulation timeout (s)")
    p.add_argument(
        "--allow-pdk-mismatch",
        action="store_true",
        help="run even if the installed PDK differs from the sim/pdk.json pin",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="netlist and print the corner list and the klt sim request(s) it would run; write "
        "nothing under sim/ and submit nothing",
    )
    p.add_argument(
        "--backend",
        choices=("auto", "batch", "local"),
        default="auto",
        help="auto (default): a full or multi-point matrix is ONE `klt sim --backend batch` "
        "request per sweep on the fleet; a single selected point and --quick run through "
        "`klt sim --backend local`. batch: force the fleet. local: single point or --quick "
        "only -- a local grid is refused before anything launches. A failed submit is an "
        "error, never a local fallback",
    )
    p.add_argument(
        "--wait-for-capacity",
        type=float,
        default=600.0,
        help="batch backend: seconds the submit may wait out fleet capacity and "
        "concurrency-cap refusals -- sets request batch.capacity_wait_s; 0 disables. "
        "Default 600 (host batch-submit rules)",
    )
    return p.parse_args(argv)


def resolve_backend(args: argparse.Namespace, matrix: list[Corner]) -> str:
    """Pick `batch` or `local` for this selection; refuse a local grid up front.

    Full or multi-point matrices go to the fleet; a single point and --quick (an
    explicit short point list) run through `klt sim --backend local`. Nothing has
    been netlisted or launched when this raises.
    """
    if args.quick:
        if args.backend == "batch":
            print("corner-run: --quick is a local liveness subset; keeping it on the local backend")
        return "local"
    if args.backend == "local" and len(matrix) > 1:
        raise HarnessError(
            f"--backend local refuses a {len(matrix)}-point grid: local runs are for a single "
            "point or --quick. Run the grid on the fleet instead (--backend batch, or leave "
            "--backend at its default), or select one point with --process/--temp/--supply"
        )
    if args.backend == "auto":
        return "local" if len(matrix) == 1 else "batch"
    return args.backend


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    pin = load_pin()
    pdk = resolve_pdk(pin)

    if args.print_env:
        # Fail closed: pdk-env.sh evals this output, so a tree that is not the
        # pinned revision must never reach the environment. No override here.
        if not pdk.matches_pin:
            raise HarnessError(pdk_mismatch_message(pdk, pin))
        print_env(pdk)
        return 0

    if not args.experiment:
        raise HarnessError("give an experiment directory, e.g. sim/pdk-smoke (or --print-env)")

    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise HarnessError(
            pdk_mismatch_message(pdk, pin)
            + "\n  or re-run with --allow-pdk-mismatch (the record will say so)"
        )

    exp = load_experiment(Path(args.experiment))
    matrix, is_subset = build_matrix(exp, args, pin)
    if not matrix:
        raise HarnessError("empty corner matrix")
    if is_subset and not args.subset_reason:
        raise HarnessError(
            "this run is a subset of the full PVT matrix; pass --subset-reason "
            '"..." so the record states why (CLAUDE.md: PVT corners on every '
            "recorded result)"
        )

    backend = resolve_backend(args, matrix)

    git_info = git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = exp.dir / "records"
    snapshots_dir = exp.dir / "netlist-snapshots"
    # New runs stage raw logs in git-ignored scratch and store them in the
    # fleet artifact store; only the manifest + summary are committed.
    corners_dir = evidence_store.stage_dir_for(exp.slug, record_id)
    art_manifest = evidence_store.manifest_path(exp.slug, record_id)
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"

    sim_common.refuse_existing(
        (record_md, record_json, snapshot, corners_dir, art_manifest)
    )

    if not args.dry_run:
        # Fail closed before simulating: no broker/klt means no run, no fallback.
        try:
            evidence_store.preflight()
        except evidence_store.StoreError as err:
            raise HarnessError(str(err))

    run_dir = BUILD_DIR / exp.slug / record_id
    run_dir.mkdir(parents=True, exist_ok=True)

    netlist = netlist_with_klt(exp.schematic, run_dir, pdk)
    body = netlist_body(netlist)

    print(f"experiment      : {exp.slug}")
    print(f"record id       : {record_id}")
    print(f"PDK             : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"testbench       : {exp.schematic.relative_to(REPO_ROOT)}")
    print(f"corner points   : {len(matrix)}" + (" (SUBSET)" if is_subset else " (full matrix)"))
    print(f"scratch run dir : {run_dir}")

    units = sweep_units(exp)
    sim_netlist = build_batch_netlist(exp, body, matrix)
    # Local runs are one request per point (a --quick list is not a grid); the fleet
    # takes the whole grid as one request per sweep.
    groups = [[c] for c in matrix] if backend == "local" else [matrix]
    plan = []  # (unit, group, subdir, request)
    for unit in units:
        for group in groups:
            tag = "-".join(t for t in (unit.name, group[0].id if backend == "local" else "") if t)
            subdir = f"{backend}-{tag}" if tag else backend
            plan.append(
                (unit, group, subdir,
                 build_batch_request(exp, pdk, group, args.timeout, args.wait_for_capacity, unit, backend))
            )
    if args.dry_run:
        print(f"\n-- klt sim request(s) ({len(plan)}; backend {backend}) --")
        for unit, group, subdir, request in plan:
            print(f"# {subdir}: {len(group)} corner(s), analysis {unit.analysis!r}")
            print(json.dumps(request, indent=2))
        print("\n-- corner list --")
        for corner in matrix:
            print(f"  {corner.id}")
        print("\n(dry run: nothing submitted, nothing written under sim/<experiment>/)")
        return 0

    fleet = None
    reports: dict[str, dict] = {}  # unit name -> merged report
    for unit, group, subdir, request in plan:
        if backend == "batch":
            report, fleet_info = submit_batch(exp, group, sim_netlist, request, run_dir, subdir)
            if fleet is None:
                fleet = fleet_info
                fleet["batch"]["submissions"] = []
            b = fleet_info["batch"]
            fleet["batch"]["submissions"].append(
                {
                    "request": subdir,
                    "job_id": b["job_id"],
                    "status": b["status"],
                    "runner_klt": b["runner_klt"],
                    "fleet_pdk_version": b["fleet_pdk_version"],
                }
            )
        else:
            report = run_local(exp, pdk, group[0], sim_netlist, request, run_dir, subdir)
        merged = reports.setdefault(unit.name, {"corners": []})
        merged["corners"] += report.get("corners", [])
    results = results_from_reports(
        exp, matrix, [(u, reports[u.name]) for u in units], corners_dir, args.timeout
    )
    for i, res in enumerate(results, start=1):
        write_batch_corner_log(res, corners_dir / f"{res['corner_id']}.log")
        summary = ", ".join(
            f"{c['name']}={'n/a' if c['value'] is None else format(c['value'], '.6g')}"
            for c in res["measurements"]
        )
        print(
            f"[{i:>3}/{len(matrix)}] {res['corner_id']:<20} "
            f"{'PASS' if res['pass'] else 'FAIL'}  {summary}"
        )
    for _, _, subdir, _ in plan:
        for name in ("netlist.spice", "request.json", "report.json", "klt.stderr"):
            src = run_dir / subdir / name
            if src.is_file():
                dst = corners_dir / subdir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(sim_common.scrub(src.read_text(), run_dir, REPO_ROOT))

    spreads = spread_checks(exp, results)
    overall = all(r["pass"] for r in results) and all(s["pass"] for s in spreads)

    # Store the raw logs first; on failure nothing is written under sim/<exp>/
    # or manifests/ and the staged bytes stay in the scratch dir for a retry.
    try:
        art_manifest, art_summary = evidence_store.store_run(exp.slug, record_id, corners_dir)
    except evidence_store.StoreError as err:
        raise HarnessError(f"evidence not stored, nothing committed: {err}")

    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(body) + "\n.end\n")

    pdk_record = {
        "root": str(pdk.root),
        "variant": pdk.variant,
        "installed_commit": pdk.installed_commit,
        "pinned_commit": pin["open_pdks_commit"],
        "matches_pin": pdk.matches_pin,
        "lib_file": str(pdk.lib_file),
    }
    tools = tool_versions()
    if fleet is not None:
        # The fleet, not this host, ran the simulator: the record must cite the
        # PDK and engine the fleet reports (the pin is checked against that).
        pdk_record.update(fleet["pdk"])
        pdk_record.update(
            fleet_pdk_block(pdk_record["installed_commit"], pdk.installed_commit, pin))
        tools["ngspice"] = fleet["ngspice"]

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or default_author(),
        "supersedes": args.supersedes,
        "experiment": {
            "slug": exp.slug,
            "title": exp.raw.get("title", exp.slug),
            "claim": exp.raw["claim"],
            "provenance": exp.raw.get("provenance", "schematic"),
            "provenance_source": exp.raw.get(
                "provenance_source", str(exp.schematic.relative_to(REPO_ROOT))
            ),
            "statistical_convention": exp.raw.get("statistical_convention", "N/A"),
        },
        "pdk": pdk_record,
        "tools": tools,
        "git": git_info,
        "matrix": {
            "process": unique_in_order(c.process for c in matrix),
            "temperature_c": sorted({c.temp_c for c in matrix}),
            "supply_v": sorted({c.supply_v for c in matrix}),
            "n_points": len(matrix),
            "is_subset": is_subset,
            "subset_reason": args.subset_reason,
            "points": [[c.process, c.temp_c, c.supply_v] for c in matrix],
            "point_ids": [c.id for c in matrix],
        },
        "corners": results,
        "spread_checks": spreads,
        "overall_pass": overall,
        "links": {
            "testbench": str(exp.schematic.relative_to(REPO_ROOT)),
            "manifest": str((exp.dir / "experiment.json").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)),
            "artifact_summary": str(art_summary.relative_to(REPO_ROOT)),
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    record["backend"] = backend
    if fleet is not None:
        record["batch"] = fleet["batch"]
    else:
        record["local"] = {"klt_client": sim_common.klt_version()}
    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {art_manifest.relative_to(REPO_ROOT)} (artifact store)")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    if fleet is not None and pdk_record["fleet_matches_pin"] != "match":
        # Both non-match states keep the nonzero exit -- an unstamped fleet run is
        # unverifiable, and honest wording must not quietly weaken the gate -- but they
        # are different findings and the warning says which one happened (issue #333).
        if pdk_record["fleet_matches_pin"] == "not-reported":
            print(
                "corner-run: WARNING: the fleet runner reported no open_pdks commit, so its "
                f"PDK cannot be compared with the sim/pdk.json pin {pin['open_pdks_commit']}; "
                "the record says NOT COMPARED, not MISMATCH.",
                file=sys.stderr,
            )
        else:
            print(
                f"corner-run: WARNING: the fleet runner's PDK is {pdk_record['installed_commit']}, "
                f"but sim/pdk.json pins {pin['open_pdks_commit']}; the record says MISMATCH.",
                file=sys.stderr,
            )
        if not args.allow_pdk_mismatch:
            print("  re-run with --allow-pdk-mismatch to accept this as exit 0", file=sys.stderr)
            return 3
    return 0 if overall else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except HarnessError as err:
        print(f"corner-run: error: {err}", file=sys.stderr)
        sys.exit(1)
