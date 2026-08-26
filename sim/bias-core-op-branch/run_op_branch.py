#!/usr/bin/env python3
"""Cold-`.op` branch-selection diagnostic for `bias_core` (issue #19).

Why this is a bespoke `run_*.py` and not a `sim/bin/corner-run.py`
`experiment.json`
--------------------------------------------------------------------
`corner-run.py` runs exactly one deterministic deck per PVT point and
enforces the full PVT matrix. The object under study here is not a PVT
point at all: it is *the solver's own path to a DC operating point* at a
single process/temperature point (`tt`/27 °C), which needs

1. a **fine supply axis** (10 mV steps from 2.97 V to 3.63 V, 67 points --
   far denser than the 3-point supply axis a PVT matrix declares), and
2. the **same deck run under different numerical settings** (KLU vs. the
   default sparse solver; dynamic gmin stepping vs. source stepping vs. a
   designer `.nodeset` seed), which is an axis `experiment.json` has no way
   to express.

Same rule as `sim/pnp-mismatch/run_pnp_mismatch.py`, per `sim/README.md`
("Experiments that do not go through the corner runner"): this script still
reuses `corner-run.py`'s PDK resolution and pin enforcement, mints the same
record id, refuses to overwrite anything under `sim/<slug>/`, writes both
the `.md` and the `.json` twin, commits a netlist snapshot, and embeds the
exact deck in every per-point log.

What it measures
----------------
`sim/bias-core-smoke/`'s first record (`20260825-214036-a9cac4b`) reports
two FAILing corners -- `tt_27c_2.97v` and `tt_27c_3.63v` -- where `VREF`
sits near `VDD` and the supply current is reported as **negative**
milliamps. Issue #19 asks whether that is a real second stable state of the
circuit (a startup-robustness defect) or an artifact of the cold `.op`
solve's own continuation path.

The discriminator this script applies is **physicality**, and it is
deliberately encoded as a per-point pass/fail rather than as prose:

- A real second DC equilibrium is a *physical* solution. It obeys KCL, its
  node voltages lie inside the rails (or at least within volts of them),
  and -- with a single supply feeding an otherwise passive network -- it
  dissipates power, so the supply must **source** current
  (`-i(v1) > 0`).
- Every off-branch point this script finds is checked against those two
  conditions (`nonphysical[...]` check). The check **passes when the
  off-branch point is demonstrably non-physical**, i.e. when it cannot be a
  circuit state. An off-branch point that turned out to be physical would
  FAIL that check and the record -- which is exactly the outcome that would
  mean "real silicon risk, harden the startup circuit".

Reusing the smoke testbench is deliberate: the object under study is that
experiment's own `.op` deck, so this script netlists
`sim/bias-core-smoke/testbench/tb_bias_core_smoke.sch` unchanged (its
`provenance_source`) and only varies what the runner injects around it.

Usage
-----
    sim/bias-core-op-branch/run_op_branch.py                # the full run
    sim/bias-core-op-branch/run_op_branch.py --quick        # ~20 points
    sim/bias-core-op-branch/run_op_branch.py --dry-run      # print the plan

Exit status: 0 every check passed, 2 a record was written but a check
failed, 1 harness/setup error (no record written) -- same convention as
`corner-run.py`.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
BUILD_DIR = SIM_DIR / "build" / "bias-core-op-branch"
SPICEINIT_FILE = SIM_DIR / "spiceinit"
TESTBENCH = SIM_DIR / "bias-core-smoke" / "testbench" / "tb_bias_core_smoke.sch"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    add_common_args,
    load_corner_run,
    render_log,
    render_pdk_tools_repo_state,
    render_record_id_experiment,
)

cr = load_corner_run()

# --------------------------------------------------------------------------
# experiment definition
# --------------------------------------------------------------------------

SLUG = "bias-core-op-branch"
TITLE = (
    "bias_core cold-`.op` branch selection: is the near-VDD high-current DC point "
    "a second stable state or a solver artifact?"
)

CLAIM = (
    "Issue #19 -- NOT a spec claim (spec/target-spec.md does not exist yet, "
    "spec/porting-plan.md Sec4 item 4). Characterizes the two FAILing corners in "
    "sim/bias-core-smoke/records/20260825-214036-a9cac4b.md (tt_27c_2.97v, "
    "tt_27c_3.63v): whether the near-VDD, milliamp-current DC point ngspice "
    "reports there is a real second equilibrium of bias_core (a startup-robustness "
    "defect) or a non-physical artifact of the cold .op solve's own continuation "
    "path. Discriminator: physicality of each off-branch point (supply-current sign "
    "and internal-node magnitude), plus whether the off-branch set moves when only "
    "the numerics change (linear solver / continuation method / .nodeset seed) while "
    "the circuit is held identical."
)

PROCESS = "tt"
TEMP_C = 27.0
SUPPLY_LO, SUPPLY_HI, SUPPLY_STEP = 2.97, 3.63, 0.01
HEADLINE_SUPPLIES = (2.97, 3.63)  # the two corners sim/bias-core-smoke/ flagged
TEMP_NEIGHBOURHOOD = [22.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0, 32.0]
TEMP_NEIGHBOURHOOD_SUPPLY = 2.97
N_CONTROL_REPEATS = 3

# The values sim/bias-core-smoke/'s own record reports at the two failing
# corners. Re-deriving them here is the control that fails loudly if this
# script has drifted away from the artifact it exists to explain.
SMOKE_RECORD_ID = "20260825-214036-a9cac4b"
SMOKE_OFF_BRANCH_VREF = {2.97: 2.965472, 3.63: 3.625298}
SMOKE_MATCH_TOL_V = 1e-5

# good-branch acceptance window (same harness-liveness band as
# sim/bias-core-smoke/'s own vref bound -- NOT a spec claim)
GOOD_VREF = (1.0, 1.4)
GOOD_ISUP = (1e-8, 1e-5)

# An off-branch point is *non-physical* -- i.e. cannot be a state bias_core is
# able to occupy, whatever the solver reports -- if EITHER holds:
#
#   1. the supply current is negative: with V1 the only energy source and every
#      other element in the cell passive (MOS, BJT, poly resistors, MIM caps),
#      a DC solution must dissipate power, so V1 must SOURCE current.
#   2. any node sits outside [VSS - RAIL_MARGIN_V, VDD + RAIL_MARGIN_V]. The
#      cell contains no charge pump, no inductor and no second supply, so every
#      node is bounded by the rails; a full volt of margin is far more slack
#      than a junction drop or any model's series-resistance artefact needs.
#
# Deliberately NOT an "absurdly large number" threshold: a solver false
# convergence can land a node a few tens of volts outside the rail as easily as
# 1e8 V outside it, and both are equally impossible. Anchoring the test to the
# rails keeps the criterion physical rather than arbitrary.
RAIL_MARGIN_V = 1.0

INTERNAL_NODES = (
    "xdut.na",
    "xdut.nb",
    "xdut.nbtop",
    "xdut.ec",
    "xdut.er",
    "xdut.pg",
    "xdut.pb",
    "xdut.nbg",
    "xdut.n1",
    "xdut.n2",
    "xdut.nt",
    "xdut.nkg",
    "xdut.nkm",
)
PIN_NODES = ("vref", "ibias", "bias_ok")
SUPPLY_VECTOR = "-i(v1)"


@dataclass(frozen=True)
class Variant:
    """One numerical path to the same circuit's operating point."""

    name: str
    klu: bool
    options: tuple[str, ...] = ()
    nodeset: tuple[str, ...] = ()
    description: str = ""


