#!/usr/bin/env python3
"""PVT corner runner for sky130-temp-por.

Netlists an xschem testbench, sweeps a process/voltage/temperature matrix
through ngspice against the pinned sky130 PDK, and writes an append-only
evidence record under sim/<experiment-slug>/. See sim/README.md for the
record format and the rules the runner enforces.

Ported byte-for-byte (module docstring, tool-name references aside) from
sky130-bandgap/sim/bin/corner-run.py (issue #17) -- the PDK resolution, corner
matrix, deck generation and record schema are PDK/repo-generic, not specific
to that repo's own bandgap circuit.

Usage
-----
    sim/bin/corner-run.py sim/bias-core-smoke                # full PVT matrix
    sim/bin/corner-run.py sim/bias-core-smoke --quick \\
        --subset-reason "harness liveness check"            # 3-point subset
    sim/bin/corner-run.py --print-env                       # PDK env exports
    sim/bin/corner-run.py sim/bias-core-smoke --backend batch   # whole grid -> fleet
    sim/bin/corner-run.py sim/bias-core-smoke --backend batch --dry-run  # print request

--backend batch submits the corner grid as ONE `klt sim --backend batch` request
(never per-corner calls) and records the fleet's own PDK stamp, engine and job
id. A failed submit is an error quoting klt verbatim; there is no local
fallback. --quick always stays on the local backend.

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
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# sim_common.py lives alongside this file (sim/bin/) so it resolves whether
# this module is run directly (Python auto-prepends the script's own
# directory to sys.path) or loaded via sim_common.load_corner_run()'s
# importlib shim (whose only caller already put sim/bin on sys.path before
# importing sim_common in the first place) -- issue #191.
import sim_common

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


def netlist_with_xschem(schematic: Path, out_dir: Path, pdk: Pdk) -> Path:
    if not shutil.which("xschem"):
        raise HarnessError("xschem not found on PATH; cannot netlist the testbench")
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk.root)
    env["PDK"] = pdk.variant
    cmd = [
        "xschem",
        "-n",  # netlist
        "-q",  # quit when done
        "-x",  # no X11 / no GUI
        "-s",  # spice netlist format
        "-o",
        str(out_dir),
        "--rcfile",
        str(XSCHEMRC_FILE),
        str(schematic),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=300, stdin=subprocess.DEVNULL
    )
    produced = out_dir / (schematic.stem + ".spice")
    if proc.returncode != 0 or not produced.is_file():
        raise HarnessError(
            "xschem netlisting failed\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  rc: {proc.returncode}\n"
            f"  stdout: {proc.stdout.strip()}\n"
            f"  stderr: {proc.stderr.strip()}"
        )
    return produced


def netlist_body(netlist: Path) -> list[str]:
    """Strip the trailing .end so the deck can wrap the netlist.

    Also rewrites the absolute path xschem stamps into its `** sch_path:`
    comment to a repo-relative one, so netlist snapshots are byte-comparable
    across machines and checkouts.
    """
    text = netlist.read_text().replace(str(REPO_ROOT) + os.sep, "")
    return [ln for ln in text.splitlines() if ln.strip().lower() != ".end"]


# --------------------------------------------------------------------------
# deck generation and simulation
# --------------------------------------------------------------------------


def build_deck(exp: Experiment, pdk: Pdk, corner: Corner, body: list[str]) -> str:
    deck = exp.raw.get("deck", {})
    head = [
        f"* {exp.slug} corner deck -- generated by sim/bin/corner-run.py, do not edit",
        f"* corner: {corner.id}",
        f".param vsup={corner.supply_v}",
    ]
    for name, value in (deck.get("params") or {}).items():
        head.append(f".param {name}={value}")
    for opt in deck.get("options") or []:
        head.append(f".option {opt}")
    head.append(f".temp {fmt_temp(corner.temp_c)}")
    head.append(f'.lib "{pdk.lib_file}" {corner.process}')

    control = [".control", "save all"]
    control += list(deck.get("analyses") or ["op"])
    for m in exp.measurements:
        control.append(f"let meas_{m.name} = {m.expr}")
    for m in exp.measurements:
        control.append(f"print meas_{m.name}")
    control += ["quit", ".endc", ".end", ""]

    return "\n".join(head + body + control)


MEAS_RE = re.compile(r"^meas_([A-Za-z0-9_]+)\s*=\s*(-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)")


def parse_measurements(log: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in log.splitlines():
        m = MEAS_RE.match(line.strip())
        if m:
            values[m.group(1)] = float(m.group(2))
    return values


def signal_name(signum: int) -> str:
    """POSIX name for a signal number, e.g. 9 -> 'SIGKILL'."""
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal {signum}"


def exit_note(rc: int, timed_out: bool, killed_by_signal: int | None) -> str:
    """One-line explanation of *why* a corner produced no measurement.

    The three failure modes are otherwise indistinguishable in the record: the
    harness's own timeout, a child killed by a signal from outside the harness
    (OOM killer, an operator, a session reaper), and a clean nonzero exit from
    ngspice itself. See issue #48.
    """
    if timed_out:
        return " (TIMEOUT — the harness killed ngspice after --timeout expired)"
    if killed_by_signal is not None:
        return (
            f" ({signal_name(killed_by_signal)} — ngspice was killed by a signal from"
            " OUTSIDE the harness; the harness did not time it out)"
        )
    return ""


def evaluate_measurements(exp: Experiment, values: dict[str, float]) -> tuple[list[dict], bool]:
    """Grade measured values against the manifest's min/max windows.

    Shared by the local ngspice path and the batch path so both apply the
    same pass/fail rules and emit the same per-measurement check schema.
    """
    checks = []
    ok = True
    for m in exp.measurements:
        value = values.get(m.name)
        passed = value is not None
        reason = "" if passed else "measurement not found in ngspice output"
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


def run_corner(
    exp: Experiment,
    pdk: Pdk,
    corner: Corner,
    body: list[str],
    run_dir: Path,
    log_path: Path,
    timeout: int,
) -> dict:
    deck_text = build_deck(exp, pdk, corner, body)
    deck_path = run_dir / f"{corner.id}.deck.spice"
    deck_path.write_text(deck_text)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["ngspice", "-b", deck_path.name],
            cwd=run_dir,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        rc = -1
        timed_out = True
    elapsed_s = time.monotonic() - started

    # subprocess reports a signal-killed child as a NEGATIVE return code. The
    # harness's own timeout path above is the only place that sets rc = -1, so
    # any other negative rc means something outside the harness killed ngspice.
    killed_by_signal = None if timed_out else (-rc if rc < 0 else None)

    values = parse_measurements(stdout + "\n" + stderr)
    checks, ok = evaluate_measurements(exp, values)
    ok = ok and rc == 0 and not timed_out

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                f"# corner: {corner.id}",
                f"# process={corner.process} temp={fmt_temp(corner.temp_c)}C "
                f"supply={corner.supply_v:.2f}V",
                f"# ngspice exit: {rc}{exit_note(rc, timed_out, killed_by_signal)}",
                f"# wall clock: {elapsed_s:.1f}s (--timeout was {timeout}s)",
                f"# result: {'PASS' if ok else 'FAIL'}",
                "",
                "# ==== deck (exact input given to ngspice) ====",
                *[f"| {ln}" for ln in deck_text.splitlines()],
                "",
                "# ==== ngspice stdout ====",
                stdout.rstrip(),
                "",
                "# ==== ngspice stderr ====",
                stderr.rstrip(),
                "",
            ]
        )
    )

    return {
        "corner_id": corner.id,
        "process": corner.process,
        "temperature_c": corner.temp_c,
        "supply_v": corner.supply_v,
        "ngspice_exit": rc,
        "timed_out": timed_out,
        "killed_by_signal": killed_by_signal,
        "killed_by_signal_name": (
            signal_name(killed_by_signal) if killed_by_signal is not None else None
        ),
        "elapsed_s": round(elapsed_s, 3),
        "timeout_s": timeout,
        "measurements": checks,
        "pass": ok,
        "log": str(log_path.relative_to(REPO_ROOT)),
    }


# --------------------------------------------------------------------------
# batch backend (klt sim --backend batch)
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
        raise HarnessError("klt not found on PATH; the batch backend needs klayout-tools")
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
    """Netlist for the fleet: klt supplies .lib, .temp and the supply alter."""
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
    return "\n".join(head + body + [".end", ""])


def build_batch_request(exp: Experiment, pdk: Pdk, matrix: list[Corner], timeout: int) -> dict:
    deck = exp.raw.get("deck", {})
    analyses = list(deck.get("analyses") or ["op"])
    if len(analyses) != 1:
        raise HarnessError(
            f"{exp.slug}: the batch backend supports exactly one deck analysis, got {analyses}"
        )
    kind, _, args = analyses[0].strip().partition(" ")
    analysis = {"kind": kind.lower(), "args": args.strip()}
    process, temps, supplies = batch_axes(matrix)
    supply_source = deck.get("supply_source", "v1")
    return {
        "netlist": "netlist.spice",
        "backend": "batch",
        "models": {"pdk": pdk.variant, "lib": pdk.pin["ngspice_lib"]},
        "corners": {
            "process": process,
            "supply_v": {supply_source: supplies},
            "temperature_c": temps,
        },
        "analysis": analysis,
        "measurements": [
            {"name": m.name, "expr": m.expr, **({"unit": m.unit} if m.unit else {})}
            for m in exp.measurements
        ],
        "options": {"timeout_s": timeout, "keep_artifacts": True},
        "batch": {"runner_version_check": "warn"},
    }


def fleet_pdk_commit(version: str) -> str:
    """open_pdks commit out of the fleet's `provenance.pdk.version` string."""
    m = re.search(r"\b[0-9a-f]{40}\b", version or "")
    return m.group(0) if m else "unknown"


