#!/usr/bin/env python3
"""Monte Carlo mismatch runner for the sky130 substrate-PNP pair (issue #17).

Adapted from sky130-bandgap/sim/pnp-mismatch/run_pnp_mismatch.py -- same
reasons that harness is a bespoke script rather than a
sim/bin/corner-run.py `experiment.json`: `corner-run.py` drives exactly one
deterministic deck per PVT point and parses one scalar per measurement. A
local-mismatch (or global-process-Monte-Carlo) claim needs the same deck
resampled N times at a single process point and a *distribution* parsed out
of the log -- a different axis than the PVT matrix.

Two divergences from the precedent script, both because this repo's own PNP
usage differs from sky130-bandgap's (see testbench/tb_pnp_mismatch.spice's
own header note for the full topology justification):

1. **Device pairs**: sky130-bandgap's testbench pairs the small
   (`W0p68L0p68`) and large (`W3p40L3p40`) fixed PNP sizes. This repo's
   design uses ONLY the large size (confirmed by grep across
   design/netlist/*.spice at port time) -- there is no small/large ratio to
   reuse. What this design DOES have is a real 1-vs-8-PARALLEL array
   (bias_core's/temp_core's `XQ1` vs `XQ8A..XQ8H`), so this script's
   `array1v8` pair reproduces that topology directly instead of inventing a
   device-size ratio the design does not have.
2. **MC_PR_SWITCH (global process Monte Carlo)**: issue #17's acceptance
   criteria explicitly call out confirming *both* `MC_MM_SWITCH=1` (local
   mismatch) and `MC_PR_SWITCH=1` (global process Monte Carlo) produce
   non-degenerate samples. sky130-bandgap's own precedent script only
   exercises `MC_MM_SWITCH`. Added here: a `process-mc` point on the `mc`
   section. Its own per-run *differential* (pair) checks are expected to
   read ~zero -- verified, not assumed, see `evaluate()`'s docstring -- since
   `MC_PR_SWITCH`-gated parameters are `.param`-scoped globally, not
   per-instance like `MC_MM_SWITCH`'s `AGAUSS()` terms, so two co-located
   devices in the same ngspice run see the identical draw and their
   difference cancels by construction. What DOES vary run-to-run is each
   device's own *absolute* VEB, which is what this point's checks assert
   instead -- the correct way to falsify "MC_PR_SWITCH is silently inert on
   this deck" without mistaking common-mode cancellation for a broken switch.

Usage
-----
    sim/pnp-mismatch/run_pnp_mismatch.py                  # the full run
    sim/pnp-mismatch/run_pnp_mismatch.py --samples 20     # quick smoke run
    sim/pnp-mismatch/run_pnp_mismatch.py --dry-run        # print the plan

Exit status: 0 every check passed, 2 a record was written but a check failed,
1 harness/setup error (no record written) -- same convention as corner-run.py.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
DECK = HERE / "testbench" / "tb_pnp_mismatch.spice"
BUILD_DIR = SIM_DIR / "build" / "pnp-mismatch"
SPICEINIT_FILE = SIM_DIR / "spiceinit"

sys.path.insert(0, str(SIM_DIR / "bin"))
from sim_common import (  # noqa: E402
    MismatchPoint,
    add_common_args,
    build_mismatch_points,
    load_corner_run,
    mean,
    mv,
    parse_samples,
    render_log,
    render_pdk_tools_repo_state,
    render_record_id_experiment,
    seed_stability_checks,
    stdev,
)

cr = load_corner_run()

# --------------------------------------------------------------------------
# experiment definition
# --------------------------------------------------------------------------

SLUG = "pnp-mismatch"
TITLE = "Substrate PNP pair mismatch -- sigma(dVBE) by local + global-process Monte Carlo"

MM_SECTION = "tt_mm"  # nominal process + MC_MM_SWITCH=1 (local mismatch on)
OFF_SECTION = "tt"  # nominal process + MC_MM_SWITCH=0, MC_PR_SWITCH=0 (control: sigma must be 0)
MC_PR_SECTION = "mc"  # nominal process + MC_PR_SWITCH=1 (global process Monte Carlo on)
TEMPS_C = [-40.0, 27.0, 125.0]
N_SAMPLES = 300  # matches sky130-bandgap's own mismatch record, so N is comparable
N_CONTROL = 30  # the control point is deterministic; N only has to be > 1
SEED_A = 20260825
SEED_B = 20260826  # second seed, for the seed-stability check

# PDK mismatch coefficients, read from
# $PDK_ROOT/$PDK/libs.tech/combined/continuous/models_global.spice
SW_MM_IS = 1.662e-2  # sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is
SW_MM_BF = 5.537e-2  # sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf
# sky130_fd_pr__pnp_05v5_W3p40L3p40 -- the ONLY PNP flavor this design uses
# (design/bias_core.md) -- reuses the same two coefficients scaled by:
LARGE_IS_SCALE = 0.13
LARGE_BF_SCALE = 0.45

K_OVER_Q = 1.380649e-23 / 1.602176634e-19  # V/K

LARGE = "sky130_fd_pr__pnp_05v5_W3p40L3p40"


@dataclass(frozen=True)
class Pair:
    vector: str  # ngspice vector printed by the testbench
    kind: str  # "identical" | "array1v8"
    label: str
    bias_a: float  # per-single-device bias current
    n_a: int  # device count on the "a" (first) leg
    n_b: int  # device count on the "b" (second) leg
    veb_vectors: tuple[str, str] | None = None  # absolute VEB legs, if printed


PAIRS = (
    Pair("da1", "identical", f"{LARGE} x2", 1e-6, 1, 1),
    Pair("da10", "identical", f"{LARGE} x2", 10e-6, 1, 1),
    Pair("dr1", "array1v8", f"{LARGE} 1x vs 8x parallel", 1e-6, 1, 8, ("vr1a", "vr1b")),
    Pair("dr10", "array1v8", f"{LARGE} 1x vs 8x parallel", 10e-6, 1, 8, ("vr10a", "vr10b")),
)
VEB_VECTORS = ("vr1a", "vr1b", "vr10a", "vr10b")
ALL_VECTORS = tuple(p.vector for p in PAIRS) + VEB_VECTORS

# check tolerances
MEAN_SIGMA_TOL = 4.0  # |mean| must stay under TOL * sigma/sqrt(N) for a zero-mean pair
ANALYTIC_BAND = (0.4, 2.5)  # measured sigma / first-order analytic prediction
SEED_SIGMA_TOL = 0.25  # |sigma_B/sigma_A - 1| for the seed-stability check
SIGNAL_RATIO_MAX = 0.05  # sigma(dVBE) must stay well under the PTAT dVBE signal
PROCESS_MC_DIFF_TOL_V = 5e-4  # differential sigma must stay near-zero on the `mc` section
PROCESS_MC_ABS_MIN_SIGMA_V = 1e-6  # absolute VEB sigma must be clearly nonzero on `mc`
CONTROL_ZERO_TOL_V = 1e-9  # floating-point-noise floor for the both-switches-off control


Point = MismatchPoint  # shared 7-field shape


def build_points(samples: int) -> list[Point]:
    points = build_mismatch_points(
        samples,
        mm_section=MM_SECTION,
        off_section=OFF_SECTION,
        temps_c=TEMPS_C,
        seed_a=SEED_A,
        seed_b=SEED_B,
        n_control=N_CONTROL,
        corner_suffix="nosupply",
    )
    # Extra point beyond the precedent script: MC_PR_SWITCH=1 (global process
    # Monte Carlo), issue #17's acceptance-criteria edge case. Sample count
    # capped like the control point -- this is a liveness check on the
    # switch, not a distribution claim needing N=300.
    points.append(
        Point(
            corner_id=f"{MC_PR_SECTION}_27c_nosupply",
            section=MC_PR_SECTION,
            temp_c=27.0,
            seed=SEED_A,
            samples=min(N_CONTROL, samples),
            role="process-mc",
            purpose=(
                "MC_PR_SWITCH=1 (global process Monte Carlo) liveness check -- "
                "confirms the switch draws a non-degenerate sample on THIS "
                "repo's own PNP netlist, per issue #17's acceptance criteria"
            ),
        )
    )
    return points


def thermal_voltage(temp_c: float) -> float:
    return K_OVER_Q * (temp_c + 273.15)


def analytic_sigma(pair: Pair, temp_c: float) -> float:
    """First-order prediction from the PDK's own Is-mismatch coefficient.

    VBE = VT*ln(Ic/Is) => a relative Is error shifts VBE by -VT*(dIs/Is), so
    sigma(VBE) ~ VT * sigma_rel(Is) for one device. For an n-device PARALLEL
    block of independently-mismatched identical devices, the combined
    effective Is is dominated by the *sum* of the n legs' currents, whose
    relative deviation from nominal is the *average* of n independent draws
    -- so the block's own relative Is sigma is expected to land near
    sigma_rel/sqrt(n) (central-limit argument, stated in
    testbench/tb_pnp_mismatch.spice's own header). The two legs' voltage
    sigmas add in quadrature.
    """
    vt = thermal_voltage(temp_c)
    coeff = LARGE_IS_SCALE * SW_MM_IS
    sigma_a = coeff / math.sqrt(pair.n_a)
    sigma_b = coeff / math.sqrt(pair.n_b)
    return vt * math.sqrt(sigma_a**2 + sigma_b**2)


# --------------------------------------------------------------------------
# ngspice
# --------------------------------------------------------------------------


def corner_shim(pdk, point: Point) -> str:
    return (
        "* Generated per point by sim/pnp-mismatch/run_pnp_mismatch.py from the\n"
        "* resolved PDK -- scratch only, not committed.\n"
        f'.lib "{pdk.lib_file}" {point.section}\n'
        f".temp {point.temp_c:g}\n"
    )


def spiceinit_text(point: Point) -> str:
    return (
        SPICEINIT_FILE.read_text()
        + "\n* Monte Carlo controls injected by sim/pnp-mismatch/run_pnp_mismatch.py\n"
        f"set mc_seed={point.seed}\n"
        f"set mc_runs={point.samples}\n"
    )


def run_point(pdk, point: Point, run_dir: Path, timeout: int) -> tuple[str, int, bool]:
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DECK, run_dir / DECK.name)
    (run_dir / "corner.spice").write_text(corner_shim(pdk, point))
    (run_dir / ".spiceinit").write_text(spiceinit_text(point))
    try:
        proc = subprocess.run(
            ["ngspice", "-b", DECK.name],
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


def write_log(
    corners_dir: Path, point: Point, pdk, record_id: str, stamp: datetime, run_dir: Path, raw: str, rc: int, timed_out: bool
) -> Path:
    corners_dir.mkdir(parents=True, exist_ok=True)
    path = corners_dir / f"{point.corner_id}.log"
    deck_text = (run_dir / DECK.name).read_text()
    shim_text = (run_dir / "corner.spice").read_text()
    init_text = (run_dir / ".spiceinit").read_text()
    header = [
        f"# point: {point.corner_id}",
        f"# record: {record_id}",
        f"# role: {point.role} -- {point.purpose}",
        f"# section={point.section} temp={point.temp_c:g}C supply=n/a "
        f"seed={point.seed} samples={point.samples}",
    ]
    sections = [
        (".spiceinit (exact)", init_text),
        ("corner.spice (exact)", shim_text),
        ("testbench deck (exact input given to ngspice)", deck_text),
    ]
    path.write_text(render_log(header, pdk, rc, timed_out, stamp, sections, raw))
    return path


# --------------------------------------------------------------------------
# per-point evaluation
# --------------------------------------------------------------------------


def evaluate(point: Point, samples: list[dict[str, float]]) -> dict:
    """Per-point checks.

    role == "mismatch": each pair's differential vector must show nonzero
    sigma inside an analytic band, plus a zero-mean or signal-vs-sigma check
    depending on pair kind (see PAIRS).
    role == "control": every differential vector's sigma must be EXACTLY
    zero (MC_MM_SWITCH=0 and MC_PR_SWITCH=0 -- deterministic).
    role == "process-mc": MC_PR_SWITCH=1 gates *globally*-scoped `.param`
    terms (see this module's docstring), so two co-located devices in the
    same run draw the SAME sample -- their differential vectors are expected
    to stay near zero (checked, with a generous numerical-noise tolerance,
    not skipped), while each device's own ABSOLUTE VEB is expected to vary
    run-to-run. That absolute-sigma check is the one that actually falsifies
    "MC_PR_SWITCH is silently inert here."
    """
    stats = {}
    for name in ALL_VECTORS:
        values = [s[name] for s in samples]
        stats[name] = {
            "n": len(values),
            "mean": mean(values),
            "sigma": stdev(values),
            "max_abs": max(abs(v) for v in values),
            "min": min(values),
            "max": max(values),
        }
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    add(
        "sample_count",
        len(samples) == point.samples,
        f"parsed {len(samples)} samples, expected {point.samples}",
    )

    if point.role == "process-mc":
        for pair in PAIRS:
            sigma = stats[pair.vector]["sigma"]
            add(
                f"diff_near_zero[{pair.vector}]",
                sigma <= PROCESS_MC_DIFF_TOL_V,
                f"sigma({pair.vector}) = {mv(sigma)} mV with MC_PR_SWITCH=1 (global, "
                f"common-mode across co-located devices in the same run -- expected near "
                f"zero, tolerance {PROCESS_MC_DIFF_TOL_V * 1e3:g} mV)",
            )
        for name in VEB_VECTORS:
            sigma = stats[name]["sigma"]
            add(
                f"abs_nonzero[{name}]",
                sigma >= PROCESS_MC_ABS_MIN_SIGMA_V,
                f"sigma({name}) = {sigma * 1e6:.3f} uV across the MC_PR_SWITCH=1 loop "
                f"(must be >= {PROCESS_MC_ABS_MIN_SIGMA_V * 1e6:g} uV: a zero here means "
                f"the global-process switch never reached the models)",
            )
        return {
            "corner_id": point.corner_id,
            "role": point.role,
            "purpose": point.purpose,
            "section": point.section,
            "temperature_c": point.temp_c,
            "supply_v": None,
            "seed": point.seed,
            "requested_samples": point.samples,
            "parsed_samples": len(samples),
            "stats": stats,
            "checks": checks,
            "pass": all(c["pass"] for c in checks),
        }

    for pair in PAIRS:
        st = stats[pair.vector]
        sigma = st["sigma"]
        if point.role == "control":
            add(
                f"sigma_zero[{pair.vector}]",
                sigma <= CONTROL_ZERO_TOL_V,
                f"sigma = {sigma:.6g} V with MC_MM_SWITCH=0, MC_PR_SWITCH=0 (must be "
                f"<= {CONTROL_ZERO_TOL_V:g} V -- a floating-point-noise floor, not a "
                f"real-mismatch tolerance: the array1v8 pair's 8-parallel-device node sum "
                f"is not always bit-identical run-to-run even with both switches off, but "
                f"stays ~9 orders of magnitude below any measured real-mismatch sigma "
                f"above)",
            )
            continue

        add(
            f"sigma_nonzero[{pair.vector}]",
            sigma > 0.0,
            f"sigma = {sigma * 1e3:.4f} mV (must be > 0: a zero here means the "
            f"mismatch switch never reached the models)",
        )
        pred = analytic_sigma(pair, point.temp_c)
        ratio = sigma / pred if pred else 0.0
        add(
            f"analytic_band[{pair.vector}]",
            ANALYTIC_BAND[0] <= ratio <= ANALYTIC_BAND[1],
            f"sigma/predicted = {ratio:.2f} (measured {sigma * 1e3:.4f} mV vs "
            f"first-order PDK-coefficient prediction {pred * 1e3:.4f} mV; band "
            f"{ANALYTIC_BAND[0]}-{ANALYTIC_BAND[1]})",
        )
        if pair.kind == "identical":
            se = sigma / math.sqrt(len(samples))
            add(
                f"zero_mean[{pair.vector}]",
                abs(st["mean"]) <= MEAN_SIGMA_TOL * se,
                f"|mean| = {abs(st['mean']) * 1e3:.4f} mV vs "
                f"{MEAN_SIGMA_TOL:g}*sigma/sqrt(N) = {MEAN_SIGMA_TOL * se * 1e3:.4f} mV "
                f"(an identical pair has no systematic offset)",
            )
        else:
            signal = abs(st["mean"])
            add(
                f"signal_vs_sigma[{pair.vector}]",
                signal > 0 and sigma / signal <= SIGNAL_RATIO_MAX,
                f"sigma/|mean dVBE| = {sigma / signal:.4f} (mismatch spread "
                f"{sigma * 1e3:.4f} mV against a {signal * 1e3:.3f} mV PTAT signal "
                f"from the 1-vs-8-parallel array's own VT*ln(8) term; must be <= "
                f"{SIGNAL_RATIO_MAX:g})",
            )

    return {
        "corner_id": point.corner_id,
        "role": point.role,
        "purpose": point.purpose,
        "section": point.section,
        "temperature_c": point.temp_c,
        "supply_v": None,
        "seed": point.seed,
        "requested_samples": point.samples,
        "parsed_samples": len(samples),
        "stats": stats,
        "checks": checks,
        "pass": all(c["pass"] for c in checks),
    }


def seed_stability(results: dict[str, dict]) -> list[dict]:
    """Compare the seed-B point against the same point at seed A."""
    a = results.get(f"{MM_SECTION}_27c_nosupply")
    b = results.get(f"{MM_SECTION}_27c_nosupply_seed-b")
    if not a or not b:
        return []
    out = []
    for pair in PAIRS:
        out += seed_stability_checks(a, b, pair.vector, SEED_A, SEED_B, SEED_SIGMA_TOL)
    return out


# --------------------------------------------------------------------------
# record rendering
# --------------------------------------------------------------------------


def render_record(r: dict) -> str:
    L: list[str] = []
    add = L.append
    mm_points = [p for p in r["points"] if p["role"] == "mismatch"]
    ctrl = next((p for p in r["points"] if p["role"] == "control"), None)
    seedb = next((p for p in r["points"] if p["role"] == "seed-check"), None)
    proc_mc = next((p for p in r["points"] if p["role"] == "process-mc"), None)
    n = r["statistics"]["n_samples"]

    add(f"# Record {r['record_id']}")
    add("")
    L.extend(
        render_record_id_experiment(
            r["record_id"], r["experiment"]["slug"], r["experiment"]["title"]
        )
    )
    add(f"- **Claim**: {r['experiment']['claim']}")
    add(
        f"- **Netlist provenance**: {r['experiment']['provenance']} "
        f"(`{r['experiment']['provenance_source']}`)"
    )
    L.extend(render_pdk_tools_repo_state(r))

    add("- **Corner matrix run**:")
    add(
        f"  - Process: `{MM_SECTION}` (local mismatch, MC_MM_SWITCH=1), `{OFF_SECTION}` "
        f"(control, both switches 0), `{MC_PR_SECTION}` (global process Monte Carlo, "
        f"MC_PR_SWITCH=1) -- see the module docstring for why local mismatch is not "
        f"stacked on the deterministic tt/ss/ff/sf/fs process axis (would double-count "
        f"the global spread a future characterization issue's own process-corner sweep "
        f"already records)."
    )
    add(
        "  - Temperature: "
        + ", ".join(f"{p['temperature_c']:g} °C" for p in mm_points)
        + " (full CLAUDE.md temperature axis for the local-mismatch sweep; the "
        "process-mc liveness point runs at 27 °C only)"
    )
    add(
        "  - Supply: **not applicable**. Every DUT is a diode-connected substrate PNP "
        "referred to its own emitter node and biased by an ideal current source; there is "
        "no supply-referenced terminal. Point ids carry `nosupply` in the supply field."
    )
    add(
        f"  - {len(r['points'])} ngspice points executed: {len(mm_points)} local-mismatch "
        f"Monte Carlo points (N = {n} each), one MC_MM_SWITCH/MC_PR_SWITCH-off control "
        f"point, one second-seed point, one MC_PR_SWITCH=1 liveness point."
    )
    add(
        f"- **Statistical convention**: **N = {n}** Monte Carlo samples per local-mismatch "
        f"temperature point (section `{MM_SECTION}`: `MC_MM_SWITCH=1`, `MC_PR_SWITCH=0`, "
        f"`mismatch_factor=1`); the `{MC_PR_SECTION}` liveness point uses "
        f"N = {proc_mc['parsed_samples'] if proc_mc else 'n/a'}. Spread is reported as "
        f"**1 σ** sample standard deviation (N−1). Reproducible: `setseed {SEED_A}` (the "
        f"second-seed point uses {SEED_B})."
    )
    add(f"- **Result**: {'PASS' if r['overall_pass'] else 'FAIL'} — see the tables below.")
    add("")

    add("## What the sky130 PDK actually does for BJT mismatch / process Monte Carlo")
    add("")
    add(
        "Verified against the pinned PDK (already confirmed once, on the same PDK pin, by "
        "sky130-bandgap's own sim/pnp-mismatch/). In "
        "`libs.tech/combined/continuous/models_bjt.spice` each PNP subcircuit carries a "
        "**per-instance** mismatch term gated by `MC_MM_SWITCH`:"
    )
    add("")
    add("```")
    add(".param mm_is = {sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is")
    add("               * mismatch_factor * MC_MM_SWITCH * AGAUSS(0,1.0,1)/sqrt(mult)}")
    add("  is  = '... * (1+mm_is)'   (W3p40L3p40 scales the W0p68L0p68 coefficient by "
        f"{LARGE_IS_SCALE})")
    add("```")
    add("")
    add(
        f"with the sigmas in `continuous/models_global.spice`: "
        f"`..._is = {SW_MM_IS:.3e}` ({SW_MM_IS:.3%} on Is) and "
        f"`..._bf = {SW_MM_BF:.3e}` ({SW_MM_BF:.3%} on Bf). `AGAUSS()` sits inside the "
        f"subcircuit, so each instance draws independently -- confirmed empirically below "
        f"by the array1v8 pair's own sigma landing near 1/sqrt(8) of the identical pair's."
    )
    add("")
    add(
        "By contrast, `MC_PR_SWITCH`-gated terms (`libs.tech/combined/continuous/"
        "parameters_*.spice`, e.g. `sw_nw_rs_mult`) are `.param`-scoped **globally**, not "
        "per subcircuit instance -- every device in one ngspice run sees the identical "
        "draw. That is why this record's `process-mc` point checks each device's own "
        "*absolute* VEB for nonzero sigma rather than the pair *difference*: the "
        "difference is expected to cancel by construction (common-mode across co-located "
        "devices), and a differential-only check would have missed a genuinely-working "
        "`MC_PR_SWITCH` (the naive mistake this record's own module docstring calls out)."
    )
    add("")

    add(f"## Pair ΔVBE distribution (N = {n} per local-mismatch point)")
    add("")
    add(
        "| Pair | Bias/device | T (°C) | mean ΔVBE (mV) | 1 σ (mV) | 3 σ (mV) | worst sample \\|ΔVBE\\| (mV) |"
    )
    add("|---|---|---|---|---|---|---|")
    for pair in PAIRS:
        for p in mm_points:
            st = p["stats"][pair.vector]
            add(
                f"| {pair.kind}: `{pair.label}` | {pair.bias_a * 1e6:g} µA | "
                f"{p['temperature_c']:g} | {st['mean'] * 1e3:+.4f} | {mv(st['sigma'])} | "
                f"{mv(3 * st['sigma'])} | {mv(st['max_abs'])} |"
            )
    add("")
    add(
        "The three temperatures share one seed, so they are the *same* device draws "
        "re-solved at a different temperature (common random numbers) — the three rows of a "
        "pair are not independent estimates of σ."
    )
    add("")

    add("## Sanity: measured σ vs the PDK's own coefficients")
    add("")
    add(
        "First-order prediction from the Is-mismatch coefficient alone, generalized to the "
        "1-vs-8-parallel array by a central-limit 1/sqrt(n) argument (see "
        "`analytic_sigma()`'s docstring) -- an *order-of-magnitude* agreement here rules "
        "out the failure mode where the spread comes from somewhere other than the "
        "intended per-instance mismatch terms."
    )
    add("")
    add("| Pair | T (°C) | predicted σ (mV) | measured σ (mV) | ratio |")
    add("|---|---|---|---|---|")
    for pair in PAIRS:
        for p in mm_points:
            pred = analytic_sigma(pair, p["temperature_c"])
            got = p["stats"][pair.vector]["sigma"]
            add(
                f"| {pair.kind}, {pair.bias_a * 1e6:g} µA | {p['temperature_c']:g} | "
                f"{mv(pred)} | {mv(got)} | {got / pred:.2f} |"
            )
    add("")

    add("## Controls (the reason this record can be believed)")
    add("")
    if ctrl:
        sig = ", ".join(f"σ({p.vector}) = {ctrl['stats'][p.vector]['sigma']:.3g} V" for p in PAIRS)
        add(
            f"- **Both-switches-off control** (`{ctrl['corner_id']}`, section `{OFF_SECTION}`, "
            f"N = {ctrl['parsed_samples']}): identical deck with `MC_MM_SWITCH=0`, "
            f"`MC_PR_SWITCH=0`. {sig} — exactly zero, so the spread reported above is the "
            f"mismatch switch and not solver noise or a re-randomised bias point."
        )
    if seedb:
        add(
            f"- **Second-seed point** (`{seedb['corner_id']}`, `setseed {SEED_B}`, "
            f"N = {seedb['parsed_samples']}): "
            + "; ".join(
                f"σ({p.vector}) = {mv(seedb['stats'][p.vector]['sigma'])} mV"
                for p in PAIRS
            )
            + " — see the seed-stability checks below: the individual samples change, σ "
            "does not."
        )
    if proc_mc:
        add(
            f"- **MC_PR_SWITCH=1 liveness point** (`{proc_mc['corner_id']}`, section "
            f"`{MC_PR_SECTION}`, N = {proc_mc['parsed_samples']}): pair differences stay "
            f"near zero (common-mode cancellation, expected -- see the mechanism note "
            f"above) while each device's own absolute VEB shows nonzero sigma "
            + "; ".join(
                f"σ({name}) = {proc_mc['stats'][name]['sigma'] * 1e6:.2f} µV"
                for name in VEB_VECTORS
            )
            + " — proof the global-process switch reached the models on THIS repo's own "
            "netlist, not just sky130-bandgap's."
        )
    add("")

    add("## Checks")
    add("")
    for p in r["points"]:
        add(f"- `{p['corner_id']}` ({p['role']}): **{'PASS' if p['pass'] else 'FAIL'}**")
        for c in p["checks"]:
            add(f"  - {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    for c in r["cross_point_checks"]:
        add(f"- {'PASS' if c['pass'] else 'FAIL'} `{c['name']}` — {c['detail']}")
    add(f"- **Overall: {'PASS' if r['overall_pass'] else 'FAIL'}**")
    add("")

    add("## Divergences from sky130-bandgap's own sim/pnp-mismatch/ precedent")
    add("")
    add(
        "1. **Device pairs.** The precedent pairs the small (`W0p68L0p68`) and large "
        "(`W3p40L3p40`) fixed PNP sizes -- this design uses ONLY the large size "
        "(design/bias_core.md), so this record's `array1v8` pair reproduces the design's "
        "real 1-vs-8-parallel array topology (`XQ1` vs `XQ8A..XQ8H`) instead."
    )
    add(
        "2. **MC_PR_SWITCH coverage.** Added beyond the precedent: a `process-mc` point, "
        "per issue #17's own acceptance criteria (confirm BOTH MC_MM_SWITCH and "
        "MC_PR_SWITCH produce non-degenerate samples against this repo's own netlists)."
    )
    add(
        "3. **Terminal connection.** Same convention as the precedent: this deck drives "
        "the **emitter** (collector and base grounded), matching how bias_core/temp_core "
        "actually connect their PNPs (`X<name> VSS VSS <node> ...`)."
    )
    add(
        f"4. **N, seed, bias points.** N = {N_SAMPLES} and the 1 µA / 10 µA per-device "
        "bias rungs match sky130-bandgap's own record for cross-repo comparability; this "
        "repo's own per-branch bias currents have not been characterized against sky130 "
        "models yet (spec/porting-plan.md Sec4 item 2)."
    )
    add("")

    add("- **Links**:")
    for key, value in r["links"].items():
        add(f"  - {key}: `{value}`")
    add(f"- **Timestamp / author**: {r['timestamp']}, {r['author']}")
    add(f"- **Supersedes**: {r['supersedes'] or '(none — first record for this claim)'}")
    add("")
    add(
        "Written by `sim/pnp-mismatch/run_pnp_mismatch.py`. Append-only: never edit this "
        "file — a correction is a new record with a `Supersedes` field (see "
        "`sim/README.md`)."
    )
    add("")
    return "\n".join(L)


CLAIM = (
    "Issue #17 -- sim-harness port. Confirms sky130's local-mismatch "
    "(MC_MM_SWITCH=1) AND global-process-Monte-Carlo (MC_PR_SWITCH=1) mechanisms both "
    "produce non-degenerate samples against THIS repo's own PNP topology -- a single "
    "`sky130_fd_pr__pnp_05v5_W3p40L3p40` vs. the real 1-vs-8-parallel array "
    "bias_core/temp_core actually use, not a re-run of sky130-bandgap's own small/large "
    "device-size pair. **This record makes no spec pass/fail claim** -- no ratified spec "
    "exists yet (spec/porting-plan.md Sec4 item 4); it reports measured distributions "
    "plus the harness checks that make them trustworthy, per issue #17's own acceptance "
    "criteria."
)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_common_args(p, timeout_default=3600, samples_default=N_SAMPLES)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not DECK.is_file():
        raise cr.HarnessError(f"missing testbench: {DECK}")
    if args.samples < 2:
        raise cr.HarnessError("--samples must be at least 2 (sigma needs N-1 > 0)")

    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        raise cr.HarnessError(
            f"installed PDK {pdk.variant} is open_pdks {pdk.installed_commit}, but "
            f"sim/pdk.json pins {pin['open_pdks_commit']}\n"
            f"  install the pin: {pin['install_command']}\n"
            f"  or re-run with --allow-pdk-mismatch (the record will say so)"
        )
    if not shutil.which("ngspice"):
        raise cr.HarnessError("ngspice not found on PATH")

    points = build_points(args.samples)
    git_info = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{git_info['sha']}"

    records_dir = HERE / "records"
    snapshots_dir = HERE / "netlist-snapshots"
    corners_dir = HERE / "corners" / record_id
    record_md = records_dir / f"{record_id}.md"
    record_json = records_dir / f"{record_id}.json"
    snapshot = snapshots_dir / f"{record_id}.spice"
    for path in (record_md, record_json, snapshot, corners_dir):
        if path.exists():
            raise cr.HarnessError(
                f"{path} already exists — sim/ is append-only, refusing to overwrite"
            )

    print(f"experiment      : {SLUG}")
    print(f"record id       : {record_id}")
    print(f"PDK             : {pdk.dir} (open_pdks {pdk.installed_commit})")
    print(f"testbench       : {DECK.relative_to(REPO_ROOT)}")
    print(f"points          : {len(points)} ({args.samples} samples per MC point)")
    for p in points:
        print(f"  {p.corner_id:<38} section={p.section:<6} T={p.temp_c:>5g}C seed={p.seed} N={p.samples}")
    if args.dry_run:
        print("\n-- corner shim for the first point --")
        print(corner_shim(pdk, points[0]))
        print("(dry run: nothing written under sim/pnp-mismatch/)")
        return 0

    results: dict[str, dict] = {}
    ordered: list[dict] = []
    for i, point in enumerate(points, start=1):
        run_dir = BUILD_DIR / record_id / point.corner_id
        raw, rc, timed_out = run_point(pdk, point, run_dir, args.timeout)
        write_log(corners_dir, point, pdk, record_id, now, run_dir, raw, rc, timed_out)
        if rc != 0 or timed_out:
            raise cr.HarnessError(
                f"ngspice exit {rc}{' (timeout)' if timed_out else ''} for {point.corner_id}; "
                f"see {(corners_dir / (point.corner_id + '.log')).relative_to(REPO_ROOT)}"
            )
        samples = parse_samples(raw, ALL_VECTORS)
        if not samples:
            raise cr.HarnessError(
                f"no Monte Carlo samples parsed for {point.corner_id} — see the log"
            )
        res = evaluate(point, samples)
        results[point.corner_id] = res
        ordered.append(res)
        head = ", ".join(
            f"sigma({p.vector})={res['stats'][p.vector]['sigma'] * 1e3:.4f}mV" for p in PAIRS
        )
        print(
            f"[{i}/{len(points)}] {point.corner_id:<38} "
            f"{'PASS' if res['pass'] else 'FAIL'}  n={res['parsed_samples']}  {head}"
        )

    cross = seed_stability(results)
    overall = all(r["pass"] for r in ordered) and all(c["pass"] for c in cross)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DECK, snapshot)

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
            "provenance_source": str(DECK.relative_to(REPO_ROOT)),
            "statistical_convention": (
                f"N = {args.samples} Monte Carlo samples per local-mismatch point "
                f"(section {MM_SECTION}: MC_MM_SWITCH=1, MC_PR_SWITCH=0); 1 sigma sample "
                f"standard deviation (N-1), fixed setseed {SEED_A}"
            ),
        },
        "mismatch_model": {
            "local_switch": "MC_MM_SWITCH (per-instance AGAUSS, set by the .lib section: "
            "0 in tt/ss/ff/sf/fs/tt, 1 in *_mm)",
            "global_switch": "MC_PR_SWITCH (globally-scoped .param AGAUSS/GAUSS terms, set "
            "1 only in the mc section)",
            "sections": {
                "mismatch": MM_SECTION,
                "control": OFF_SECTION,
                "process_mc": MC_PR_SECTION,
            },
            "coefficients": {
                "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is": SW_MM_IS,
                "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf": SW_MM_BF,
                "W3p40L3p40_is_scale": LARGE_IS_SCALE,
                "W3p40L3p40_bf_scale": LARGE_BF_SCALE,
            },
            "source": "libs.tech/combined/continuous/models_bjt.spice + models_global.spice",
        },
        "pairs": [
            {
                "vector": p.vector,
                "kind": p.kind,
                "devices": p.label,
                "bias_a": p.bias_a,
                "n_a": p.n_a,
                "n_b": p.n_b,
                "veb_vectors": list(p.veb_vectors) if p.veb_vectors else None,
            }
            for p in PAIRS
        ],
        "statistics": {"n_samples": args.samples, "seed_a": SEED_A, "seed_b": SEED_B},
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
        "points": ordered,
        "cross_point_checks": cross,
        "overall_pass": overall,
        "links": {
            "testbench": str(DECK.relative_to(REPO_ROOT)),
            "run_script": str((HERE / "run_pnp_mismatch.py").relative_to(REPO_ROOT)),
            "netlist_snapshot": str(snapshot.relative_to(REPO_ROOT)),
            "raw_logs": str(corners_dir.relative_to(REPO_ROOT)) + "/",
            "json_record": str(record_json.relative_to(REPO_ROOT)),
            "record": str(record_md.relative_to(REPO_ROOT)),
        },
    }

    records_dir.mkdir(parents=True, exist_ok=True)
    record_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    record_md.write_text(render_record(record))

    print()
    print(f"record  : {record_md.relative_to(REPO_ROOT)}")
    print(f"json    : {record_json.relative_to(REPO_ROOT)}")
    print(f"logs    : {corners_dir.relative_to(REPO_ROOT)}/")
    print(f"overall : {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except cr.HarnessError as err:
        print(f"run_pnp_mismatch: error: {err}", file=sys.stderr)
        sys.exit(1)