VARIANTS = {
    v.name: v
    for v in (
        Variant(
            "klu",
            klu=True,
            description=(
                "the harness default: sim/spiceinit's `option klu` linear solver, "
                "ngspice's automatic dynamic-gmin-stepping fallback. This is exactly "
                "what produced sim/bias-core-smoke/'s own record."
            ),
        ),
        Variant(
            "sparse",
            klu=False,
            description=(
                "identical deck, identical circuit, ONE thing changed: `option klu` "
                "commented out, so ngspice uses its built-in sparse solver. A linear "
                "solver cannot change a circuit's set of equilibria -- it only changes "
                "the arithmetic path taken to one -- so any point whose branch flips "
                "here is a property of the numerics, not of bias_core."
            ),
        ),
        Variant(
            "srcstep",
            klu=True,
            options=("gminsteps=0",),
            description=(
                "KLU, but gmin stepping disabled (`.option gminsteps=0`), which leaves "
                "source stepping as ngspice's continuation fallback. A second, "
                "independent way to vary only the continuation path."
            ),
        ),
        Variant(
            "nodeset",
            klu=True,
            nodeset=(
                "v(vref)=1.25",
                "v(xdut.na)=0.7",
                "v(xdut.ec)=0.7",
                "v(xdut.er)=0.7",
            ),
            description=(
                "KLU, plus a designer `.nodeset` seed: VREF at its intended ~1.25 V and "
                "the three PNP emitter nodes at one diode drop. This is the mitigation "
                "option issue #19 names for cold-`.op` characterization -- four numbers "
                "a designer can write down before simulating, not the solved answer."
            ),
        ),
    )
}


@dataclass
class Point:
    point_id: str
    role: str  # sweep | temp-sweep | variant | control
    variant: str
    supply_v: float
    temp_c: float
    purpose: str
    repeat: int = 0
    values: dict = field(default_factory=dict)


def frange(lo: float, hi: float, step: float) -> list[float]:
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 6) for i in range(n + 1)]