def _report_corner_key(c: dict) -> tuple:
    supply = c.get("supply_v")
    if isinstance(supply, dict):
        supply = next(iter(supply.values()), None)
    return (c.get("process"), float(c["temperature_c"]), float(supply))


def results_from_report(
    exp: Experiment, matrix: list[Corner], report: dict, corners_dir: Path, timeout: int
) -> list[dict]:
    """Map a klt report.json onto `run_corner`-shaped per-corner result dicts.

    Limits are graded here with `evaluate_measurements`, not by klt, so the
    batch and local paths share one pass/fail rule.
    """
    by_key = {}
    for c in report.get("corners", []):
        try:
            by_key[_report_corner_key(c)] = c
        except (KeyError, TypeError, ValueError):
            continue
    results = []
    for corner in matrix:
        rc = by_key.get((corner.process, corner.temp_c, corner.supply_v))
        values = {}
        status = "missing"
        runtime = 0.0
        if rc is not None:
            status = rc.get("status", "?")
            runtime = float(rc.get("runtime_s") or 0.0)
            values = {
                m["name"]: m["value"]
                for m in rc.get("measurements", [])
                if m.get("value") is not None
            }
        checks, ok = evaluate_measurements(exp, values)
        errored = rc is None or status in ("error", "errored")
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
                "batch_status": status,
                "diagnostics": (rc or {}).get("diagnostics", []),
            }
        )
    return results


