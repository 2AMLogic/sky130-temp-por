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
                          normally); one copy per process, like `import`
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
    open_run()/fan_out()/refuse_unsubmittable()
                          the campaign submit bootstrap every fleet
                          `cmd_run` opens with: the run id + run-directory
                          rule, the bounded submit pool, and the
                          submit-time clean-tree guard
    load_request_report()/fleet_job_fields()
                          the per-request report triage every campaign
                          grader runs before its corner loop: one gradeable
                          report or one scrubbed reason it cannot be graded,
                          then the one `environment.remote` field list a
                          request record carries (issue #322)
    record_pdk_tools()      the record's `pdk` + `tools` provenance dicts,
                          every tool version derived from what actually ran
                          rather than hand-copied, plus the pieces it is
                          built from -- fleet_ngspice() (the one klt-log
                          banner regex), joined_versions(),
                          host_tool_versions()/host_ngspice_tag()
    runner_pdk()/fleet_pdk_fields()/fleet_pdk_clause()
                          the one reader of the PDK the fleet runner
                          actually ran under (`environment.remote.
                          worker_environment.pdk`, never the client-resolved
                          `provenance.pdk`), the `pdk.fleet_pdk*` fields a
                          record states it in, and the one sentence that
                          states it in prose (issue #328)
    fleet_pdk_commit()/fleet_pin_verdict()/fleet_pin_state()/PIN_COMMIT_LIMIT
                          the fleet half of the pin check (issue #333): the
                          one open_pdks-commit parser (moved here from
                          `corner-run.py`), the THREE-state
                          `match`/`mismatch`/`not-reported` verdict over a
                          set of runner stamps, its rendered phrase, and the
                          one sentence stating what an equal commit does not
                          establish
    pin_state()             the `sim/pdk.json` pin-state ternary every
                          record's `PDK` line carries
"""

from __future__ import annotations

import argparse
import concurrent.futures
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
from datetime import datetime, timezone
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

    One copy per process: an already-registered `sys.modules["corner_run"]` is
    returned as-is, so every caller resolves against the same `Pdk`,
    `HarnessError` etc. A second exec would give a second set of classes that
    the rest of the harness does not match (issue #304); `import` gives that
    guarantee for free and this shim has to supply it itself.

    Registers the loaded module in `sys.modules` under its spec name
    ("corner_run") *before* `exec_module` runs -- required because
    `@dataclass`-decorated classes inside corner-run.py resolve type
    annotations through `sys.modules[cls.__module__]`, which fails on an
    unregistered module. A failed exec un-registers the half-built module so
    the next call retries a fresh load rather than handing back a broken one.
    """
    loaded = sys.modules.get("corner_run")
    if loaded is not None:
        return loaded
    path = BIN_DIR / "corner-run.py"
    spec = importlib.util.spec_from_file_location("corner_run", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def corner_id(proc: str, temp: float, vf: float) -> str:
    """Record/run-directory key for one (process, temperature, supply) corner, e.g. tt_27c_1.80v."""
    return f"{proc}_{load_corner_run().fmt_temp(temp)}c_{vf:.2f}v"


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


def selftest_record_id(now, sha: str) -> str:
    """Record id of a checker self-test record (`<date>-<time>-<sha>-checker-selftest`)."""
    return f"{now:%Y%m%d}-{now:%H%M%S}-{sha}-checker-selftest"


def selftest_footer_lines(doc: dict, ok: bool, script: str) -> list[str]:
    """Closing lines shared by every self-test record's markdown: verdict, timestamp/author, supersedes."""
    return ["", f"**Overall: {'PASS' if ok else 'FAIL'}**", "", f"- **Timestamp / author**: {doc['timestamp']}, {doc['author']}",
            f"- **Supersedes**: {doc['supersedes'] or '(none)'}", "", f"Written by `{script}`. Append-only.", ""]


def write_selftest_record(rec_dir: Path, record_id: str, doc: dict, md_lines: list[str]) -> None:
    """Write a self-test record's `.json` + `.md`, refusing to touch an existing record (records/ is append-only)."""
    rec_dir.mkdir(exist_ok=True)
    for ext in (".md", ".json"):
        if (rec_dir / f"{record_id}{ext}").exists():
            raise SystemExit("record exists -- append-only")
    (rec_dir / f"{record_id}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    (rec_dir / f"{record_id}.md").write_text("\n".join(md_lines))


def write_wave_fixture(path: Path, doc: dict) -> None:
    """Write a synthetic-waveform fixture as compact gzipped JSON.  mtime=0 keeps it byte-identical on every
    run, so a self-test never dirties the committed fixtures."""
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(json.dumps(doc, separators=(",", ":")).encode())


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


def pin_state(matches_pin: bool) -> str:
    """The `sim/pdk.json` pin-state ternary a record's `PDK` line carries.

    One definition: the renderer below, `run_solver_sweep.py` and `run_accuracy_mc.py`
    each wrote this conditional out in full, so the wording a reader greps for
    (`**MISMATCH vs sim/pdk.json pin**`) lived in three places at once (issue #328).
    """
    return "matches sim/pdk.json pin" if matches_pin else "**MISMATCH vs sim/pdk.json pin**"


def fleet_pin_state(verdict: str) -> str:
    """`pin_state()`'s three-state sibling, for the FLEET runners' stamp (issue #333).

    `pin_state()` takes a bool because the host's own install always has a commit to
    compare.  A fleet runner may report no commit at all, and "unverifiable" is not
    "wrong": collapsing it onto the mismatch branch is the conflation #306/#312/#328
    exist to prevent, and was live in `corner-run.py`'s batch path, which rendered an
    unreported stamp as `**MISMATCH vs sim/pdk.json pin**`.

    Shares `pin_state()`'s match/mismatch wording on purpose -- `**MISMATCH vs
    sim/pdk.json pin**` is the string a reader greps a record for -- and the
    not-reported branch deliberately contains neither "matches" nor "MISMATCH".
    """
    if verdict == "match":
        return "matches sim/pdk.json pin"
    if verdict == "mismatch":
        return "**MISMATCH vs sim/pdk.json pin**"
    if verdict == "not-reported":
        return "no open_pdks commit reported, so not compared with sim/pdk.json pin"
    raise ValueError(f"not a fleet pin verdict: {verdict!r}")


def render_pdk_tools_repo_state(r: dict) -> list[str]:
    """`PDK` (pin-state ternary) + `Tools` + `Repo state` (dirty-tree
    ternary) lines shared verbatim across every experiment's
    `render_record()`."""
    pdk = r["pdk"]
    tools = r["tools"]
    # `local_installed_commit` exists for exactly one reason: on a batch record
    # `corner-run.py` substitutes the FLEET runner's commit into `installed_commit` and
    # parks this host's under that key.  So when it is present this line's pin state is
    # the fleet verdict, which is three-state -- an unreported runner stamp must not
    # render as a mismatch (issue #333).  Campaign-runner records carry
    # `fleet_matches_pin` too, but their `installed_commit` is the host's, so they
    # keep the host's bool here and state the fleet verdict in their own prose.
    verdict = pdk.get("fleet_matches_pin")
    state = (fleet_pin_state(verdict) if verdict and "local_installed_commit" in pdk
             else pin_state(pdk["matches_pin"]))
    return [
        f"- **PDK**: {pdk['variant']} @ open_pdks `{pdk['installed_commit']}` ({state}); "
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


def point_log(corner: dict, header: list[str], run_dir: Path, repo_root: Path) -> str:
    """One graded point's `.log` for a fleet corner: caller's `header`, the exact deck klt
    gave ngspice, klt's diagnostics, and the raw ngspice output.  Scrubbed (the committed
    copy must not carry build or home paths)."""
    art = corner.get("artifacts") or {}
    deck = Path(art["deck"]).read_text() if art.get("deck") and Path(art["deck"]).is_file() else "(no deck retrieved)"
    log = Path(art["log"]).read_text() if art.get("log") and Path(art["log"]).is_file() else "(no ngspice log retrieved)"
    lines = list(header) + [""]
    lines += ["# ==== klt sim deck (exact input given to ngspice on the runner) ====", *[f"| {ln}" for ln in deck.splitlines()], ""]
    lines += ["# ==== klt diagnostics ====", *[f"| {dg.get('severity')}/{dg.get('code')}: {dg.get('message')}" for dg in corner.get("diagnostics", [])], ""]
    lines += ["# ==== ngspice stdout+stderr ====", log.rstrip(), ""]
    return scrub("\n".join(lines), run_dir, repo_root)


def classify_error(corner: dict, log_text: str) -> str:
    """`error_class` for a corner that produced no usable result (display only, never a grade)."""
    if "could not find a valid modelname" in log_text:
        return "model_not_found"
    codes = [d.get("code") for d in corner.get("diagnostics", [])]
    if any(c and "timeout" in c for c in codes):
        return "timeout"
    return ("error:" + ",".join(sorted({c for c in codes if c}))) if codes else "error"


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


def open_run(build_dir: Path, run_id_arg: str | None, git_sha: str, *,
             reuse: str | None = None, sub: str | None = None,
             create: bool = True) -> tuple[str, Path, datetime]:
    """Open one campaign run: derive its id, apply the run-directory rule, return
    ``(run_id, run_dir, now)``.

    Every fleet campaign runner's ``cmd_run`` used to start with its own copy of this:
    a ``<timestamp>-<short sha>`` run id (overridable with ``--run-id``),
    ``<build_dir>/<run_id>`` as the run directory, and a rule about an existing
    directory.  ``reuse`` selects that rule:

    ``None``      a fresh run: refuse an existing directory (``sim/`` evidence is
                  append-only, and a reused id would mix two runs into one) and
                  create it.
    ``"require"`` ``--retry-failed``: the directory must already exist, because the
                  retry re-submits only the unusable requests of *that* run.
    ``"allow"``   ``--resume`` (and a ``--retry-failed`` that tolerates a first run):
                  create it when missing, accept it when present.

    ``sub`` nests the run directory one level below the run id (``run_accuracy_mc.py``'s
    ``--variant`` shares its baseline's run id).  ``create=False`` applies the rule but
    leaves the ``mkdir`` to the caller (``run_brownout_campaign.py`` creates the
    directory only once its request selection has been validated).
    """
    if reuse not in (None, "require", "allow"):
        raise ValueError(f"reuse must be None, 'require' or 'allow', not {reuse!r}")
    now = datetime.now(timezone.utc)
    run_id = run_id_arg or f"{now:%Y%m%d-%H%M%S}-{git_sha}"
    run_dir = (build_dir / run_id / sub) if sub else (build_dir / run_id)
    if reuse == "require":
        if not run_dir.exists():
            raise SystemExit(f"{run_dir} does not exist")
    else:
        if reuse is None and run_dir.exists():
            raise SystemExit(f"{run_dir} exists; refusing to reuse a run id")
        if create:
            run_dir.mkdir(parents=True, exist_ok=(reuse == "allow"))
    return run_id, run_dir, now


def fan_out(fn, units, jobs: int, *, label=None, tag: str | None = None) -> list[dict]:
    """Run ``fn(unit)`` over ``units`` in the shared bounded pool, results in ``units`` order.

    The pool is capped at 2 workers however large ``--jobs`` is -- these are fleet
    submits against a vCPU-budgeted fleet, not local simulations -- and a ``jobs``
    below 1 still gets one worker rather than a ``ThreadPoolExecutor`` ``ValueError``.
    An exception from ``fn`` becomes an ``{"error": repr(err)}`` entry plus an
    ``[error]`` log line: never swallowed, and never allowed to abandon the rest of the
    campaign, because a submit failure is evidence the record reports.

    ``label(unit)`` names a unit for the log line; with ``tag`` that name is also
    prefixed to each of the unit's results as ``{tag: name, ...}`` (a key the result
    itself carries wins, exactly as it did when the runners merged these by hand).
    """
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(2, jobs))) as ex:
        for unit, fut in [(u, ex.submit(fn, u)) for u in units]:
            name = label(unit) if label else None
            head = {tag: name} if tag else {}
            try:
                results.append({**head, **fut.result()})
            except Exception as err:  # noqa: BLE001 -- recorded, never swallowed
                results.append({**head, "error": repr(err)})
                say(f"[error] submit{'' if name is None else ' ' + name} raised: {err!r}")
    return results


MODEL_LIB = "libs.tech/combined/sky130.lib.spice"


def base_request(
    netlist: str,
    backend: str,
    corners: dict,
    analysis: dict,
    measurements: list[dict],
    timeout_s: int,
    capacity_wait_s: float = 0,
    waveforms: bool = True,
    monte_carlo: dict | None = None,
) -> dict:
    """Fleet request skeleton shared by every campaign driver: the sky130A `models` block, the
    `options` block and, on the batch backend, the `batch` block.  Key order is part of the
    contract (request.json is recorded evidence)."""
    req = {
        "netlist": netlist,
        "backend": backend,
        "models": {"pdk": "sky130A", "lib": MODEL_LIB},
        "corners": corners,
        "analysis": analysis,
        "measurements": measurements,
        "options": {"timeout_s": timeout_s, "keep_artifacts": True, **({"waveforms": True} if waveforms else {})},
    }
    if monte_carlo:
        req["monte_carlo"] = monte_carlo
    if backend == "batch":
        req["batch"] = {"runner_version_check": "warn"}
        if capacity_wait_s:
            req["batch"]["capacity_wait_s"] = capacity_wait_s
    return req


FLEET_NOTE = "client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used"
XSCHEM_NOTE = "only the testbench is netlisted by xschem here; the DUT is spliced from the committed design/netlist/temp_por_top.spice (host xschem leaves expr() parameters unevaluated)"


# --------------------------------------------------------------------------
# record provenance: the shared `pdk` / `tools` block (issue #297)
# --------------------------------------------------------------------------

RUNNER_LIB_FILE = MODEL_LIB + " (resolved on the runner as /opt/pdk/sky130A/...)"
HOST_PDK_ROOT = "<host $PDK_ROOT>"
HOST_NGSPICE_SUFFIX = " (host; the grid ran on the fleet)"

_FLEET_NGSPICE_RE = re.compile(r"(ngspice-\d+) done")


def fleet_ngspice(log_text: str) -> str | None:
    """The fleet runner's ngspice version as it announces itself in a per-corner klt log
    (`... ngspice-47 done ...`), or None when the log carries no such banner.

    Every fleet campaign runner reads its per-point `ngspice` field through this, so a
    record states the engine that actually ran instead of a literal that goes stale."""
    m = _FLEET_NGSPICE_RE.search(log_text)
    return m.group(1) if m else None


def joined_versions(items, key: str) -> str:
    """Sorted, comma-joined set of `item[key]` across `items`, or `"unknown"` when none
    carries one.  `items` may hold `None` entries (a request that never got a report)."""
    return ", ".join(sorted({v for it in items if (v := (it or {}).get(key))})) or "unknown"


def runner_pdk(src) -> dict:
    """The PDK install of the fleet machine that actually RAN a job, off its klt report.

    NOT `provenance.pdk`: that is the PDK the *client* resolved, while the runner executes
    against its own `/opt/pdk`, stamped under `environment.remote.worker_environment.pdk`.
    The two genuinely diverge -- `sim/bias-core-smoke/records/20261023-171642-e69f5b2e.json`
    recorded a grid executed under open_pdks `c6d73a35...` while the client had merely
    resolved `f6eeac7d...` -- so citing the client's value makes an unverified fleet read
    as pinned, which is the stated-not-observed claim it exists to remove.

    `sim/bin/corner-run.py` settled which field is correct; issues #306 and #312 then
    repeated the walk as a private helper in two more runners, and three campaign runners
    stored the client's value under the key `fleet_pdk_report` anyway (visible in
    `sim/glitch-top/records/20261113-082829-da28d31-vdd_level-rerun181.json`, whose
    "fleet" PDK report names search roots on the SUBMITTING host).  This is the one
    reader, so "which field is the fleet's PDK?" is answered in one place (issue #328).

    Accepts a whole report, its `environment` section, or one `remote`-shaped section --
    which is also the shape of a per-process job in accuracy-MC's `ent['jobs']`.  Returns
    `{}` when any link in the chain is absent, so an unreported stamp becomes `unknown`
    via `joined_versions()` rather than falling back to the client's value.
    """
    d = src or {}
    d = d.get("environment") or d   # a whole klt report -> its environment section
    d = d.get("remote") or d        # an environment section -> its remote section
    return (d.get("worker_environment") or {}).get("pdk") or {}


def fleet_pdk_commit(version: str) -> str:
    """The open_pdks commit out of a PDK stamp string, or `"unknown"` when it carries none.

    One parser for the whole repo.  It lived in `corner-run.py`, the only runner that
    compared a runner stamp with the pin at all; issue #333 moved it here so the other
    seven runners inherit the comparison instead of each re-deriving it, which is the
    move issue #328 made for the *reader* (`runner_pdk()`).  `corner-run.py` imports
    `sim_common`, and `load_corner_run()` is a lazy importlib shim, so this is the one
    direction that creates no import cycle.
    """
    m = re.search(r"\b[0-9a-f]{40}\b", version or "")
    return m.group(0) if m else "unknown"


def fleet_pin_verdict(commits, pin: dict) -> str:
    """The THREE-state verdict of a set of fleet-runner commits against the pin:
    `"match"` / `"mismatch"` / `"not-reported"` (issue #333).

    `commits` is one `fleet_pdk_commit()` result per fleet job (any iterable; `None` and
    `"unknown"` both mean that job named no commit).

      * `"not-reported"` -- no job named a commit.  An absent stamp and a stamp that
        carries no 40-hex commit are the SAME answer: nothing to compare.  This is the
        branch that must never collapse into `"mismatch"`, and the reason this is a
        string and not a bool -- `corner-run.py` used a bool and so reported an
        unstamped fleet run as `**MISMATCH vs sim/pdk.json pin**` and exited 3.
      * `"match"` -- at least one job named a commit and every named commit equals
        `pin["open_pdks_commit"]`.
      * `"mismatch"` -- otherwise, which includes the MIXED case (some jobs on the pin,
        some not).  A grid is not on the pin because part of it was.

    Partial coverage is deliberately not a fourth state: `fleet_pdk_jobs` /
    `fleet_pdk_reporting` already carry it, so this is a verdict over the jobs that
    ANSWERED, never over the whole grid.  `"match"` from 2 of 5 reporting jobs says "the
    jobs that reported ran the pin", not "the grid ran the pin"; render the coverage
    beside it.  Note the denominators differ on purpose: `fleet_pdk_reporting` counts
    jobs with a *stamp*, this counts jobs with a parseable *commit*, so a malformed
    stamp is reported-but-not-comparable rather than silently wrong.

    See `PIN_COMMIT_LIMIT` for what a `"match"` does not establish.
    """
    named = [c for c in commits if c and c != "unknown"]
    if not named:
        return "not-reported"
    return "match" if all(c == pin["open_pdks_commit"] for c in named) else "mismatch"


def fleet_pdk_fields(pdks, pin: dict) -> dict:
    """The fleet half of a record's `pdk` block: what the runners reported, how many, and
    how that compares with the `sim/pdk.json` pin.

    `pdks` is one `runner_pdk()` result per fleet job the record covers (any iterable;
    `None` for a request that never reached the fleet, which is NOT counted as a job --
    only a job that ran and reported no stamp belongs in the denominator).

    `fleet_pdk` is the sorted SET of observed stamps, `unknown` when no job reported one;
    `fleet_pdk_jobs` / `fleet_pdk_reporting` are its coverage, so a value joined over the
    jobs that answered cannot be rendered as one they all agreed on.  Named for the
    `pdk.fleet_pdk*` keys `run_accuracy_mc.py` already writes -- deliberately NOT the old
    `fleet_pdk_report`, whose recorded contents are the client's resolution, so a reader
    comparing an old record with a new one sees the key change with the meaning.

    `fleet_matches_pin` is `fleet_pin_verdict()`'s three-state string (issue #333): until
    then every record *stated* the runners' stamp and no record *compared* it, so "the
    fleet ran under the pinned PDK" was an assumption disclosed in prose with
    local-vs-fleet engine agreement as its only indirect evidence.  `pin` is required,
    not optional, so a runner cannot keep writing the uncompared shape by omission.
    """
    observed = [p for p in pdks if p is not None]
    return {"fleet_pdk": joined_versions(observed, "stamp_text"),
            "fleet_pdk_jobs": len(observed),
            "fleet_pdk_reporting": sum(1 for p in observed if p.get("stamp_text")),
            "fleet_matches_pin": fleet_pin_verdict(
                (fleet_pdk_commit(p.get("stamp_text")) for p in observed), pin)}


def fleet_pdk_clause(fleet_pdk: str, verdict: str) -> str:
    """One sentence-initial clause stating what the fleet runners reported about their PDK
    **and how it compares with the pin**.

    Four record texts used to state "the fleet PDK commit is not reported by the runner"
    as a literal.  The runners do report it, so the claim went stale into append-only
    records that can no longer be corrected (issue #328).  Those four then said, still
    weakly, that the stamp is recorded and *not compared* with the pin -- also a literal,
    and also false once the comparison exists (issue #333).  Both halves are derived
    here: `fleet_pdk_fields()`'s `fleet_pdk` and its `fleet_matches_pin`.

    `verdict` is required for the same reason `pin` is required above: a caller that
    renders only the stamp is a caller that silently keeps the uncompared claim.
    """
    if fleet_pdk == "unknown":
        got = "The fleet runners that executed the grid reported no PDK stamp"
    else:
        got = f"The fleet runners that executed the grid reported PDK `{fleet_pdk}`"
    # One parenthetical form for all three states.  `pin_state()`'s wording is a noun
    # fragment ("**MISMATCH vs sim/pdk.json pin**"), not a predicate, so splicing it in
    # after "which" is ungrammatical -- and a parenthetical is what every record's PDK
    # header line already uses.  `not-reported` is reached two ways (no stamp at all, and
    # a stamp carrying no 40-hex commit); both name whatever was reported and then decline
    # to compare it, which is NOT the mismatch branch.
    return f"{got} (verdict: {fleet_pin_state(verdict)})"


PIN_COMMIT_LIMIT = (
    "an equal open_pdks commit is not proof that the runner's model library is "
    "byte-identical to this host's -- it identifies the open_pdks build, not a hash of "
    "the `sky130.lib.spice` the runner loaded, and the only model-library hash a klt "
    "report carries (`environment.models_lib_sha256`) is client-scope "
    "(`models_lib_sha256_scope: \"client\"`), taken on the submitting host, so it is not "
    "fleet-side evidence about the runner's library"
)
"""What a `"match"` from `fleet_pin_verdict()` does NOT establish (issue #333).

Issue #333 asked whether `environment.models_lib_sha256` is the stronger check.  It is
not: every klt report in this tree carries `models_lib_sha256_scope: "client"`, and
`sim/bias-core-smoke/records/20261023-171642-e69f5b2e.json` shows a client-scope hash
sitting beside a *runner* that ran a different open_pdks commit than the client resolved.

klt does have the comparison -- `environment.remote.models_lib_comparison`, from
klayout-tools #5321 -- and on every batch report in this tree it answers
`{"status": "not_comparable", "reason": "runner_hash_unavailable"}`, because its input
(the runner inner report's own `models_lib_sha256`) is absent.  Most of this repo's
requests declare no `models.lib` at all (they select corners per section), which is the
structural case already filed and open as **klayout-tools #5457**; that issue is the
friction-protocol record for this gap, so do not file it again.  The commit comparison
above is the strongest fleet-side PDK claim available until it closes.

The runner does report a runner-scope hash -- `worker_environment.pdk.stamp_sha256` with
`stamp_scope: "executed"` -- but `stamp_scheme: "sources-sha256"` makes it a hash of the
open_pdks sources, not of the `sky130.lib.spice` the simulator loaded, so it answers the
same question as the commit rather than a stronger one.
"""


@functools.lru_cache(maxsize=1)
def host_tool_versions() -> dict:
    """`corner-run.tool_versions()` read once per process -- each call shells out to
    `ngspice -v` and `xschem --version`, and a record needs the same answer throughout."""
    return load_corner_run().tool_versions()


def host_ngspice_tag() -> str:
    """Just the `ngspice-NN` token of the host's own ngspice, for a local-probe-vs-fleet
    cross-check sentence; `"unknown"` when the banner carries no version."""
    m = re.search(r"ngspice-\d+", host_tool_versions()["ngspice"])
    return m.group(0) if m else "unknown"


def record_pdk_tools(
    pdk,
    pin: dict,
    meta: dict,
    points=(),
    requests=(),
    *,
    lib_file: str | None = RUNNER_LIB_FILE,
    root: str | None = HOST_PDK_ROOT,
    host_tools: bool = True,
    fleet_note: str | None = FLEET_NOTE,
    xschem_note: str | None = XSCHEM_NOTE,
    ngspice_key: str = "ngspice",
    runner_key: str = "runner_klt_version",
) -> tuple[dict, dict]:
    """Build a record's `pdk` and `tools` provenance dicts.

    Every tool version here is *observed*, never a literal: the fleet's ngspice from the
    per-point banners the runners pull out of each corner's klt log (`fleet_ngspice()`),
    the fleet runner's klt from each request's `runner_klt_version`, the host's from
    `corner-run.tool_versions()`.  A hand-copied constant in one of these fields is how a
    record ends up reporting a tool nobody ran (issue #297).

    `points` / `requests` are the record's own lists (any iterable of dicts, `None`
    entries tolerated); pass `ngspice_key` / `runner_key` when a runner names those
    fields differently.  Pass `None` for `lib_file`, `root`, `fleet_note` or
    `xschem_note` to leave that key out, and `host_tools=False` for a runner that never
    invokes ngspice or xschem itself.  Runner-specific extras (`fleet_klu_points`,
    `klt_sim_backend_env`, ...) are added by the caller on top of the returned dicts --
    including the fleet half of the `pdk` block, which every caller adds from the one
    shared `fleet_pdk_fields()` below rather than reading a report itself (issue #328).
    """
    pdk_d = {
        "variant": pdk.variant,
        "installed_commit": pdk.installed_commit,
        "pinned_commit": pin["open_pdks_commit"],
        "matches_pin": pdk.matches_pin,
    }
    if root is not None:
        pdk_d["root"] = root
    if lib_file is not None:
        pdk_d["lib_file"] = lib_file

    tv = host_tool_versions()
    tools_d = {"platform": tv["platform"], "python": tv["python"], "klt_client": meta.get("klt_client")}
    if host_tools:
        tools_d["ngspice"] = tv["ngspice"] + HOST_NGSPICE_SUFFIX
        tools_d["xschem"] = tv["xschem"]
    tools_d["fleet_runner_klt"] = joined_versions(requests, runner_key)
    tools_d["fleet_ngspice"] = joined_versions(points, ngspice_key)
    if fleet_note is not None:
        tools_d["fleet_note"] = fleet_note
    if xschem_note is not None:
        tools_d["xschem_note"] = xschem_note
    return pdk_d, tools_d


def deck_drift(repo_root: Path, deck_inputs, run_sha: str | None, grade_sha: str | None) -> list[str] | None:
    """Deck-affecting paths changed between the submit and grading commits (None = not determinable)."""
    if not run_sha or not grade_sha:
        return None
    p = subprocess.run(["git", "-C", str(repo_root), "diff", "--name-only", run_sha, grade_sha, "--", *deck_inputs], capture_output=True, text=True)
    return None if p.returncode != 0 else [ln for ln in p.stdout.splitlines() if ln.strip()]


def snapshot_request_artifacts(src: Path, tag: str, snap_dir: Path, corners_dir: Path, run_dir: Path, repo_root: Path) -> None:
    """Copy a request's netlist/request snapshots into snap_dir and its scrubbed klt report into corners_dir/<tag>."""
    for name in ("netlist.spice", "request.json"):
        if (src / name).is_file():
            snap_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / name, snap_dir / f"{tag}.{name}")
    if (src / "report.json").is_file():
        (corners_dir / tag).mkdir(parents=True, exist_ok=True)
        (corners_dir / tag / "klt-report.json").write_text(scrub((src / "report.json").read_text(), run_dir, repo_root))


def submit_failures(requests: list[dict]) -> list[dict]:
    """Requests that never got a job id and ended in a non-passing outcome."""
    return [{"tag": q["tag"], "reason": q["outcome"]} for q in requests if q.get("job_id") is None and q.get("outcome") and q["outcome"] not in ("ok", "OK", "PASS")]


def refuse_unsubmittable(gi: dict, allow_dirty: bool, *, require_pushed: bool = False) -> None:
    """Exit unless the tree is clean: the submit-time twin of ``refuse_unrecordable``.

    A fleet run's record cites its submit commit as the source revision of the evidence,
    so a dirty tree leaves that citation unresolvable -- what
    ``docs/characterization-report.md`` calls a provenance-weak record.
    ``--allow-dirty`` overrides it for a debug run; the state is recorded either way.
    ``require_pushed`` additionally demands that HEAD is on a remote branch, so the
    fleet runners' own source SHA resolves (brown-out and glitch).
    """
    if require_pushed:
        if (gi["dirty"] or not gi["pushed_to_remote"]) and not allow_dirty:
            raise SystemExit(f"refusing to submit: dirty={gi['dirty']} pushed={gi['pushed_to_remote']} (commit + push first, or --allow-dirty; the state is recorded either way)")
    elif gi["dirty"] and not allow_dirty:
        raise SystemExit("refusing to submit from a dirty tree (commit first so the record cites a resolvable source revision, or --allow-dirty; the state is recorded either way)")


def refuse_unrecordable(gi: dict, drift: list[str] | None, allow_dirty: bool, allow_deck_drift: bool) -> None:
    """Exit unless the tree is clean and the deck unchanged since submit (each overridable)."""
    if gi["dirty"] and not allow_dirty:
        raise SystemExit("refusing to record from a dirty tree (commit first, or --allow-dirty; the state is recorded either way)")
    if drift and not allow_deck_drift:
        raise SystemExit(f"deck inputs changed between the submit commit and HEAD: {drift} -- the record would mis-attribute the evidence")


def report_usable(report_path: Path) -> bool:
    """True when a klt report.json exists and carries per-corner results (the retry-failed predicate)."""
    try:
        return report_path.is_file() and "corners" in json.loads(report_path.read_text())
    except json.JSONDecodeError:
        return False


TRIAGE_CAP = 600

# The one wording for "this request never reached the fleet".  Named, because a
# grader that treats it differently from a post-submission failure (iq-top keeps its
# pre-seeded per-point reason) must test for it without re-encoding the text, and
# because the "NOT SUBMITTED" prefix is asserted on by
# sim/iq-top/test_solver_sensitivity.py.
NOT_SUBMITTED = "NOT SUBMITTED / no report"

FLEET_JOB_KEYS = ("job_id", "instance_type", "lifecycle", "runner_klt_version",
                  "client_klt_version", "elapsed_seconds", "state")


def load_request_report(d: Path, run_dir: Path, repo_root: Path, cap: int = TRIAGE_CAP) -> tuple[dict | None, str | None]:
    """One fleet request's gradeable klt report, or the scrubbed reason it cannot be graded.

    Exactly one of the two is None: `(report, None)` when `d/report.json` parses and
    carries per-corner results -- the same predicate `report_usable()` applies on the
    retry path -- and `(None, why)` for each of the three ways a request yields nothing
    to grade:

        no report.json       "NOT SUBMITTED / no report"
        unparseable          "NO JSON (klt failed before a report existed): <klt.stderr tail>"
        report without corners "klt error (no corners reported): <report error message>"

    Every campaign grader used to carry its own copy of this block.  The copies had
    drifted into three wordings for a missing report, two for a report without
    corners, and stderr-tail caps of 500/600/800 (issue #322); one wording and one
    cap now serve all six.  The "NOT SUBMITTED" prefix is load-bearing --
    `sim/iq-top/test_solver_sensitivity.py` asserts on it.  `klt.stderr` is read only
    when it exists: klt can refuse before writing either file.
    """
    rep_path = d / "report.json"
    if not rep_path.is_file():
        return None, NOT_SUBMITTED
    try:
        rep = json.loads(rep_path.read_text())
    except json.JSONDecodeError:
        err = d / "klt.stderr"
        tail = err.read_text()[-cap:] if err.is_file() else ""
        return None, "NO JSON (klt failed before a report existed): " + scrub(tail, run_dir, repo_root)
    if "corners" not in rep:
        msg = str((rep.get("error") or {}).get("message", rep))[:cap]
        return None, "klt error (no corners reported): " + scrub(msg, run_dir, repo_root)
    return rep, None


def fleet_job_fields(report: dict) -> dict:
    """The fleet-job provenance a request record carries: `environment.remote` plus the report's own status.

    One key list for every grader.  `client_klt_version` is in it on purpose: a request
    record that omits it cannot show a client-versus-runner klt version skew, which is
    exactly what two of the six copies did before issue #322.  Keys absent from the
    report are recorded as None rather than dropped, so a record always has the same
    shape whatever the fleet reported.
    """
    remote = (report.get("environment") or {}).get("remote") or {}
    fields = {k: remote.get(k) for k in FLEET_JOB_KEYS}
    fields["corner_count"] = report.get("corner_count")
    fields["outcome"] = report.get("status")
    return fields


CONCURRENCY_CAP_MARKER = "BATCH_MAX_CONCURRENT_INSTANCES"


def concurrency_capped(*texts: str) -> bool:
    """True when any text is klt's error envelope for the shared fleet's concurrent-instance cap refusal.

    klt's capacity_wait_s only waits out Spot capacity refusals, not this cap
    (2AMLogic/klayout-tools#2917).  The refusal creates no instance and runs no
    corner.  Strict on purpose: a report that carries per-corner results is never a
    refusal, even if it mentions the marker.
    """
    for text in texts:
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(body, dict) and "corners" not in body and CONCURRENCY_CAP_MARKER in str((body.get("error") or {}).get("message", "")):
            return True
    return False


def cap_retry(d: Path, label: str, poll_s: float, budget_s: float | None = None, max_retries: int | None = None,
              evidence: str = "launch-refused", sleep=None, clock=None):
    """`retry` hook for submit_prepared: wait out a fleet concurrency-cap refusal and resubmit (never a local grid).

    Retries while the run was refused at the cap and the bounds allow another wait:
    at most `max_retries` retries and/or `budget_s` seconds in total (the next
    wait must fit in the budget).  Every refusal is kept as evidence in `d`:
    evidence="launch-refused" -> launch-refused-N.txt (stdout+stderr);
    evidence="attempt" -> attemptN/report.json + klt.stderr, as an archived earlier attempt.
    `sleep`/`clock` are injectable for tests.
    """
    import time
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    start = clock()

    def retry(p, n):
        # klt writes its --format json error envelope to stderr, not stdout: check both
        if not concurrency_capped(p.stdout, p.stderr):
            return False
        if max_retries is not None and n > max_retries:
            return False
        if budget_s is not None and clock() - start + poll_s > budget_s:
            return False
        if evidence == "attempt":
            k = 1
            while (d / f"attempt{k}").exists():
                k += 1
            (d / f"attempt{k}").mkdir(parents=True)
            (d / f"attempt{k}" / "report.json").write_text(p.stdout)
            (d / f"attempt{k}" / "klt.stderr").write_text(p.stderr)
        else:
            (d / f"launch-refused-{n}.txt").write_text(p.stdout + p.stderr)
        say(f"[wait]   {label}: fleet concurrency cap reached; resubmitting in {poll_s:.0f} s")
        sleep(poll_s)
        return True
    return retry


def _json_document(text: str):
    """Parse a JSON document that may be preceded by non-JSON noise (klt prints a plain
    line ahead of its error envelope).  None when nothing parses."""
    for candidate in (text, text[text.index("{"):] if "{" in text else None):
        if candidate is None:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def attempt_message(ad: Path) -> str:
    """One archived attempt's outcome: the report's error/status, else klt's stderr error envelope."""
    for name in ("report.json", "klt.stderr"):
        f = ad / name
        if not f.is_file():
            continue
        body = _json_document(f.read_text())
        if isinstance(body, dict) and (body.get("error") or body.get("status")):
            return (body.get("error") or {}).get("message") or ("report status " + str(body.get("status")))
    tail = (ad / "klt.stderr").read_text()[-300:].strip() if (ad / "klt.stderr").is_file() else ""
    return "unparseable report" + (f": {tail}" if tail else "")


def attempt_messages(d: Path, run_dir: Path, repo_root: Path, cap: int = 400) -> list[str]:
    """A request's `failed_earlier_attempts`: one scrubbed line per `attemptN/` under `d`, oldest first.

    `cap_retry`/`submit_prepared` archive each superseded submit as `attemptN/report.json`
    (klt's stdout) + `attemptN/klt.stderr`; both are read, because klt writes its
    `--format json` error envelope to stderr when it refuses before any report exists.
    Sorted numerically, so attempt10 follows attempt9 rather than attempt1.
    """
    def order(p: Path) -> tuple[int, str]:
        n = p.name[len("attempt"):]
        return (int(n) if n.isdigit() else 0, p.name)

    return [scrub(attempt_message(ad), run_dir, repo_root)[:cap] for ad in sorted(d.glob("attempt*"), key=order)]


def submit_prepared(d: Path, netlist: str | None, request: dict, submit_msg: str, done_label: str,
                    retry=None, files: dict[str, str] | None = None) -> dict:
    """Archive d's earlier attempt, write netlist.spice + request.json, run `klt sim --backend batch`.

    An earlier attempt's report.json/klt.stderr is archived to attemptN/, never
    overwritten. `submit_msg`/`done_label` are the texts after "[submit] " and
    "[done]   " in the log lines. `retry(proc, n)`, if given, is called after
    each klt run (n = 1, 2, ...) and returns True to run klt again on the same
    request (e.g. a bounded launch-refusal wait); only the last run's output is
    written to report.json/klt.stderr.

    `netlist` is None for a `decks[]` request, which carries no `netlist` field; its
    per-unit decks and inputs are passed as `files`, a map of d-relative paths to their
    text, written before the submit so each `decks[].deck`/`inputs[].path` resolves
    against the request file's own directory (see `deck_request()`).
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
    if netlist is not None:
        (d / "netlist.spice").write_text(netlist)
    for rel, text in (files or {}).items():
        unit_file = d / rel
        unit_file.parent.mkdir(parents=True, exist_ok=True)
        unit_file.write_text(text)
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


# --------------------------------------------------------------------------
# deck-list (`decks[]`) requests: the fleet as transport, not as corner engine
# --------------------------------------------------------------------------

DECK_NOTE = (
    "submitted as a `klt sim` deck-list (`decks[]`) request, the transport klt documents "
    "for a harness that renders its own decks and mints its own evidence from the raw logs "
    "(klayout-tools #2804): each point's deck is shipped byte-for-byte and run as "
    "`ngspice -b <deck>` in its own directory on the fleet worker, so the artifact is the "
    "one this harness mints rather than one klt re-composed from a corner axis. The "
    "per-point `.spiceinit` rides as a `decks[].inputs[]` entry, which is how a setting the "
    "fleet drops from `options.ngspice_init` still reaches the run"
)


def runner_lib_ref(variant: str = "sky130A", lib: str = MODEL_LIB) -> str:
    """The model library as a *shipped deck* must spell it: `$PDK_ROOT/<variant>/<lib>`.

    A deck-list request never rewrites the deck, so an absolute path under the SUBMITTING
    host's `$PDK_ROOT` is refused by name rather than retargeted at the runner's PDK. The
    `$PDK_ROOT` spelling is the one each executing host -- this one for a local probe, the
    fleet worker for the real run -- expands for itself.
    """
    return f"$PDK_ROOT/{variant}/{lib}"


def deck_request(
    units: list[dict],
    backend: str,
    *,
    timeout_s: int,
    pdk_variant: str = "sky130A",
    capacity_wait_s: float = 0,
    max_workers: int | None = None,
) -> dict:
    """`decks[]` request skeleton shared by the deck-transport campaign drivers.

    `units` is the `decks[]` list (each: `id`, `deck`, optional `inputs`, `timeout_s`).
    A deck request must NOT also declare `netlist`, `corners`, `analysis`, `measurements`
    or `monte_carlo` -- klt rejects a document carrying both by name -- so this skeleton
    deliberately has no overlap with `base_request()`. Key order is part of the contract
    (request.json is recorded evidence).
    """
    req = {
        "backend": backend,
        "models": {"pdk": pdk_variant},
        "decks": units,
        "options": {"timeout_s": timeout_s, **({"max_workers": max_workers} if max_workers else {})},
    }
    if backend == "batch":
        req["batch"] = {"runner_version_check": "warn"}
        if capacity_wait_s:
            req["batch"]["capacity_wait_s"] = capacity_wait_s
    return req


def snapshot_deck_request(src: Path, corners_dir: Path, run_dir: Path, repo_root: Path) -> None:
    """Copy a deck-list submit's own artifacts into the record's committed evidence.

    The same convention `corner-run.py` uses for a batch corner run (`corners/<record>/
    batch/`): the request as submitted, klt's report, and klt's stderr, each scrubbed of
    build-tree and home paths. There is no `netlist.spice` for a deck request, and the
    per-unit decks are not duplicated here because each point's own `.log` already
    embeds the exact deck ngspice was given.
    """
    for name in ("request.json", "report.json", "klt.stderr"):
        f = src / name
        if f.is_file():
            dst = corners_dir / "batch" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(scrub(f.read_text(), run_dir, repo_root))


def deck_units(report: dict | None) -> dict[str, dict]:
    """`{unit id: unit}` of a `decks[]` report; empty for anything that is not one."""
    return {u["id"]: u for u in (report or {}).get("units", []) if isinstance(u, dict) and u.get("id")}


def deck_streams(report: dict, unit: dict) -> str:
    """One unit's captured `stdout.bin` + `stderr.bin`, concatenated the way a local
    `ngspice -b` harness read `proc.stdout + proc.stderr`.

    klt ships the streams back as bytes and never normalizes them, so they are decoded
    here with `errors="replace"` rather than assumed to be clean UTF-8. Stream paths in
    the report are relative to its own absolute `outdir`.
    """
    out_dir = Path(report.get("outdir", ""))
    text = ""
    for key in ("stdout", "stderr"):
        rel = unit.get(key)
        if not rel:
            continue
        path = out_dir / rel
        if path.is_file():
            text += path.read_bytes().decode(errors="replace")
    return text


_SOLVER_RE = re.compile(r"Using (.+?) as Direct Linear Solver")


def log_solver(log_text: str) -> str | None:
    """The linear solver ngspice announced in a run log (`KLU`, `SPARSE 1.3`), or None.

    This is the observable that proves a `.spiceinit` solver setting actually reached the
    engine. It matters because the fleet runner ignores `options.ngspice_init`: a variant
    whose setting was silently dropped would otherwise be indistinguishable from one that
    took effect, and the record would name a numerical path nobody ran (issue #319).
    """
    m = _SOLVER_RE.search(log_text)
    return m.group(1).strip() if m else None


def spiceinit_text(sim_dir: Path, *, disable: tuple[str, ...] = (), extra: tuple[str, ...] = (), by: str = "") -> str:
    """`<sim_dir>/spiceinit` rendered as the `.spiceinit` one point actually runs under.

    `disable` comments out every init line starting with one of its entries (e.g.
    `"option klu"`), naming `by` as the script that disabled it; `extra` appends lines
    (e.g. a Monte Carlo point's `set mc_seed=`). Both edits stay visible in the returned
    text, because this is the exact file shipped into the run directory as `.spiceinit`
    and embedded verbatim in the point's log.
    """
    lines = []
    for line in (sim_dir / "spiceinit").read_text().splitlines():
        if any(line.strip().startswith(d) for d in disable):
            lines.append(f"* {line}")
            lines.append(f"*   ^ DISABLED by {by}")
        else:
            lines.append(line)
    if extra:
        lines += ["", f"* injected by {by}", *extra]
    return "\n".join(lines) + "\n"


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
    cr = load_corner_run()
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


def refuse_existing(paths) -> None:
    """Abort if any of ``paths`` already exists: ``sim/`` is append-only evidence, never overwritten."""
    for pth in paths:
        if pth.exists():
            raise SystemExit(f"{pth} exists -- sim/ is append-only")


def spiceinit_lines(sim_dir: Path) -> list[str]:
    """The ngspice init lines of ``<sim_dir>/spiceinit`` (blank and ``*`` comment lines dropped)."""
    return [ln.strip() for ln in (sim_dir / "spiceinit").read_text().splitlines() if ln.strip() and not ln.startswith("*")]


def run_local_probe(d: Path) -> subprocess.CompletedProcess:
    """Run ``<d>/request.json`` as ONE local ``klt sim`` (never a grid); save ``report.json`` and ``klt.stderr`` in ``d``."""
    p = subprocess.run(
        ["klt", "sim", str(d / "request.json"), "--backend", "local", "-o", str(d / "out"), "--format", "json"],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    (d / "report.json").write_text(p.stdout)
    (d / "klt.stderr").write_text(p.stderr)
    return p