def build_points(quick: bool) -> list[Point]:
    supplies = frange(SUPPLY_LO, SUPPLY_HI, SUPPLY_STEP)
    temps = list(TEMP_NEIGHBOURHOOD)
    if quick:
        supplies = sorted(set(supplies[::10]) | set(HEADLINE_SUPPLIES))
        temps = [26.0, 27.0, 28.0]

    points: list[Point] = []
    for variant in ("klu", "sparse"):
        for v in supplies:
            points.append(
                Point(
                    point_id=f"sweep-{variant}_{PROCESS}_{TEMP_C:g}c_{v:.2f}v",
                    role="sweep",
                    variant=variant,
                    supply_v=v,
                    temp_c=TEMP_C,
                    purpose=(
                        f"fine supply sweep under the `{variant}` numerics -- maps which "
                        "supply points a cold .op lands off the intended branch on"
                    ),
                )
            )
    for t in temps:
        points.append(
            Point(
                point_id=f"temp-klu_{PROCESS}_{t:g}c_{TEMP_NEIGHBOURHOOD_SUPPLY:.2f}v",
                role="temp-sweep",
                variant="klu",
                supply_v=TEMP_NEIGHBOURHOOD_SUPPLY,
                temp_c=t,
                purpose=(
                    "temperature neighbourhood of the flagged 27 degC point at the low "
                    "supply extreme -- is the failure tied to 27 degC, or scattered?"
                ),
            )
        )
    for variant in ("srcstep", "nodeset"):
        for v in HEADLINE_SUPPLIES:
            points.append(
                Point(
                    point_id=f"variant-{variant}_{PROCESS}_{TEMP_C:g}c_{v:.2f}v",
                    role="variant",
                    variant=variant,
                    supply_v=v,
                    temp_c=TEMP_C,
                    purpose=(
                        f"one of sim/bias-core-smoke/'s two flagged corners re-solved "
                        f"with the `{variant}` continuation path, circuit unchanged"
                    ),
                )
            )
    for i in range(N_CONTROL_REPEATS):
        points.append(
            Point(
                point_id=f"control-repeat{i + 1}_{PROCESS}_{TEMP_C:g}c_{HEADLINE_SUPPLIES[0]:.2f}v",
                role="control",
                variant="klu",
                supply_v=HEADLINE_SUPPLIES[0],
                temp_c=TEMP_C,
                purpose=(
                    "determinism control: the identical deck under the identical "
                    "numerics, re-run. ngspice is deterministic, so these must agree "
                    "bit-for-bit -- without that, a branch difference between two "
                    "VARIANTS could be run-to-run noise rather than the numerics"
                ),
                repeat=i + 1,
            )
        )
    return points


# --------------------------------------------------------------------------
# deck generation / ngspice
# --------------------------------------------------------------------------


def spiceinit_text(variant: Variant) -> str:
    text = SPICEINIT_FILE.read_text()
    if not variant.klu:
        text = text.replace(
            "option klu",
            "* option klu -- DISABLED by sim/bias-core-op-branch/run_op_branch.py\n"
            "* (variant `sparse`: ngspice falls back to its built-in sparse solver)",
        )
    return text


def build_deck(pdk, point: Point, body: list[str]) -> str:
    variant = VARIANTS[point.variant]
    head = [
        f"* {SLUG} point deck -- generated by sim/bias-core-op-branch/run_op_branch.py",
        f"* point: {point.point_id}",
        f"* variant: {variant.name} -- {variant.description}",
        f".param vsup={point.supply_v}",
        ".option wnflag=1",
    ]
    head += [f".option {o}" for o in variant.options]
    head += [f".temp {point.temp_c:g}", f'.lib "{pdk.lib_file}" {PROCESS}']
    if variant.nodeset:
        head.append(".nodeset " + " ".join(variant.nodeset))

    control = [".control", "save all", "op"]
    control += [f"print {n}" for n in (*PIN_NODES, *INTERNAL_NODES)]
    control.append(f"print {SUPPLY_VECTOR}")
    control += ["quit", ".endc", ".end", ""]
    return "\n".join(head + body + control)


VALUE_RE = re.compile(r"^(-?[a-z0-9_.()]+)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)\s*$")