def write_batch_corner_log(res: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# corner: {res['corner_id']}",
        f"# process={res['process']} temp={fmt_temp(res['temperature_c'])}C "
        f"supply={res['supply_v']:.2f}V",
        f"# klt sim --backend batch corner status: {res['batch_status']}",
        f"# result: {'PASS' if res['pass'] else 'FAIL'}",
        "",
    ]
    for d in res["diagnostics"]:
        lines.append(f"# diagnostic [{d.get('severity')}] {d.get('code')}: {d.get('message')}")
    log_path.write_text("\n".join(lines) + "\n")


def submit_batch(
    exp: Experiment, matrix: list[Corner], netlist: str, request: dict, run_dir: Path
) -> tuple[dict, dict]:
    """Submit the grid as one `klt sim --backend batch` request.

    Returns (report, fleet) where `fleet` carries what the fleet reported about
    itself. A submit that yields no usable report is a HarnessError quoting klt
    verbatim: there is no local fallback.
    """
    d = run_dir / "batch"
    outcome = sim_common.submit_prepared(
        d, netlist, request, f"{exp.slug}: {len(matrix)} points -> batch fleet", exp.slug
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
    # make an unverified fleet look pinned).
    runner_pdk = (remote.get("worker_environment") or {}).get("pdk") or {}
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
        if res["timed_out"]:
            fails.append(
                "ngspice TIMED OUT — the harness killed it after "
                f"--timeout {res.get('timeout_s', '?')}s"
            )
        elif res.get("killed_by_signal") is not None:
            fails.append(
                f"ngspice was KILLED BY {res['killed_by_signal_name']} "
                f"(exit {res['ngspice_exit']}) after {res.get('elapsed_s', '?')}s — a signal "
                "from OUTSIDE the harness, not a harness timeout; investigate the machine "
                "(OOM killer, session reaper, operator), not --timeout"
            )
        elif res["ngspice_exit"] != 0:
            fails.append(f"ngspice exit {res['ngspice_exit']} (clean nonzero exit, no signal)")
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

    lines.append("- **Links**:")
    lines.append(f"  - Testbench: `{r['links']['testbench']}`")
    lines.append(f"  - Netlist snapshot: `{r['links']['netlist_snapshot']}`")
    lines.append(f"  - Raw per-corner logs: `{r['links']['corners_dir']}`")
    lines.append(f"  - Machine-readable record: `{r['links']['json']}`")
    lines.append(f"  - Experiment manifest: `{r['links']['manifest']}`")
    lines.append(
        f"- **Timestamp / author**: {r['timestamp']}, {r['author']}"
    )
    lines.append(f"- **Supersedes**: {r['supersedes'] or '(none)'}")
    lines.append("")
    lines.append(
        "Written by `sim/bin/corner-run.py`. Append-only: never edit this file — "
        "a correction is a new record with a `Supersedes` field (see `sim/README.md`)."
    )
    lines.append("")
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
    p.add_argument("--timeout", type=int, default=300, help="per-corner ngspice timeout (s)")
    p.add_argument(
        "--allow-pdk-mismatch",
        action="store_true",
        help="run even if the installed PDK differs from the sim/pdk.json pin",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="netlist and print the corner list and one deck (with --backend batch: the "
        "klt sim request instead), write nothing under sim/ and submit nothing",
    )
    p.add_argument(
        "--backend",
        choices=("local", "batch"),
        default="local",
        help="local: serial ngspice on this host (default; single points and --quick). "
        "batch: submit the whole grid as one `klt sim --backend batch` request to the "
        "fleet; a failed submit is an error, never a local fallback",
    )
    return p.parse_args(argv)


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

    backend = args.backend
    if backend == "batch" and args.quick:
        print("corner-run: --quick is a local liveness subset; keeping it on the local backend")
        backend = "local"

    git_info = git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = exp.dir / "records"
    snapshots_dir = exp.dir / "netlist-snapshots"
    corners_dir = exp.dir / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"

    for path in (record_md, record_json, snapshot, corners_dir):
        if path.exists():
            raise HarnessError(
                f"{path} already exists — sim/ is append-only, refusing to overwrite"
            )

    run_dir = BUILD_DIR / exp.slug / record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SPICEINIT_FILE, run_dir / ".spiceinit")

    if backend == "batch":
        netlist = netlist_with_klt(exp.schematic, run_dir, pdk)
    else:
        netlist = netlist_with_xschem(exp.schematic, run_dir, pdk)
    body = netlist_body(netlist)

    print(f"experiment      : {exp.slug}")
    print(f"record id       : {record_id}")
    print(f"PDK             : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"testbench       : {exp.schematic.relative_to(REPO_ROOT)}")
    print(f"corner points   : {len(matrix)}" + (" (SUBSET)" if is_subset else " (full matrix)"))
    print(f"scratch run dir : {run_dir}")

    fleet = None
    if backend == "batch":
        request = build_batch_request(exp, pdk, matrix, args.timeout)
        batch_netlist = build_batch_netlist(exp, body, matrix)
        if args.dry_run:
            print(f"\n-- klt sim request ({len(matrix)} corners, one grid) --")
            print(json.dumps(request, indent=2))
            print("\n-- corner list --")
            for corner in matrix:
                print(f"  {corner.id}")
            print("\n(dry run: nothing submitted, nothing written under sim/<experiment>/)")
            return 0
        report, fleet = submit_batch(exp, matrix, batch_netlist, request, run_dir)
        results = results_from_report(exp, matrix, report, corners_dir, args.timeout)
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
        for name in ("netlist.spice", "request.json", "report.json", "klt.stderr"):
            src = run_dir / "batch" / name
            if src.is_file():
                dst = corners_dir / "batch" / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(sim_common.scrub(src.read_text(), run_dir, REPO_ROOT))
    elif args.dry_run:
        print("\n-- corner list --")
        for corner in matrix:
            print(f"  {corner.id}")
        print(f"\n-- deck for {matrix[0].id} --")
        print(build_deck(exp, pdk, matrix[0], body))
        print("\n(dry run: nothing written under sim/<experiment>/)")
        return 0
    else:
        results = []
        for i, corner in enumerate(matrix, start=1):
            log_path = corners_dir / f"{corner.id}.log"
            res = run_corner(exp, pdk, corner, body, run_dir, log_path, args.timeout)
            results.append(res)
            summary = ", ".join(
                f"{c['name']}={'n/a' if c['value'] is None else format(c['value'], '.6g')}"
                for c in res["measurements"]
            )
            print(
                f"[{i:>3}/{len(matrix)}] {corner.id:<20} "
                f"{'PASS' if res['pass'] else 'FAIL'}  {summary}"
            )

    spreads = spread_checks(exp, results)
    overall = all(r["pass"] for r in results) and all(s["pass"] for s in spreads)

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
        pdk_record["local_installed_commit"] = pdk.installed_commit
        pdk_record["matches_pin"] = pdk_record["installed_commit"] == pin["open_pdks_commit"]
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
            "corners_dir": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    if fleet is not None:
        record["backend"] = "batch"
        record["batch"] = fleet["batch"]
    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {corners_dir.relative_to(REPO_ROOT)}/")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    if fleet is not None and not pdk_record["matches_pin"]:
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