def parse_values(raw: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in raw.splitlines():
        m = VALUE_RE.match(line.strip())
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def run_point(pdk, point: Point, body: list[str], record_id: str, timeout: int) -> dict:
    run_dir = BUILD_DIR / record_id / point.point_id
    run_dir.mkdir(parents=True, exist_ok=True)
    deck = build_deck(pdk, point, body)
    (run_dir / "deck.spice").write_text(deck)
    (run_dir / ".spiceinit").write_text(spiceinit_text(VARIANTS[point.variant]))
    try:
        proc = subprocess.run(
            ["ngspice", "-b", "deck.spice"],
            cwd=run_dir,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        raw, rc, timed_out = proc.stdout + proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        out, err = exc.stdout or "", exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        raw, rc, timed_out = out + err, -1, True
    return {"point": point, "deck": deck, "raw": raw, "rc": rc, "timed_out": timed_out}


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------


def classify(values: dict[str, float]) -> str:
    vref = values.get("vref")
    isup = values.get(SUPPLY_VECTOR)
    if vref is None or isup is None:
        return "unknown"
    if GOOD_VREF[0] <= vref <= GOOD_VREF[1] and GOOD_ISUP[0] <= isup <= GOOD_ISUP[1]:
        return "good"
    return "off"


def worst_node(values: dict[str, float]) -> tuple[str, float]:
    """The measured node furthest from 0 V (reported, not a pass/fail input)."""
    worst, mag = "", 0.0
    for name in (*PIN_NODES, *INTERNAL_NODES):
        v = values.get(name)
        if v is not None and abs(v) > abs(mag):
            worst, mag = name, v
    return worst, mag


def rail_violations(values: dict[str, float], supply_v: float) -> list[tuple[str, float]]:
    """Nodes outside [VSS - RAIL_MARGIN_V, VDD + RAIL_MARGIN_V]."""
    lo, hi = -RAIL_MARGIN_V, supply_v + RAIL_MARGIN_V
    out = []
    for name in (*PIN_NODES, *INTERNAL_NODES):
        v = values.get(name)
        if v is not None and not (lo <= v <= hi):
            out.append((name, v))
    out.sort(key=lambda nv: -abs(nv[1]))
    return out


def evaluate(res: dict) -> dict:
    point: Point = res["point"]
    values = parse_values(res["raw"])
    branch = classify(values)
    node, node_v = worst_node(values)
    isup = values.get(SUPPLY_VECTOR)
    vref = values.get("vref")
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    add(
        f"ngspice_ok[{point.point_id}]",
        res["rc"] == 0 and not res["timed_out"],
        f"ngspice exit {res['rc']}" + (" (TIMEOUT)" if res["timed_out"] else ""),
    )
    add(
        f"measured[{point.point_id}]",
        vref is not None and isup is not None,
        f"vref={vref}, {SUPPLY_VECTOR}={isup}",
    )

    violations = rail_violations(values, point.supply_v)
    if branch == "good":
        add(
            f"good_branch_physical[{point.point_id}]",
            isup is not None and isup > 0 and not violations,
            f"VREF={vref:.6g} V in [{GOOD_VREF[0]}, {GOOD_VREF[1]}] V, supply SOURCES "
            f"{isup * 1e6:.3f} uA (positive), every node inside "
            f"[{-RAIL_MARGIN_V:g}, {point.supply_v + RAIL_MARGIN_V:.2f}] V "
            f"(furthest: {node}={node_v:.4g} V) -- a physical operating point"
            + (
                ""
                if not violations
                else " -- EXCEPT " + ", ".join(f"{n}={v:.4g} V" for n, v in violations)
            ),
        )
    elif branch == "off":
        nonphysical = (isup is not None and isup < 0) or bool(violations)
        why = []
        if isup is not None and isup < 0:
            why.append(
                f"supply current {isup * 1e3:.4g} mA is NEGATIVE -- the circuit would be "
                "delivering power into its own only energy source, which a passive "
                "network cannot do"
            )
        if violations:
            why.append(
                f"{len(violations)} node(s) outside the rails by more than "
                f"{RAIL_MARGIN_V:g} V ("
                + ", ".join(f"{n}={v:.4g} V" for n, v in violations[:4])
                + f"), against a {point.supply_v:.2f} V rail and no charge pump, "
                "inductor or second supply anywhere in the cell"
            )
        add(
            f"nonphysical[{point.point_id}]",
            nonphysical,
            f"off-branch point (VREF={vref:.6g} V near VDD={point.supply_v:.2f} V): "
            + ("; ".join(why) if why else "")
            + (
                ""
                if nonphysical
                else " -- point is PHYSICALLY PLAUSIBLE: this would be a REAL second "
                "equilibrium, i.e. a startup-robustness defect, not a solver artifact"
            ),
        )
    else:
        add(f"parsed[{point.point_id}]", False, "no vref/supply-current value parsed")

    return {
        "point_id": point.point_id,
        "role": point.role,
        "variant": point.variant,
        "purpose": point.purpose,
        "process": PROCESS,
        "temperature_c": point.temp_c,
        "supply_v": point.supply_v,
        "repeat": point.repeat,
        "ngspice_exit": res["rc"],
        "timed_out": res["timed_out"],
        "branch": branch,
        "vref": vref,
        "isup": isup,
        "worst_internal_node": {"name": node, "value": node_v},
        "rail_violations": [{"node": n, "value": v} for n, v in violations],
        "rail_window_v": [-RAIL_MARGIN_V, point.supply_v + RAIL_MARGIN_V],
        "values": values,
        "checks": checks,
        "pass": all(c["pass"] for c in checks),
    }


def off_supplies(results: list[dict], variant: str) -> list[float]:
    return sorted(
        r["supply_v"]
        for r in results
        if r["role"] == "sweep" and r["variant"] == variant and r["branch"] == "off"
    )


def cross_checks(results: list[dict]) -> list[dict]:
    """Checks that need more than one point."""
    out: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        out.append({"name": name, "pass": bool(ok), "detail": detail})

    # -- control: the artifact this script exists to explain is still present.
    headline = {
        r["supply_v"]: r
        for r in results
        if r["role"] == "sweep" and r["variant"] == "klu" and r["supply_v"] in SMOKE_OFF_BRANCH_VREF
    }
    for supply, expected in SMOKE_OFF_BRANCH_VREF.items():
        r = headline.get(supply)
        got = r["vref"] if r else None
        ok = got is not None and abs(got - expected) <= SMOKE_MATCH_TOL_V
        add(
            f"artifact_reproduced[{supply:.2f}v]",
            ok,
            f"cold .op under the harness's own numerics reproduces "
            f"sim/bias-core-smoke/records/{SMOKE_RECORD_ID}.md's off-branch "
            f"VREF={expected:.6g} V (measured {got if got is None else format(got, '.6g')} V, "
            f"tolerance {SMOKE_MATCH_TOL_V:g} V). This is the control that must fail if the "
            "mechanism under test is no longer active -- without it, an all-good sweep "
            "would be indistinguishable from a script that stopped exercising the artifact",
        )

    # -- control: ngspice is deterministic, so variant-to-variant differences mean something.
    repeats = [r for r in results if r["role"] == "control"]
    vrefs = [r["vref"] for r in repeats if r["vref"] is not None]
    add(
        "control_determinism",
        len(vrefs) == len(repeats) and len(set(vrefs)) == 1,
        f"{len(repeats)} identical re-runs of the same deck under the same numerics "
        f"returned VREF {sorted(set(vrefs))} -- must be a single value, or a branch "
        "difference between two variants could be run-to-run noise",
    )

    klu_off = off_supplies(results, "klu")
    sparse_off = off_supplies(results, "sparse")
    n_sweep = len([r for r in results if r["role"] == "sweep" and r["variant"] == "klu"])
    only_klu = sorted(set(klu_off) - set(sparse_off))
    only_sparse = sorted(set(sparse_off) - set(klu_off))
    add(
        "solver_dependence",
        bool(only_klu or only_sparse),
        f"off-branch supply points under KLU: {len(klu_off)}/{n_sweep} "
        f"{[f'{v:.2f}' for v in klu_off]}; under the sparse solver: "
        f"{len(sparse_off)}/{n_sweep} {[f'{v:.2f}' for v in sparse_off]}. "
        f"Points that flip when ONLY the linear solver changes: "
        f"{[f'{v:.2f}' for v in only_klu + only_sparse]}. A linear solver cannot add or "
        "remove an equilibrium of the circuit, so any flip is proof the branch reported "
        "is chosen by the numerics",
    )

    # -- is the off-branch set a contiguous supply region (physics) or scattered (numerics)?
    for variant, off in (("klu", klu_off), ("sparse", sparse_off)):
        runs = 0
        for i, v in enumerate(off):
            if i == 0 or abs(v - off[i - 1] - SUPPLY_STEP) > SUPPLY_STEP / 2:
                runs += 1
        out.append(
            {
                "name": f"off_branch_scatter[{variant}]",
                "pass": True,  # descriptive, not a pass/fail criterion
                "descriptive": True,
                "detail": (
                    f"{len(off)} off-branch point(s) in {runs} contiguous run(s) of the "
                    f"{SUPPLY_STEP * 1e3:g} mV supply axis. A real second equilibrium "
                    "appears over a contiguous supply region bounded by a bifurcation; "
                    "isolated single-step islands are a continuation-path signature"
                ),
            }
        )

    # -- do the alternative continuation paths recover the intended branch?
    for variant in ("srcstep", "nodeset"):
        pts = [r for r in results if r["role"] == "variant" and r["variant"] == variant]
        good = [r for r in pts if r["branch"] == "good"]
        out.append(
            {
                "name": f"recovers_intended_branch[{variant}]",
                "pass": True,  # descriptive: the pass/fail claim is `nonphysical[...]`
                "descriptive": True,
                "detail": (
                    f"{len(good)}/{len(pts)} of sim/bias-core-smoke/'s flagged corners land on "
                    f"the intended branch when re-solved with the `{variant}` path: "
                    + ", ".join(
                        f"{r['supply_v']:.2f} V -> VREF="
                        + ("n/a" if r["vref"] is None else f"{r['vref']:.6g}")
                        + f" V ({r['branch']})"
                        for r in pts
                    )
                ),
            }
        )

    # -- the intended branch itself: is it well-behaved across the whole supply range?
    good_sweep = [
        r for r in results if r["role"] == "sweep" and r["variant"] == "klu" and r["branch"] == "good"
    ]
    if good_sweep:
        vs = [r["vref"] for r in good_sweep]
        add(
            "good_branch_line_regulation",
            (max(vs) - min(vs)) < 0.05,
            f"across {len(good_sweep)} on-branch supply points VREF spans "
            f"{min(vs):.6g}-{max(vs):.6g} V ({(max(vs) - min(vs)) * 1e3:.3f} mV over the "
            f"{SUPPLY_LO:.2f}-{SUPPLY_HI:.2f} V range) -- one smooth branch, no second "
            "physical solution anywhere on the axis",
        )

    temp_pts = [r for r in results if r["role"] == "temp-sweep"]
    temp_off = sorted(r["temperature_c"] for r in temp_pts if r["branch"] == "off")
    out.append(
        {
            "name": "temperature_specificity",
            "pass": True,
            "descriptive": True,
            "detail": (
                f"at {TEMP_NEIGHBOURHOOD_SUPPLY:.2f} V, {len(temp_off)}/{len(temp_pts)} "
                f"temperatures in {[f'{t:g}' for t in sorted(r['temperature_c'] for r in temp_pts)]} "
                f"degC land off-branch: {[f'{t:g}' for t in temp_off]}"
            ),
        }
    )
    return out


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------


def render_record(r: dict) -> str:
    L: list[str] = []
    add = L.append
    add(f"# Record {r['record_id']}")
    add("")
    L.extend(render_record_id_experiment(r["record_id"], SLUG, TITLE))
    add(f"- **Claim**: {r['experiment']['claim']}")
    add(
        f"- **Netlist provenance**: {r['experiment']['provenance']} "
        f"(`{r['experiment']['provenance_source']}`)"
    )
    L.extend(render_pdk_tools_repo_state(r))

    m = r["matrix"]
    add("- **Corner matrix run**:")
    add(f"  - Process: `{PROCESS}` only")
    add(f"  - Temperature: {', '.join(f'{t:g} °C' for t in m['temperature_c'])}")
    add(
        f"  - Supply: {m['supply_v'][0]:.2f}–{m['supply_v'][-1]:.2f} V in "
        f"{SUPPLY_STEP * 1e3:g} mV steps ({len(m['supply_v'])} distinct values)"
    )
    add(f"  - {m['n_points']} ngspice invocation(s), one cold `.op` each")
    add(
        "  - **Deliberate non-PVT subset.** Reason: "
        + m["subset_reason"]
    )
    add(f"- **Statistical convention**: {r['experiment']['statistical_convention']}")

    add("- **Numerical variants** (same circuit, same deck body, different solve path):")
    for name in ("klu", "sparse", "srcstep", "nodeset"):
        add(f"  - `{name}`: {VARIANTS[name].description}")

    add("- **Result**:")
    for role, label in (
        ("sweep", "fine supply sweep"),
        ("temp-sweep", "temperature neighbourhood"),
        ("variant", "alternative continuation paths at the flagged corners"),
        ("control", "controls"),
    ):
        pts = [p for p in r["points"] if p["role"] == role]
        if not pts:
            continue
        add(f"  - **{label}** ({len(pts)} point(s)):")
        off = [p for p in pts if p["branch"] == "off"]
        good = [p for p in pts if p["branch"] == "good"]
        unknown = [p for p in pts if p["branch"] == "unknown"]
        for p in unknown:
            add(
                f"    - NO MEASUREMENT `{p['point_id']}`: ngspice exit "
                f"{p['ngspice_exit']}{' (TIMEOUT)' if p['timed_out'] else ''} — no "
                "operating point parsed (this fails the point's own `measured[…]` check)"
            )
        gv = [p["vref"] for p in good if p["vref"] is not None]
        gi = [p["isup"] for p in good if p["isup"] is not None]
        add(
            f"    - {len(good)} on the intended branch, {len(off)} off it"
            + (
                ""
                if not (gv and gi)
                else f" (on-branch VREF {min(gv):.6g}–{max(gv):.6g} V, supply current "
                f"{min(gi) * 1e6:.3f}–{max(gi) * 1e6:.3f} µA)"
            )
        )
        for p in off:
            node = p["worst_internal_node"]
            viol = p.get("rail_violations") or []
            vref_s = "n/a" if p["vref"] is None else f"{p['vref']:.6g}"
            isup_s = "n/a" if p["isup"] is None else f"{p['isup'] * 1e3:.4g}"
            add(
                f"    - OFF-BRANCH `{p['point_id']}`: VREF={vref_s} V vs "
                f"VDD={p['supply_v']:.2f} V, supply current {isup_s} mA, "
                f"furthest node `{node['name']}`={node['value']:.4g} V, "
                f"{len(viol)} node(s) outside the rails"
                + (
                    ""
                    if not viol
                    else " ("
                    + ", ".join(f"`{v['node']}`={v['value']:.4g} V" for v in viol[:4])
                    + ")"
                )
            )
    add("- **Checks**:")
    for c in r["checks"]:
        if c.get("descriptive"):
            add(f"  - (observation) `{c['name']}`: {c['detail']}")
        else:
            add(f"  - {'PASS' if c['pass'] else 'FAIL'} `{c['name']}`: {c['detail']}")
    failed_points = [p for p in r["points"] if not p["pass"]]
    for p in failed_points:
        for c in p["checks"]:
            if not c["pass"]:
                add(f"  - FAIL `{c['name']}`: {c['detail']}")
    add(f"  - **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")
    add(f"- **Verdict**: {r['verdict']}")

    add("- **Links**:")
    add(f"  - Testbench: `{r['links']['testbench']}`")
    add(f"  - Runner: `{r['links']['runner']}`")
    add(f"  - Netlist snapshot: `{r['links']['netlist_snapshot']}`")
    add(f"  - Raw per-point logs: `{r['links']['points_dir']}`")
    add(f"  - Machine-readable record: `{r['links']['json']}`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none)'}")
    add("")
    add(
        "Written by `sim/bias-core-op-branch/run_op_branch.py`. Append-only: never edit "
        "this file — a correction is a new record with a `Supersedes` field (see "
        "`sim/README.md`)."
    )
    add("")
    return "\n".join(L)


def verdict_text(results: list[dict], checks: list[dict]) -> str:
    off = [p for p in results if p["branch"] == "off"]
    physical_off = [
        p
        for p in off
        if not any(c["name"].startswith("nonphysical[") and c["pass"] for c in p["checks"])
    ]
    if not off:
        return (
            "No off-branch point was found at all — the artifact this experiment exists "
            "to explain did not reproduce; read the `artifact_reproduced[...]` controls "
            "before drawing any conclusion from this record."
        )
    if physical_off:
        return (
            f"REAL SECOND EQUILIBRIUM SUSPECTED: {len(physical_off)} off-branch point(s) "
            "are physically plausible (supply sources current, internal nodes inside a "
            "sane range). bias_core's startup circuit needs hardening; this is a design "
            "finding, not a solver artifact."
        )
    mitigations = []
    for variant in ("srcstep", "nodeset"):
        pts = [p for p in results if p["role"] == "variant" and p["variant"] == variant]
        good = [p for p in pts if p["branch"] == "good"]
        if pts:
            mitigations.append(f"`{variant}` recovered {len(good)}/{len(pts)}")
    return (
        f"SOLVER ARTIFACT: all {len(off)} off-branch point(s) are non-physical — each "
        "either reports the supply SINKING current from a passive network (power flowing "
        "the wrong way) or parks at least one node outside the rails by more than "
        f"{RAIL_MARGIN_V:g} V, so none of them can be a state bias_core is able to "
        "occupy. They are false "
        "convergences of the cold `.op`'s continuation path, and the branch reported "
        "moves when only the numerics change (see `solver_dependence`). Cold `.op` is "
        "therefore not a sound branch-selection characterization for this cell; the "
        "transient-from-0 V startup testbench (`sim/bias-core-startup/`) is the method "
        "that can make a branch claim. Note the weaker `.op`-side mitigations are only "
        "partial on the evidence here ("
        + "; ".join(mitigations)
        + " of the flagged corners), so a seeded `.op` is a convenience, not a "
        "substitute — and whichever method is used, keep the physicality guard "
        "(supply-current sign, rail bounds) on the measurement, since that is what "
        "catches a false convergence in the first place."
    )


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="cold-.op branch-selection diagnostic for bias_core (issue #19)"
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="coarse supply axis (100 mV) and 3 temperatures — smoke run, not evidence",
    )
    p.add_argument("--jobs", type=int, default=4, help="parallel ngspice processes")
    add_common_args(p, timeout_default=600)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']}\n"
            f"  install the pin: {pin['install_command']}\n"
            f"  or re-run with --allow-pdk-mismatch (the record will say so)"
        )

    points = build_points(args.quick)
    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = HERE / "records"
    snapshots_dir = HERE / "netlist-snapshots"
    points_dir = HERE / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"
    for path in (record_md, record_json, snapshot, points_dir):
        if path.exists():
            raise cr.HarnessError(
                f"{path} already exists — sim/ is append-only, refusing to overwrite"
            )

    run_dir = BUILD_DIR / record_id
    run_dir.mkdir(parents=True, exist_ok=True)
    netlist = cr.netlist_with_xschem(TESTBENCH, run_dir, pdk)
    body = cr.netlist_body(netlist)

    print(f"experiment      : {SLUG}")
    print(f"record id       : {record_id}")
    print(f"PDK             : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"testbench       : {TESTBENCH.relative_to(REPO_ROOT)}")
    print(f"points          : {len(points)} cold .op solves")
    print(f"scratch run dir : {run_dir}")

    if args.dry_run:
        print("\n-- point list --")
        for p in points:
            print(f"  {p.point_id:<44} role={p.role:<10} variant={p.variant}")
        print(f"\n-- deck for {points[0].point_id} --")
        print(build_deck(pdk, points[0], body))
        print("\n(dry run: nothing written under sim/<experiment>/)")
        return 0

    results: list[dict] = []
    stamp = datetime.now(timezone.utc)
    with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futures = [
            ex.submit(run_point, pdk, p, body, record_id, args.timeout) for p in points
        ]
        for i, fut in enumerate(futures, start=1):
            res = fut.result()
            point: Point = res["point"]
            evaluated = evaluate(res)
            log_path = points_dir / f"{point.point_id}.log"
            points_dir.mkdir(parents=True, exist_ok=True)
            header = [
                f"# point: {point.point_id}",
                f"# record: {record_id}",
                f"# role: {point.role} -- {point.purpose}",
                f"# variant: {point.variant} -- {VARIANTS[point.variant].description}",
                f"# process={PROCESS} temp={point.temp_c:g}C supply={point.supply_v:.2f}V",
                f"# branch: {evaluated['branch']}",
                f"# result: {'PASS' if evaluated['pass'] else 'FAIL'}",
            ]
            sections = [
                (".spiceinit (exact)", spiceinit_text(VARIANTS[point.variant])),
                ("deck (exact input given to ngspice)", res["deck"]),
            ]
            log_path.write_text(
                render_log(header, pdk, res["rc"], res["timed_out"], stamp, sections, res["raw"])
            )
            evaluated["log"] = str(log_path.relative_to(REPO_ROOT))
            results.append(evaluated)
            print(
                f"[{i:>3}/{len(points)}] {point.point_id:<46} "
                f"{'PASS' if evaluated['pass'] else 'FAIL'}  branch={evaluated['branch']:<5} "
                f"vref={'n/a' if evaluated['vref'] is None else format(evaluated['vref'], '.6g')}"
            )

    checks = cross_checks(results)
    overall = all(p["pass"] for p in results) and all(
        c["pass"] for c in checks if not c.get("descriptive")
    )

    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("\n".join(body) + "\n.end\n")

    record = {
        "record_id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "experiment": {
            "slug": SLUG,
            "title": TITLE,
            "claim": CLAIM,
            "provenance": "schematic",
            "provenance_source": str(TESTBENCH.relative_to(REPO_ROOT)),
            "statistical_convention": (
                "N/A (deterministic solves; the repeated-run control asserts that "
                "determinism rather than assuming it)"
            ),
        },
        "pdk": {
            "root": str(pdk.root),
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "pinned_commit": pin["open_pdks_commit"],
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": cr.tool_versions(),
        "git": git_info,
        "matrix": {
            "process": [PROCESS],
            "temperature_c": sorted({p.temp_c for p in points}),
            "supply_v": sorted({p.supply_v for p in points}),
            "n_points": len(points),
            "is_subset": True,
            "subset_reason": (
                "this is a solver-behaviour diagnostic at ONE process/temperature point, "
                "not a PVT claim. The full 45-point PVT matrix for this cell is "
                f"sim/bias-core-smoke/records/{SMOKE_RECORD_ID}.md (cold .op) and "
                "sim/bias-core-startup/ (transient from 0 V); this experiment deliberately "
                "trades the process axis for a 10 mV supply axis and a numerical-variant "
                "axis, which is what issue #19 asks for."
            ),
        },
        "variants": {
            name: {"klu": v.klu, "options": list(v.options), "nodeset": list(v.nodeset),
                   "description": v.description}
            for name, v in VARIANTS.items()
        },
        "points": results,
        "checks": checks,
        "overall_pass": overall,
        "verdict": verdict_text(results, checks),
        "links": {
            "testbench": str(TESTBENCH.relative_to(REPO_ROOT)),
            "runner": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "points_dir": str(points_dir.relative_to(REPO_ROOT)) + "/",
            "json": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {points_dir.relative_to(REPO_ROOT)}/")
    print(f"verdict : {record['verdict']}")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"run_op_branch: error: {err}", file=sys.stderr)
        sys.exit(1)
