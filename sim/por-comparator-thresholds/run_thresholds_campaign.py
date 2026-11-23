#!/usr/bin/env python3
"""Driver for the por_comparator VPOR-up / VPOR-down / hysteresis campaign (issue #102).

The process x temperature grid is expressed as ``klt sim`` requests (one request
per sweep rate and bias variant; process and temperature are klt's own corner
axes) and goes to the Spot batch fleet.  This script never launches ngspice over
a grid itself.  The sweep-rate axis is a ``.param rate`` written into one
generated netlist per request, not an extension of sim/bin/corner-run.py.

Stages (each is a subcommand):

  run      build netlists + requests, submit them to the fleet (explicit
           ``--backend batch``); raw outputs stay under sim/build/.
           --axis mc submits the mismatch Monte Carlo supplement instead
           (one request per (process, temperature), N mismatch samples each).
  probe    ONE single-corner LOCAL run (``--backend local``): a debug probe /
           cross-check of the fleet result; never a grid.
  record   extract the edges from every retrieved waveform
           (threshold_extractor.py) and write the append-only evidence:
           netlist snapshots, per-point logs, change-triggered traces,
           markdown + JSON record.  An mc run writes the mismatch-distribution
           record (per-corner mean/sigma, per-sample hysteresis) instead.
  selftest run the extractor on synthetic sweeps with known answers.

A batch submit failure is reported in the record; there is no local fallback.
"""

from __future__ import annotations

import argparse
import functools
import gzip
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(HERE))

import evidence_store  # noqa: E402
import sim_common  # noqa: E402
import threshold_extractor as tx  # noqa: E402

cr = sim_common.load_corner_run()

SLUG = "por-comparator-thresholds"
MANIFEST = HERE / "experiment.json"
BUILD = REPO_ROOT / "sim" / "build" / SLUG
NETLIST_DIR = REPO_ROOT / "design" / "netlist"
MODEL_LIB = sim_common.MODEL_LIB


say = sim_common.say
rate_tag = sim_common.rate_tag
scrub = functools.partial(sim_common.scrub, repo_root=REPO_ROOT)


def corner_id(proc: str, temp: float) -> str:
    return f"{proc}_{cr.fmt_temp(temp)}c"


AXES = ("main", "passive-skew", "mc")


def processes(man: dict, axis: str) -> list[str]:
    """Process sections of one corner axis.  'main' = the 5 MOS corners (the issue's 5x3 grid);
    'passive-skew' = the ll/hh resistor/capacitor sections (tt MOS), a separately-recorded supplement;
    'mc' = the mismatch Monte Carlo sections (the `_mm` libraries, real-bias-core only, issue #348)."""
    if axis == "mc":
        return man["monte_carlo"]["process"]
    return man["corners"]["process"] if axis == "main" else man["corners"]["passive_skew"]["process"]


def all_rates(man: dict) -> list[tuple[float, float | None]]:
    """[(rate, primary_or_None)]: each primary rate followed by its half-rate guard."""
    f = man["rates"]["half_rate_guard_factor"]
    out = []
    for r in man["rates"]["primary_v_per_s"]:
        out += [(r, None), (r * f, r)]
    return out


def tstop_for(rate: float, man: dict) -> float:
    return 2 * man["sweep"]["peak_v"] / rate


# --------------------------------------------------------------------------
# mismatch Monte Carlo supplement (issue #348; --axis mc)
# --------------------------------------------------------------------------


def mc_effective(man: dict, meta_mc: dict | None = None) -> dict:
    """The monte_carlo block this run/record uses: manifest defaults, overridden by the
    run's recorded overrides (issue #455: the fresh-seed tt/ss/ff/sf/fs campaign must be
    a separately-recorded axis without re-editing the shared manifest between run and
    record).  Returns a copy; the manifest itself is never mutated."""
    mc = dict(man["monte_carlo"])
    if meta_mc:
        if meta_mc.get("process_override"):
            mc["process"] = list(meta_mc["process_override"])
        if meta_mc.get("seed_override") is not None:
            mc["seed"] = int(meta_mc["seed_override"])
    return mc


def mc_units(man: dict, mc: dict | None = None) -> list[tuple[str, float, int]]:
    """[(process, temperature, seed_offset)]: one klt request per (process, temperature), never a bigger grid.

    Request sizing (recorded in experiment.json monte_carlo.request_sizing): the measured
    worst-corner cost of the real-bias-core 100 V/s grid is 142 s
    (corners/20261009-054331-79eebd4-real-bias-core/r100/klt-report.json, per-corner
    runtime_s), so one request holds N x 142 s of serial fleet wall clock: N = 20 ->
    2840 s, 21% under the fleet's 3600 s per-job ceiling.  Folding the three temperatures
    into one request would be 60 x 142 s = 8520 s -> batch_job_timeout, the exact failure
    temp-core-accuracy-mc recorded for its first 3000-unit requests.

    The seed offset is distinct per request because klt derives each sample's seed from
    the corner index, which is 0 inside every one-corner request here: a shared base seed
    would re-draw the SAME realisations in all six requests, silently halving the
    effective N behind a full-N claim.  Offset = 1 + index in (process x temperature)
    order, so the six realisation sets are distinct and the mapping is stated in the
    record.
    """
    mc = mc or man["monte_carlo"]
    return [(p, t, i + 1) for i, (p, t) in enumerate((p, t) for p in mc["process"] for t in mc["temperature_c"])]


def mc_request_seed(mc: dict, offset: int) -> int:
    return mc["seed"] + offset


def build_mc_request(proc: str, temp: float, offset: int, mc: dict, man: dict, backend: str, capacity_wait_s: float = 0) -> dict:
    """ONE mismatch Monte Carlo request: one `_mm` process section, one temperature, N mismatch samples.

    The `_mm` .lib section turns on the model library's local-mismatch sigmas and klt's
    `monte_carlo` block (vary=mismatch) re-runs the single corner point N times with
    per-sample seeds derived from `seed`.  Local mismatch only -- this is never
    MC_PR_SWITCH global process Monte Carlo."""
    sw = man["sweep"]
    rate = mc["rate_v_per_s"]
    tstop = tstop_for(rate, man)
    return sim_common.base_request(
        "netlist.spice", backend,
        {"process": [f"{proc}_mm"], "supply_v": {"vset": [sw["peak_v"]]}, "temperature_c": [temp]},
        # Issue #474: the supply starts at a physical 0 V, so every node starts at 0 V; `uic` starts the
        # transient from that state instead of a DC operating point that fails to converge on some cold draws.
        {"kind": "tran", "args": f"1u {tstop:.9g} 0 {sw['tmax_s']:.3g}" + (" uic" if mc.get("tran_uic") else "")},
        [
            {"name": "vdd_end", "spice": f".meas tran vdd_end FIND v(vdd) AT={tstop - 1e-6:.9g}", "unit": "V"},
            {"name": "por_raw_max", "spice": ".meas tran por_raw_max MAX v(por_raw)", "unit": "V"},
        ],
        1500, capacity_wait_s,
        monte_carlo={"n": mc["n_per_corner"], "seed": mc_request_seed(mc, offset), "vary": mc["vary"]},
    )


def mc_dir(run_dir: Path, variant_name: str, proc: str, temp: float) -> Path:
    """One MC request's directory, under the run dir next to the rate-tag dirs the main axis uses."""
    return run_dir / variant_name / f"mc_{proc}_{cr.fmt_temp(temp)}c"


def submit_mc(unit: tuple[str, float, int], variant_name: str, head: str, mc: dict, man: dict, run_dir: Path, capacity_wait_s: float) -> dict:
    proc, temp, offset = unit
    netlist = build_netlist(head, man["variants"][variant_name], mc["rate_v_per_s"])
    req = build_mc_request(proc, temp, offset, mc, man, "batch", capacity_wait_s)
    d = mc_dir(run_dir, variant_name, proc, temp)
    label = f"{proc}/{cr.fmt_temp(temp)}C"
    res = sim_common.submit_prepared(
        d, netlist, req,
        f"{variant_name} mc {label}: N={mc['n_per_corner']} mismatch samples, seed {req['monte_carlo']['seed']} -> batch fleet",
        f"{variant_name} mc {label}")
    return {"variant": variant_name, "process": proc, "temperature_c": temp,
            "seed_offset": offset, "seed": req["monte_carlo"]["seed"], **res}


# --------------------------------------------------------------------------
# netlists and requests
# --------------------------------------------------------------------------


def tb_netlist_head(variant: dict, run_dir: Path, pdk) -> str:
    """Netlist the variant's testbench schematic with xschem; keep only the testbench part."""
    return sim_common.netlist_tb_head(HERE / variant["schematic"], run_dir / "tb" / variant["schematic"].split("/")[-1][:-4], pdk)


def build_netlist(head: str, variant: dict, rate: float) -> str:
    dut = ""
    for name in variant["dut_netlists"]:
        # bare name = design/netlist export; a path with "/" is repo-relative (post-layout extracted DUT, issue #124)
        txt = ((REPO_ROOT / name) if "/" in name else (NETLIST_DIR / name)).read_text()
        dut += sim_common.drop_end(txt)
    banner = (
        f"* {SLUG}: generated by sim/{SLUG}/run_thresholds_campaign.py -- do not edit\n"
        f"* sweep rate (V/s, up and down): {rate:g}\n"
        f".param rate={rate:g}\n"
        "* ng_nomodcheck: same setting as sim/spiceinit; carried in the netlist because the\n"
        "* fleet runner ignores options.ngspice_init (see experiment.json ngspice_note)\n"
        + sim_common.NOMODCHECK_CONTROL
    )
    return banner + head + "\n" + dut


def build_request(rate: float, man: dict, backend: str, corners: dict | None = None, capacity_wait_s: float = 0, axis: str = "main") -> dict:
    sw = man["sweep"]
    tstop = tstop_for(rate, man)
    c = man["corners"]
    return sim_common.base_request(
        "netlist.spice", backend,
        corners
        or {
            "process": processes(man, axis),
            "supply_v": {"vset": [sw["peak_v"]]},
            "temperature_c": c["temperature_c"],
        },
        {"kind": "tran", "args": f"1u {tstop:.9g} 0 {sw['tmax_s']:.3g}"},
        [
            {"name": "vdd_end", "spice": f".meas tran vdd_end FIND v(vdd) AT={tstop - 1e-6:.9g}", "unit": "V"},
            {"name": "por_raw_max", "spice": ".meas tran por_raw_max MAX v(por_raw)", "unit": "V"},
        ],
        1500, capacity_wait_s,
    )


def submit(variant_name: str, rate: float, head: str, man: dict, run_dir: Path, capacity_wait_s: float, axis: str = "main") -> dict:
    netlist = build_netlist(head, man["variants"][variant_name], rate)
    req = build_request(rate, man, "batch", capacity_wait_s=capacity_wait_s, axis=axis)
    points = len(processes(man, axis)) * len(man["corners"]["temperature_c"])
    return sim_common.submit_request(variant_name, rate, run_dir, netlist, req, f" ({axis})", points)


def cmd_run(args) -> int:
    evidence_store.preflight_or_exit()  # fail closed before anything is submitted
    man = sim_common.load_manifest(MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    git_info = cr.git_state()
    sim_common.refuse_unsubmittable(git_info, args.allow_dirty)
    run_id, run_dir, now = sim_common.open_run(
        BUILD, args.run_id, git_info["sha"], reuse="allow" if args.retry_failed else None)
    axis = args.axis
    if args.retry_failed and (run_dir / "run.json").is_file():
        axis = json.loads((run_dir / "run.json").read_text()).get("axis", "main")  # a retry keeps the run's own axis
    if axis == "mc":
        if args.variant:
            raise SystemExit("--axis mc runs only the monte_carlo.variant (real-bias-core); drop --variant")
        variants = [man["monte_carlo"]["variant"]]
        mc = mc_effective(man, {"process_override": args.mc_process, "seed_override": args.mc_seed})
        work = list(mc_units(man, mc))
        if args.retry_failed:
            work = [(p, t, o) for p, t, o in work
                    if not sim_common.report_usable(mc_dir(run_dir, variants[0], p, t) / "report.json")]
    else:
        variants = args.variant or [v for v in man["variants"] if not v.endswith("-postlayout")]  # post-layout variants only on explicit --variant
        mc = None
        work = [(v, r) for v in variants for r, _ in all_rates(man)]
        if args.retry_failed:
            work = [(v, r) for v, r in work if not sim_common.report_usable(run_dir / v / rate_tag(r) / "report.json")]
    heads = {v: tb_netlist_head(man["variants"][v], run_dir / ("retry" if args.retry_failed else "."), pdk) for v in variants}
    meta = {
        "run_id": run_id,
        "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variants": variants,
        "axis": axis,
        "process": mc["process"] if axis == "mc" else processes(man, axis),
        "git": git_info,
        "klt_client": sim_common.klt_version(),
        "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"),
        "work": [list(item) for item in work],
    }
    if axis == "mc":
        meta.update({
            "monte_carlo": {"n_per_corner": mc["n_per_corner"], "seed": mc["seed"], "vary": mc["vary"],
                            "rate_v_per_s": mc["rate_v_per_s"], "variant": variants[0],
                            "process_override": args.mc_process or None,
                            "seed_override": args.mc_seed,
                            "requests": [{"process": p, "temperature_c": t, "seed_offset": o, "seed": mc_request_seed(mc, o)} for p, t, o in mc_units(man, mc)],
                            "request_sizing": mc["request_sizing"]},
        })
    n_units = (f"{len(work)} requests x N={mc['n_per_corner']} mismatch samples"
               if axis == "mc" else f"{len(work)} request(s)")
    say(f"run id {run_id}: {n_units}")
    if axis == "mc":
        results = sim_common.fan_out(
            lambda u: submit_mc(u, variants[0], heads[variants[0]], mc, man, run_dir, args.wait_for_capacity), work, args.jobs)
    else:
        results = sim_common.fan_out(
            lambda vr: submit(vr[0], vr[1], heads[vr[0]], man, run_dir, args.wait_for_capacity, axis), work, args.jobs)
    meta["submit_results"] = results
    path = run_dir / ("run.retry.json" if args.retry_failed else "run.json")
    path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def cmd_probe(args) -> int:
    """One single-corner LOCAL run (debug probe / cross-check)."""
    man = sim_common.load_manifest(MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    variant = args.variant
    rate = args.rate or man["rates"]["primary_v_per_s"][0]
    run_dir = BUILD / (args.run_id or "probe")
    d = run_dir / "probe" / f"{variant}_{rate_tag(rate)}_{args.process}_{cr.fmt_temp(args.temp)}c"
    d.mkdir(parents=True, exist_ok=True)
    head = tb_netlist_head(man["variants"][variant], d, pdk)
    (d / "netlist.spice").write_text(build_netlist(head, man["variants"][variant], rate))
    req = build_request(
        rate, man, "local",
        corners={"process": [args.process], "supply_v": {"vset": [man["sweep"]["peak_v"]]}, "temperature_c": [args.temp]},
    )
    req["options"]["ngspice_init"] = sim_common.spiceinit_lines(SIM_DIR)
    (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
    say(f"[probe] one local corner {args.process}/{args.temp}C, {rate:g} V/s, variant {variant}")
    p = sim_common.run_local_probe(d)
    print(f"exit {p.returncode}; report {d / 'report.json'}")
    try:
        rep = json.loads(p.stdout)
        for c in rep.get("corners", []):
            art = c.get("artifacts") or {}
            if art.get("waveform"):
                res = tx.analyze(sim_common.load_wave(Path(art["waveform"])), man["polarity"]["up"], man["polarity"]["down"])
                print(json.dumps({k: res.get(k) for k in ("verdict", "hysteresis_v", "max_vdd_step_v")}, indent=1))
                print("up:", {k: v for k, v in res["up"].items() if k != "edges"})
                print("down:", {k: v for k, v in res["down"].items() if k != "edges"})
    except Exception as err:  # noqa: BLE001
        print("could not analyze probe:", err)
    return 0


# --------------------------------------------------------------------------
# mismatch Monte Carlo statistics reduction (pure; selftest test_mc_statistics.py pins it)
# --------------------------------------------------------------------------


def sigma_resolution(n: int) -> float | None:
    """Relative standard error of a sigma estimated from n samples: 1/sqrt(2(N-1)) (~16% at N = 20).

    Stated as a number in the record, never as prose.  None when fewer than two valid
    samples carry it: the resolution of a sigma that could not be computed is not a
    number either."""
    return 1.0 / math.sqrt(2 * (n - 1)) if n >= 2 else None


def classify_mc_sample(extract: dict | None) -> tuple[bool, str | None]:
    """(valid, exclusion reason) for one MC sample's extractor verdict.

    A sample enters the statistics only with a clean, single, correctly-directed pair of
    edges (verdict OK, hysteresis computed).  A sample graded no_transition,
    multiple_transitions, unresolved or wrong_direction is excluded AND counted via the
    verdict text -- never silently dropped, never folded into a 0 sigma."""
    if extract is None:
        return False, "no waveform retrieved"
    if extract.get("verdict") == "OK" and extract.get("hysteresis_v") is not None:
        return True, None
    return False, extract.get("verdict") or "unextractable waveform"


# Enable/clamp-path diagnostic reduction (issue #401): the netlist already saves
# v(bias_ok) and the comparator-internal nodes; these fields keep them per sample
# instead of discarding them at reduction time, so a failed-release ("no_transition")
# realisation can be attributed to a mechanism from data.
# The v(xbias.*) nodes (issue #455) instrument the OK-detector itself: the input pair's
# gates (NA vs NBTOP -- the R_T drop is the whole settle signal), the TOK tail source,
# the mirror diode (NOKL) and its output (NOKO), the NOKX output-stage node and the
# start-up clamp gate (NKG).  They are conditionally consumed exactly like the others:
# a netlist that does not save them simply reports no fields, never zeros.
MC_DIAG_NODES = (
    "v(bias_ok)", "v(xdut.cmpo)", "v(xdut.n1)", "v(xdut.sns)",
    "v(xbias.na)", "v(xbias.nbtop)", "v(xbias.pb)", "v(xbias.tok)",
    "v(xbias.noko)", "v(xbias.nokl)", "v(xbias.nokx)", "v(xbias.nkg)",
)
# Diagnostic classification criteria -- labels on recorded evidence, never thresholds:
# the raw per-sample values are recorded beside every label, so the classification can
# be re-derived from the record without agreeing with the criterion.
# BIAS_OK is bias_core's rail-swing OK output, but it ALSO follows VDD through the weak
# XMO1P pullup whenever NOKX has not turned XMO1N on, so "ever above an absolute level"
# is not an assertion test.  Asserted AT THE PEAK means the at-peak level is a rail
# swing: >= MC_BIAS_OK_ASSERTED_FRAC of the at-peak supply (measured 0.9998 on the
# healthy tt/27C probe; a never-asserted sample holds near 0 against the XMO1N pulldown).
MC_BIAS_OK_ASSERTED_FRAC = 0.9
MC_CMPO_RELEASED_V = 0.5  # CMPO held at VSS by XMDCMPO vs swung toward the VDDA load rail


def mc_diag_fields(wave: dict, tpeak_s: float) -> dict:
    """Per-sample diagnostic fields of the enable/clamp path, from one sample's waveform.

    For each saved node: the sweep max (did it ever get there?) and the value at the
    sweep peak (t = tstop/2, where VDD tops out at its 3.63 V peak), linearly
    interpolated at that time.  `vdd_at_peak_v` is the at-peak supply itself, so the
    BIAS_OK assertion criterion can be stated relative to the actual peak (mismatch or
    not, the sweep peaks at 3.63 V by construction).  Nodes the netlist does not save
    are simply absent -- never invented as 0.  Field names lowercase the node with
    `.` -> `_` (`v(xdut.cmpo)` -> `xdut_cmpo_max_v` / `xdut_cmpo_at_peak_v`)."""
    out: dict = {}
    if "time" not in wave:
        return out
    if "v(vdd)" in wave:
        out["vdd_at_peak_v"] = sim_common.interp_at(wave["time"], wave["v(vdd)"], tpeak_s)
    for col in MC_DIAG_NODES:
        if col not in wave:
            continue
        key = col[2:-1].replace(".", "_")  # strip "v(" ... ")"; flatten subcircuit dots
        out[f"{key}_max_v"] = max(wave[col])
        out[f"{key}_at_peak_v"] = sim_common.interp_at(wave["time"], wave[col], tpeak_s)
    return out


def mc_stuck_class(diag: dict | None) -> str | None:
    """Mechanism class of ONE failed-release realisation, from its diagnostic fields.

    `enable-clamp`: BIAS_OK never asserted -- at the sweep peak its level is not a rail
    swing (below MC_BIAS_OK_ASSERTED_FRAC of the at-peak supply), so BIAS_OKB stayed
    high, XMDCMPO kept CMPO pulled to VSS and XMENSRC kept the load supply VDDA
    disconnected: the comparator never had a chance, whatever its inputs did (the
    issue's leading candidate).  `comparator-stuck`: BIAS_OK asserted (clamp released)
    yet CMPO never rose -- the comparator's own bias/tail path held the output low,
    refuting the enable-path candidate for that realisation.  `extractor-miss`: BIAS_OK
    asserted AND CMPO rose, yet the sweep was graded no_transition -- a contradiction
    against the extractor, flagged, never folded away.  None when the diagnostic data is
    missing: absence of evidence is not evidence of any mechanism."""
    if not diag or diag.get("bias_ok_at_peak_v") is None or diag.get("vdd_at_peak_v") is None:
        return None
    if diag["bias_ok_at_peak_v"] < MC_BIAS_OK_ASSERTED_FRAC * diag["vdd_at_peak_v"]:
        return "enable-clamp"
    cmpo_max = diag.get("xdut_cmpo_max_v")
    if cmpo_max is None:
        return None
    if cmpo_max < MC_CMPO_RELEASED_V:
        return "comparator-stuck"
    return "extractor-miss"


# OK-detector sub-attribution (issue #455): WHERE inside the enable path an
# `enable-clamp` realisation is stuck, from the xbias.* nodes.  The levels below are
# diagnostic labels on recorded evidence (the raw per-sample values sit beside every
# label in the record), measured against the healthy tt/27C operating point
# (TOK 1.96 V, NOKL 0.75 V, NOKO 1.50 V, NOKX 1.8 mV, NKG ~0 V) and the devices'
# threshold magnitudes, not against any spec.
MC_TOK_PRESENT_V = 1.0     # TOK (XMPOK tail source) is delivering headroom
MC_NOKO_DRIVEN_V = 0.5     # NOKO high enough that XMOK2 can conduct (> |Vth|)
MC_NOKX_LOW_V = 0.5        # NOKX discharged (output stage won the ratio fight)
MC_NKG_LOW_V = 0.1         # start-up clamp XMOKC off (XKICK holding NKG down)


def mc_okdet_subclass(diag: dict | None) -> str | None:
    """Sub-mechanism of ONE `enable-clamp` realisation, inside bias_core's OK-detector.

    `first-stage-unbalanced` (the dominant candidate): TOK is present and the clamp is
    off, yet NOKO never rose -- the XMOKA/XMOKB pair + XML1/XML2 mirror stage never
    delivered net current to NOKO, i.e. the mismatch offset of that stage exceeded the
    R_T settle signal.  `output-stage-fight`: NOKO rose but NOKX never discharged --
    XMOK2 vs XMOK2P lost the ratio fight (the issue's alternative candidate).  `tok-
    collapsed`: the XMPOK tail source never delivered headroom.  `clamp-on`: the
    start-up clamp (NKG/XMOKC) was still holding NOKO down.  None when the xbias.*
    nodes were not saved -- the coarse `stuck_class` still applies."""
    if not diag or diag.get("xbias_tok_at_peak_v") is None:
        return None
    tok = diag["xbias_tok_at_peak_v"]
    nkg = diag.get("xbias_nkg_at_peak_v")
    noko = diag.get("xbias_noko_at_peak_v")
    nokx = diag.get("xbias_nokx_at_peak_v")
    if tok is None or noko is None or nokx is None:
        return None
    if tok < MC_TOK_PRESENT_V:
        return "tok-collapsed"
    if nkg is not None and nkg > MC_NKG_LOW_V:
        return "clamp-on"
    if noko < MC_NOKO_DRIVEN_V:
        return "first-stage-unbalanced"
    if nokx > MC_NOKX_LOW_V:
        return "output-stage-fight"
    return "contradiction-nokx-low"


def okdet_attribution(corners: list[dict]) -> dict:
    """Aggregate OK-detector sub-attribution over an MC record's corners (pure).

    Splits the no_transition realisations by their recorded `okdet_class`
    (`mc_okdet_subclass`), and collects the measured settle signal (NBTOP - NA at the
    sweep peak) and NOKO levels of the releasing samples beside the failing ones, so
    the record can state the margin the detector actually had.  An enable-clamp sample
    without xbias.* data is counted as `uninstrumented`, never folded into a class."""
    sub_counts: dict[str | None, int] = {}
    fail_signal, fail_noko, ok_noko, ok_signal = [], [], [], []
    for c in corners:
        for s in c["samples"]:
            if s["valid"]:
                if s.get("xbias_noko_at_peak_v") is not None:
                    ok_noko.append(s["xbias_noko_at_peak_v"])
                if s.get("xbias_nbtop_at_peak_v") is not None and s.get("xbias_na_at_peak_v") is not None:
                    ok_signal.append(s["xbias_nbtop_at_peak_v"] - s["xbias_na_at_peak_v"])
                continue
            if "no_transition" not in (s.get("reason") or ""):
                continue
            if s.get("stuck_class") != "enable-clamp":
                sub = "not-enable-clamp"
            else:
                sub = s.get("okdet_class")
                if sub is None:
                    sub = "uninstrumented"
            sub_counts[sub] = sub_counts.get(sub, 0) + 1
            if s.get("xbias_nbtop_at_peak_v") is not None and s.get("xbias_na_at_peak_v") is not None:
                fail_signal.append(s["xbias_nbtop_at_peak_v"] - s["xbias_na_at_peak_v"])
            if s.get("xbias_noko_at_peak_v") is not None:
                fail_noko.append(s["xbias_noko_at_peak_v"])

    def rng(v):
        return None if not v else {"min": min(v), "max": max(v), "n": len(v)}

    return {
        "sub_counts": sub_counts,
        "n_failed": sum(sub_counts.values()),
        "failing_settle_signal_v": rng(fail_signal),
        "failing_noko_at_peak_v": rng(fail_noko),
        "releasing_noko_at_peak_v": rng(ok_noko),
        "releasing_settle_signal_v": rng(ok_signal),
    }


def corner_mc_stats(samples: list[dict]) -> dict:
    """Mean and sample sigma (Bessel, n-1) of VPOR-up / VPOR-down / hysteresis over the VALID samples of one corner.

    Hysteresis is per sample (VPOR-up - VPOR-down of ONE realisation), never a combination
    of the two marginal sigmas: comparator offset moves both edges of the same
    realisation in the same direction, so the marginal combination overstates the
    hysteresis spread.  N counts valid samples only; the excluded samples stay listed
    with their reasons.  An all-invalid corner is a three-state NO-RESULT -- no mean, no
    sigma, never a spurious sigma = 0.  A corner with no gradeable report at all gets
    result NOT-RUN from the caller (refusal recorded verbatim)."""
    valid = [s for s in samples if s["valid"]]
    out: dict = {
        "n_samples": len(samples),
        "n_valid": len(valid),
        "excluded": [{"sample": s["sample"], "reason": s["reason"]} for s in samples if not s["valid"]],
        "sigma_resolution": sigma_resolution(len(valid)),
    }
    if not valid:
        out["result"] = "NO-RESULT (no valid sample at this corner)"
        out["stats"] = None
        return out
    out["result"] = "OK"
    out["stats"] = {
        key: {"mean_v": statistics.fmean(s[fld] for s in valid),
              "sigma_v": statistics.stdev([s[fld] for s in valid]) if len(valid) > 1 else None}
        for key, fld in (("vpor_up_v", "vup"), ("vpor_down_v", "vdn"), ("hysteresis_v", "hys"))
    }
    return out


REPRO_TOL_V = 1e-4  # 0.1 mV: a seed-for-seed replay is deterministic; anything above this is a difference
REPRO_MISMATCH_CAP = 10  # mismatches listed in full in the record; beyond that, counted only


def mc_reproduction(old: dict, new: dict) -> dict:
    """Seed-for-seed reproduction check of a regenerated MC record against its predecessor.

    Aligns corners by (process, temperature_c) and samples by index, then compares, per
    sample: the three derived seeds, the pass/fail pattern (valid flag + exclusion
    reason verbatim), and the extracted values (vup / vdn / hys / vref_max) within
    REPRO_TOL_V.  Pure; the record renders the result verbatim -- a non-reproduction is
    stated, never quietly re-baselined (issue #401, finding 6's caveat)."""
    fields = ("seed", "process_seed", "mismatch_seed", "valid", "reason", "vup", "vdn", "hys", "vref_max_v")
    tol = {"vup": REPRO_TOL_V, "vdn": REPRO_TOL_V, "hys": REPRO_TOL_V, "vref_max_v": REPRO_TOL_V}
    old_c = {(c["process"], c["temperature_c"]): {s["sample"]: s for s in c["samples"]} for c in old["corners"]}
    mismatches, n_cmp, max_delta = [], 0, None
    seeds_ok = pattern_ok = values_ok = True
    for nc in new["corners"]:
        key = (nc["process"], nc["temperature_c"])
        osmp = old_c.get(key, {})
        for ns in nc["samples"]:
            o = osmp.get(ns["sample"])
            if o is None:
                continue
            n_cmp += 1
            diff = {}
            for f in fields:
                a, b = o.get(f), ns.get(f)
                if f in tol and a is not None and b is not None:
                    d = abs(a - b)
                    max_delta = d if max_delta is None else max(max_delta, d)
                    if d > tol[f]:
                        values_ok = False
                        diff[f] = {"old": a, "new": b}
                elif a != b:
                    if f in ("seed", "process_seed", "mismatch_seed"):
                        seeds_ok = False
                    if f in ("valid", "reason"):
                        pattern_ok = False
                    diff[f] = {"old": a, "new": b}
            if diff:
                mismatches.append({"corner": f"{nc['process']}/{nc['temperature_c']}C", "sample": ns["sample"], "fields": diff})
    out = {
        "against": old["record_id"],
        "tol_v": REPRO_TOL_V,
        "corners_compared": sum(1 for c in new["corners"] if (c["process"], c["temperature_c"]) in old_c),
        "samples_compared": n_cmp,
        "seeds_all_match": seeds_ok,
        "pattern_all_match": pattern_ok,
        "values_all_within_tol": values_ok,
        "max_abs_delta_v": max_delta,
        "pattern_reproduced": seeds_ok and pattern_ok,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:REPRO_MISMATCH_CAP],
    }
    return out


def mc_samples(rep: dict, man: dict, corners_dir: Path, run_dir: Path) -> list[dict]:
    """Per-sample extraction of ONE mismatch-MC request's report (one (process, temperature) corner).

    Each sample is its own `corners[]` entry with its own waveform artifact, so VPOR-up /
    VPOR-down are extracted from each realisation's own transient and hysteresis is formed
    WITHIN the sample.  A per-sample log and change-triggered trace are staged as fleet
    evidence; the returned list is sorted by sample index."""
    out = []
    tpeak_s = 0.5 * tstop_for(man["monte_carlo"]["rate_v_per_s"], man)
    for c in rep["corners"]:
        mcj = c.get("monte_carlo") or {}
        smp = mcj.get("sample_index")
        art = c.get("artifacts") or {}
        log_text = Path(art["log"]).read_text() if art.get("log") and Path(art["log"]).is_file() else ""
        pt = {
            "sample": smp, "corner_id": c.get("corner_id"), "klt_status": c.get("status"), "runtime_s": c.get("runtime_s"),
            "seed": mcj.get("seed"), "process_seed": mcj.get("process_seed"), "mismatch_seed": mcj.get("mismatch_seed"),
            "ngspice": sim_common.fleet_ngspice(log_text),
            "diagnostics": [{"severity": g.get("severity"), "code": g.get("code"), "message": scrub(g.get("message", ""), run_dir)[:400]} for g in c.get("diagnostics", [])],
        }
        wp = Path(art["waveform"]) if art.get("waveform") else None
        if c.get("status") == "error" or wp is None or not wp.is_file():
            pt["extract"] = None
            pt["error_class"] = "klt status error" if c.get("status") == "error" else "no waveform retrieved"
        else:
            wave = sim_common.load_wave(wp)
            pt["extract"] = tx.analyze(wave, man["polarity"]["up"], man["polarity"]["down"])
            pt["trace_rows"] = write_trace(corners_dir / f"mc{0 if smp is None else smp}.trace.csv.gz", wave)
            pt["vref_max_v"] = max(wave["v(vref)"]) if "v(vref)" in wave else None
            pt.update(mc_diag_fields(wave, tpeak_s))
        pt["valid"], pt["reason"] = classify_mc_sample(pt["extract"])
        pt["stuck_class"] = mc_stuck_class(pt) if not pt["valid"] and "no_transition" in (pt["reason"] or "") else None
        pt["okdet_class"] = mc_okdet_subclass(pt) if pt.get("stuck_class") == "enable-clamp" else None
        ex = pt.get("extract") or {}
        pt["vup"] = ex.get("up", {}).get("vdd_v")
        pt["vdn"] = ex.get("down", {}).get("vdd_v")
        pt["hys"] = ex.get("hysteresis_v")
        lines = [f"# sample: {SLUG} mismatch-mc mc{0 if smp is None else smp}  corner_id {c.get('corner_id')}",
                 f"# klt status: {c.get('status')}  seed {mcj.get('seed')} (process {mcj.get('process_seed')}, mismatch {mcj.get('mismatch_seed')})  ngspice {pt['ngspice']}",
                 f"# valid: {pt['valid']}" + (f"  reason: {pt['reason']}" if pt["reason"] else "")]
        if pt.get("extract"):
            ex = pt["extract"]
            lines += ["# up: " + json.dumps({k: v for k, v in ex["up"].items() if k != "edges"}),
                      "# down: " + json.dumps({k: v for k, v in ex["down"].items() if k != "edges"}),
                      f"# hysteresis_v: {ex.get('hysteresis_v')}"]
        if any(k.endswith("_max_v") for k in pt):
            lines.append("# diag (issue #401): " + json.dumps({k: pt[k] for k in pt if k.endswith(("_max_v", "_at_peak_v")) or k == "stuck_class"}))
        lines += ["", "# ==== klt diagnostics ===="] + [f"| {d['severity']}/{d['code']}: {d['message']}" for d in pt["diagnostics"]]
        corners_dir.mkdir(parents=True, exist_ok=True)
        (corners_dir / f"mc{0 if smp is None else smp}.log").write_text("\n".join(lines) + "\n")
        out.append(pt)
    out.sort(key=lambda s: (s["sample"] is None, s["sample"] or 0))
    return out


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------


def write_trace(path: Path, wave: dict, dv: float = 0.002, anchor_s: float = 0.2e-3) -> int:
    """Change-triggered trace (VDD, POR_RAW, VREF, IBIAS, plus the enable/clamp-path
    diagnostic nodes when the netlist saves them): a row whenever a column moved >= dv,
    or an anchor.  The diagnostic nodes (issue #401) are conditionally included so a
    netlist without the extra `.save` lines still writes the original four-column trace."""
    cols = [c for c in ("time", "v(vdd)", "v(por_raw)", "v(vref)", "v(ibias)") + MC_DIAG_NODES if c in wave]
    rows = sim_common.decimate([wave[c] for c in cols], anchor_s, [None] + [dv] * (len(cols) - 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(",".join(f"{x:.9g}" for x in r) + "\n")
    return len(rows)


def analyze_variant(variant: str, run_dir: Path, man: dict, corners_dir: Path) -> dict:
    points, requests = [], []
    for rate, primary in all_rates(man):
        tag = rate_tag(rate)
        d = run_dir / variant / tag
        rq = {"rate_v_per_s": rate, "tag": tag, "primary_rate": primary, "tstop_s": tstop_for(rate, man)}
        attempts = sim_common.attempt_messages(d, run_dir, REPO_ROOT)
        if attempts:
            rq["failed_earlier_attempts"] = attempts
        rep, why = sim_common.load_request_report(d, run_dir, REPO_ROOT)
        if rep is None:
            rq["outcome"] = why
            requests.append(rq)
            continue
        rq.update(sim_common.fleet_job_fields(rep))
        requests.append(rq)
        for c in rep["corners"]:
            proc, temp = c["process"], c["temperature_c"]
            cid = corner_id(proc, temp)
            art = c.get("artifacts") or {}
            log_text = Path(art["log"]).read_text() if art.get("log") and Path(art["log"]).is_file() else ""
            pt = {
                "id": cid, "variant": variant, "rate_v_per_s": rate, "rate_tag": tag, "primary_rate": primary,
                "process": proc, "temperature_c": temp, "klt_status": c.get("status"), "runtime_s": c.get("runtime_s"),
                "ngspice": sim_common.fleet_ngspice(log_text),
                "diagnostics": [{"severity": g.get("severity"), "code": g.get("code"), "message": scrub(g.get("message", ""), run_dir)[:400]} for g in c.get("diagnostics", [])],
            }
            wp = Path(art["waveform"]) if art.get("waveform") else None
            if wp is not None and wp.is_file():
                wave = sim_common.load_wave(wp)
                pt["extract"] = tx.analyze(wave, man["polarity"]["up"], man["polarity"]["down"])
                pt["trace_rows"] = write_trace(corners_dir / tag / f"{cid}.trace.csv.gz", wave)
                pt["vref_end_v"] = wave.get("v(vref)", [None])[-1]
            else:
                pt["extract"] = None
                pt["error_class"] = sim_common.classify_error(c, log_text)
            header = [f"# point: {SLUG} {variant} {tag} {cid}", f"# process={proc} temp={cr.fmt_temp(temp)}C rate={rate:g} V/s tstop={tstop_for(rate, man):.6g}s klt status: {c.get('status')}"]
            (corners_dir / tag).mkdir(parents=True, exist_ok=True)
            (corners_dir / tag / f"{cid}.log").write_text(sim_common.point_log(c, header, run_dir, REPO_ROOT))
            points.append(pt)
    return {"points": points, "requests": requests}


def f3(x, spec=".4f"):
    return "n/a" if x is None else f"{x:{spec}}"


def point_table(man: dict, points: list[dict], procs: list[str] | None = None) -> list[dict]:
    """One row per (process, temperature): primary-rate edges + guard grade. Never drops a corner."""
    prim = man["rates"]["primary_v_per_s"][0]
    half = prim * man["rates"]["half_rate_guard_factor"]
    tol = man["grading"]["rate_guard_tolerance_v"]
    by = {(p["rate_v_per_s"], p["id"]): p for p in points}
    rows = []
    for proc in procs or man["corners"]["process"]:
        for temp in man["corners"]["temperature_c"]:
            cid = corner_id(proc, temp)
            a, b = by.get((prim, cid)), by.get((half, cid))
            row = {"id": cid, "process": proc, "temperature_c": temp}
            ea = (a or {}).get("extract")
            eb = (b or {}).get("extract")
            if not ea:
                row.update(status="NO_RESULT (primary-rate segment: " + ((a or {}).get("error_class") or "not run / no report") + ")",
                           vup=None, vdn=None, hys=None, up_res="-", down_res="-")
            else:
                row.update(vup=ea["up"]["vdd_v"], vdn=ea["down"]["vdd_v"], hys=ea["hysteresis_v"],
                           up_res=ea["up"]["result"], down_res=ea["down"]["result"], max_step_v=ea["max_vdd_step_v"],
                           status="OK" if ea["verdict"] == "OK" else ea["verdict"])
                if eb:
                    g = tx.compare_rates(ea, eb, tol)
                    row["guard"] = g
                    if row["status"] == "OK" and g["grade"] != "consistent":
                        row["status"] = "RATE-DEPENDENT (not graded as a quasi-static result)"
                else:
                    row["guard"] = {"grade": "n/a (no half-rate waveform)"}
                    if row["status"] == "OK":
                        # no guard evidence -> not a graded quasi-static result (kept in the table, out of the binding set)
                        row["status"] = "UNGUARDED (half-rate sweep missing; not graded as a quasi-static result)"
            rows.append(row)
    return rows


def binding(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["vup"] is not None and r["vdn"] is not None and r["hys"] is not None and r["status"] == "OK"]
    out = {"n_ok": len(ok), "n_total": len(rows)}
    if not ok:
        return out
    for key, fld in (("vpor_up", "vup"), ("vpor_down", "vdn"), ("hysteresis", "hys")):
        lo = min(ok, key=lambda r: r[fld])
        hi = max(ok, key=lambda r: r[fld])
        out[key] = {"min_v": lo[fld], "min_corner": lo["id"], "max_v": hi[fld], "max_corner": hi["id"]}
    return out


def render_md(rec: dict) -> str:
    man = rec["manifest_excerpt"]
    L = [f"# Record {rec['record_id']}", ""]
    L += sim_common.render_record_id_experiment(rec["record_id"], SLUG, man["title"])
    L.append(f"- **Claim**: {man['claim']}")
    L.append(f"- **Variant**: `{rec['variant']['name']}` -- {rec['variant']['description']}")
    L.append(f"- **Bias treatment**: {rec['variant']['bias_treatment']}")
    duts = ', '.join('`' + (n if '/' in n else 'design/netlist/' + n) + '`' for n in rec['variant']['dut_netlists'])
    L.append(f"- **Netlist provenance**: {rec['variant'].get('provenance') or 'schematic'} (testbench `{rec['variant']['schematic']}`; DUT spliced from {duts})")
    L += sim_common.render_pdk_tools_repo_state(rec)
    rg = rec.get("run_git") or {}
    if rg:
        L.append(f"- **Repo state at fleet-submit time**: `{rg.get('sha')}` on `{rg.get('branch')}`"
                 + (" (working tree DIRTY at submit time)" if rg.get("dirty") else " (clean working tree)")
                 + " -- the commit whose netlists the fleet simulated; the line above is the commit that extracted and wrote this record")
    t = rec["tools"]
    L.append(f"- **Fleet runner**: klt `{t['fleet_runner_klt']}` / `{t['fleet_ngspice']}` (client klt `{t['klt_client']}`); {t['fleet_note']}")
    L.append(f"- **Corner axis**: `{rec['matrix'].get('axis', 'main')}` -- {rec['matrix'].get('axis_note', '').rstrip('.')}. Never merged with the other axis's table.")
    L.append("- **Corner matrix run**: process " + ", ".join(rec["matrix"]["process"]) + "; temperature " + ", ".join(f"{cr.fmt_temp(x)} C" for x in rec["matrix"]["temperature_c"]) +
             f"; VDD is the swept variable (0 -> {rec['matrix']['peak_v']} V -> 0), no separate supply axis; sweep rates {', '.join(f'{r:g}' for r in rec['matrix']['rates_v_per_s'])} V/s (primary + half-rate guard). " +
             f"{rec['matrix']['n_corners']} process x temperature points; full matrix, no subset.")
    L.append("- **Statistical convention**: N/A (corner-matrix check; no mismatch Monte Carlo)")
    L.append("")
    L.append("## Measurement definitions (this campaign; none is a ratified bound)")
    for k, v in rec["definitions"].items():
        L.append(f"- **{k}**: {v}")
    L.append("")
    L.append("## Fleet submissions")
    L.append("| rate (V/s) | tstop (ms) | outcome | job id | runner klt | state | submitted at commit | refused earlier attempts |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rec["requests"]:
        L.append(f"| {r['rate_v_per_s']:g} | {r['tstop_s'] * 1e3:.4g} | {r.get('outcome')} | {r.get('job_id')} | {r.get('runner_klt_version')} | {r.get('state')} | "
                 f"{r.get('submit_git') or 'unknown'} | {len(r.get('failed_earlier_attempts', []))} |")
    L.append("")
    prim = man["primary_rate"]
    L.append(f"## Per-corner results (primary rate {prim:g} V/s; all {len(rec['table'])} process x temperature points)")
    L.append("| corner | VPOR-up (V) | VPOR-down (V) | hysteresis (mV) | up edge | down edge | half-rate guard (up/down delta, mV) | status |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rec["table"]:
        g = r.get("guard") or {}
        gtxt = g.get("grade", "-")
        if "up_delta_v" in g and "down_delta_v" in g:
            gtxt += f" ({g['up_delta_v'] * 1e3:+.2f}/{g['down_delta_v'] * 1e3:+.2f})"
        L.append(f"| {r['id']} | {f3(r['vup'])} | {f3(r['vdn'])} | {f3(None if r['hys'] is None else r['hys'] * 1e3, '.1f')} | {r['up_res']} | {r['down_res']} | {gtxt} | {r['status']} |")
    L.append("")
    b = rec["binding"]
    L.append("## Binding-corner table (EVIDENCE for a follow-on DR-003 amendment; not ratified, `spec/` untouched)")
    L.append(f"Computed over the {b['n_ok']} of {b['n_total']} corners with a clean, rate-consistent result.")
    if "vpor_up" in b:
        L.append("| metric | min (V or mV) | corner setting the min | max (V or mV) | corner setting the max |")
        L.append("|---|---|---|---|---|")
        L.append(f"| VPOR-up | {b['vpor_up']['min_v']:.4f} V | {b['vpor_up']['min_corner']} | {b['vpor_up']['max_v']:.4f} V | {b['vpor_up']['max_corner']} |")
        L.append(f"| VPOR-down | {b['vpor_down']['min_v']:.4f} V | {b['vpor_down']['min_corner']} | {b['vpor_down']['max_v']:.4f} V | {b['vpor_down']['max_corner']} |")
        L.append(f"| hysteresis | {b['hysteresis']['min_v'] * 1e3:.1f} mV | {b['hysteresis']['min_corner']} | {b['hysteresis']['max_v'] * 1e3:.1f} mV | {b['hysteresis']['max_corner']} |")
        m = rec["margin"]
        L.append("")
        L.append(f"Margin vs the DR-001 low rail ({m['rail_v']} V): VPOR-up,max = {m['vpor_up_max_v']:.4f} V ({m['vpor_up_max_corner']}) -> margin = rail - max(VPOR-up) = **{m['margin_mv']:+.0f} mV** "
                 f"(a positive number means the rail clears the worst-case-high rising threshold; a NEGATIVE number means VPOR-up exceeds the rail at that corner and the block would not release at the low rail). "
                 f"VPOR-up,min = {m['vpor_up_min_v']:.4f} V ({m['vpor_up_min_corner']}), i.e. {m['vpor_up_min_below_rail_mv']:+.0f} mV below the rail; the DR-001 high rail ({m['rail_hi_v']} V) is {m['vpor_up_max_below_hi_mv']:+.0f} mV above max(VPOR-up). "
                 "The binding side for 'release at the low rail' is max(VPOR-up); the binding side for 'not tripping inside the operating range' is VPOR-down,min.")
    else:
        L.append("No corner produced a clean result; no binding table can be formed.")
    L.append("")
    if rec.get("probe"):
        L.append("## Local single-corner cross-check (`--backend local`)")
        L.append(rec["probe"])
        L.append("")
    L.append("## Absent coverage (stated, not hidden)")
    for a in rec["absent_coverage"]:
        L.append(f"- {a}")
    L.append("")
    L += sim_common.record_footer_lines(rec, f"sim/{SLUG}/run_thresholds_campaign.py")
    return "\n".join(L)


# --------------------------------------------------------------------------
# mismatch Monte Carlo record (issue #348)
# --------------------------------------------------------------------------


MC_MARGIN_CONTEXT = (
    "DR-004's margin `2.97 V - max(VPOR-up)` = +257 mV (real-bias-core, ss, 27 C) is a CORNER number "
    "with no sigma attached; the distributions below put a mismatch spread beside it. This is evidence "
    "toward a possible future amendment of that recommendation. It is NOT a spec claim: no threshold is "
    "proposed or ratified here, `spec/` is untouched and DR-004 is not edited."
)


def mc_per_sample_csv(path: Path, samples: list[dict], proc: str, temp: float) -> None:
    cols = ["process", "temperature_c", "sample", "valid", "reason", "vpor_up_v", "vpor_down_v", "hysteresis_v",
            "vref_max_v", "klt_status", "runtime_s", "seed", "process_seed", "mismatch_seed",
            "stuck_class", "okdet_class", "bias_ok_max_v", "bias_ok_at_peak_v", "xdut_cmpo_max_v", "xdut_cmpo_at_peak_v",
            "xdut_n1_at_peak_v", "xdut_sns_at_peak_v",
            "xbias_na_at_peak_v", "xbias_nbtop_at_peak_v", "settle_signal_at_peak_v",
            "xbias_tok_at_peak_v", "xbias_nokl_at_peak_v", "xbias_noko_at_peak_v", "xbias_nokx_at_peak_v",
            "xbias_nkg_at_peak_v", "xbias_pb_at_peak_v"]
    lines = [",".join(cols)]
    for s in samples:
        ex = s.get("extract") or {}
        up = (ex.get("up") or {}).get("vdd_v")
        dn = (ex.get("down") or {}).get("vdd_v")
        hys = ex.get("hysteresis_v")
        vref = s.get("vref_max_v")
        na, nbtop = s.get("xbias_na_at_peak_v"), s.get("xbias_nbtop_at_peak_v")
        sig = None if na is None or nbtop is None else nbtop - na
        fmt = lambda x: "" if x is None else f"{x:.7g}"  # noqa: E731
        lines.append(",".join([
            proc, f"{temp:g}", str(s["sample"]), str(int(s["valid"])), (s.get("reason") or "").replace(",", ";"),
            fmt(up), fmt(dn), fmt(hys), fmt(vref),
            str(s.get("klt_status")), f"{s.get('runtime_s'):g}" if s.get("runtime_s") is not None else "",
            str(s.get("seed")), str(s.get("process_seed")), str(s.get("mismatch_seed")),
            str(s.get("stuck_class") or ""), str(s.get("okdet_class") or ""),
            fmt(s.get("bias_ok_max_v")), fmt(s.get("bias_ok_at_peak_v")),
            fmt(s.get("xdut_cmpo_max_v")), fmt(s.get("xdut_cmpo_at_peak_v")),
            fmt(s.get("xdut_n1_at_peak_v")), fmt(s.get("xdut_sns_at_peak_v")),
            fmt(na), fmt(nbtop), fmt(sig),
            fmt(s.get("xbias_tok_at_peak_v")), fmt(s.get("xbias_nokl_at_peak_v")),
            fmt(s.get("xbias_noko_at_peak_v")), fmt(s.get("xbias_nokx_at_peak_v")),
            fmt(s.get("xbias_nkg_at_peak_v")), fmt(s.get("xbias_pb_at_peak_v")),
        ]))
    path.write_text("\n".join(lines) + "\n")


def fms(stats: dict | None, key: str, scale: float = 1.0, spec: str = ".4f") -> str:
    """`mean ± sigma` cell (or a three-state placeholder) for one metric of one corner."""
    if not stats:
        return "NO-RESULT"
    m, s = stats[key]["mean_v"], stats[key]["sigma_v"]
    txt = f"{m * scale:{spec}}"
    if s is not None:
        txt += f" ± {s * scale:{spec}}"
    return txt


def mc_mechanism_statement(stuck: list[tuple[dict, dict]]) -> str:
    """The mechanism statement this record's stuck-sample diagnostics support.

    Data-driven, never aspirational: the verdict is computed from the per-sample
    `stuck_class` fields (issue #401).  One mechanism named only when ALL failed-release
    realisations carry the same class; a mixed outcome is enumerated as a split; samples
    without diagnostic data are named as unestablished rather than absorbed into any
    class."""
    if not stuck:
        return ""
    n = len(stuck)
    classes = [s.get("stuck_class") for _, s in stuck]
    counts = {k: classes.count(k) for k in ("enable-clamp", "comparator-stuck", "extractor-miss", None)}
    sentences = {
        "enable-clamp": lambda k: f"in {k} the enable/clamp path never released (BIAS_OK never asserted -- at the sweep peak its level is "
        f"not a rail swing, below {MC_BIAS_OK_ASSERTED_FRAC:g} of the at-peak supply, so BIAS_OKB stayed high, XMDCMPO held CMPO at VSS and "
        "XMENSRC kept the load rail VDDA disconnected)",
        "comparator-stuck": lambda k: f"in {k} the clamp DID release (BIAS_OK asserted) yet CMPO never rose above {MC_CMPO_RELEASED_V:g} V -- "
        "the comparator's own bias/tail path held the output low, refuting the enable-path candidate for those realisations",
        "extractor-miss": lambda k: f"in {k} both the enable path released AND CMPO rose, yet the sweep graded no_transition -- "
        "a contradiction against the edge extractor, flagged here and not folded into any mechanism",
        None: lambda k: f"{k} carry no per-sample diagnostic data (no waveform retrieved), so no mechanism is established for them",
    }
    if all(c == "enable-clamp" for c in classes):
        return (f"**Mechanism established, all {n} failed-release realisations: the enable/clamp path never released** "
                f"(in all {n}, BIAS_OK never asserted -- at the sweep peak its level is not a rail swing, below {MC_BIAS_OK_ASSERTED_FRAC:g} "
                "of the at-peak supply, so BIAS_OKB stayed high, XMDCMPO held CMPO at VSS and XMENSRC kept the load rail VDDA disconnected).")
    if all(c == "comparator-stuck" for c in classes):
        return (f"**Mechanism established, all {n} failed-release realisations: the comparator's bias/tail path, not the enable path** "
                f"(in all {n} the clamp DID release -- BIAS_OK asserted -- yet CMPO never rose above {MC_CMPO_RELEASED_V:g} V; "
                "the comparator's own bias/tail path held the output low, refuting the enable-path candidate).")
    if all(c == "extractor-miss" for c in classes):
        return (f"**No circuit mechanism established, all {n} failed-release realisations: the instrumented data contradicts the grading** "
                f"(in all {n} both the enable path released AND CMPO rose, yet the sweep graded no_transition -- "
                "a contradiction against the edge extractor, flagged here and not folded into any mechanism).")
    if all(c is None for c in classes):
        return (f"**No mechanism established.** All {n} failed-release realisations carry no per-sample diagnostic data "
                "(no waveform retrieved), so no mechanism is established for them.")
    parts = [sentences[k](counts[k]) for k in ("enable-clamp", "comparator-stuck", "extractor-miss", None) if counts[k]]
    return "**Mechanism: mixed across the " + f"{n} failed-release realisations** -- " + "; ".join(parts) + "."


def mc_okdet_attribution_statement(att: dict) -> str:
    """Data-driven attribution sentence for the OK-detector sub-classes (issue #455).

    Reports the measured class split and the measured signal/NOKO ranges verbatim; the
    device-level interpretation (which devices inside the named stage dominate) is NOT
    asserted here -- the record's body carries that analysis beside its own arithmetic,
    and this statement only says what the waveforms say."""
    n = att["n_failed"]
    if not n:
        return "**No failed-release realisation to attribute.**"
    counts = att["sub_counts"]
    parts = [f"{v}x `{k}`" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    L = [f"**OK-detector sub-attribution of the {n} failed-release realisations: " + ", ".join(parts) + ".**"]
    fs, rs = att["failing_settle_signal_v"], att["releasing_settle_signal_v"]
    if fs:
        L.append(f"The failing realisations' own settle signal at the peak was {fs['min'] * 1e3:+.2f} to {fs['max'] * 1e3:+.2f} mV "
                 f"(n = {fs['n']} instrumented)" + (f", against {rs['min'] * 1e3:+.2f} to {rs['max'] * 1e3:+.2f} mV (n = {rs['n']}) "
                                                    "for the releasing realisations of the same corners" if rs else "") + ".")
    fn, rn = att["failing_noko_at_peak_v"], att["releasing_noko_at_peak_v"]
    if fn:
        L.append(f"Their NOKO at the peak sat at {fn['min']:.3f}-{fn['max']:.3f} V"
                 + (f", while every releasing realisation's NOKO sat at {rn['min']:.3f}-{rn['max']:.3f} V" if rn else "")
                 + " -- the stage output, not the output stage, is where the realisations separate.")
    return " ".join(L)


def render_mc_md(rec: dict) -> str:
    man = rec["manifest_excerpt"]
    mc = rec["monte_carlo"]
    L = [f"# Record {rec['record_id']}", ""]
    L += sim_common.render_record_id_experiment(rec["record_id"], SLUG, man["title"])
    L.append(f"- **Claim**: {man['claim']}")
    L.append(f"- **Variant**: `{rec['variant']['name']}` -- {rec['variant']['description']}")
    L.append(f"- **Bias treatment**: {rec['variant']['bias_treatment']}")
    L += sim_common.render_pdk_tools_repo_state(rec)
    t = rec["tools"]
    L.append(f"- **Fleet runner**: klt `{t['fleet_runner_klt']}` / `{t['fleet_ngspice']}` (client klt `{t['klt_client']}`); {t['fleet_note']}")
    L.append(f"- **Corner axis**: `mc` (mismatch Monte Carlo supplement, issue #348) -- one request per (process, temperature), "
             f"process sections `{', '.join(p + '_mm' for p in rec['matrix']['process'])}` (local mismatch only, never MC_PR_SWITCH global process MC), "
             f"temperature {', '.join(f'{cr.fmt_temp(x)} C' for x in rec['matrix']['temperature_c'])}; "
             f"VDD is the swept variable (0 -> {rec['matrix']['peak_v']} V -> 0), no separate supply axis, at the primary {rec['matrix']['rates_v_per_s'][0]:g} V/s only.")
    L.append(f"- **Statistical convention**: {mc['statistical_convention']}")
    L.append("")
    L.append("## Request sizing and seeds (why this grid cannot be bigger)")
    L.append(f"- {mc['request_sizing']}")
    L.append("- Seed offsets: " + mc["seed_offsets"])
    L.append("")
    L.append("## Fleet submissions (one request per (process, temperature))")
    L.append("| request | N | seed (base + offset) | outcome | job id | runner klt | state | submitted at commit | refused earlier attempts |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in rec["requests"]:
        L.append(f"| {r['process']}/{cr.fmt_temp(r['temperature_c'])}C | {mc['n_per_corner']} | {r.get('seed')} ({mc['seed']} + {r.get('seed_offset')}) | {r.get('outcome')} | "
                 f"{r.get('job_id')} | {r.get('runner_klt_version')} | {r.get('state')} | {r.get('submit_git') or 'unknown'} | {len(r.get('failed_earlier_attempts', []))} |")
    L.append("")
    L.append(f"## Per-corner mismatch distributions (N = {mc['n_per_corner']} samples per corner, Bessel (n-1) sigmas)")
    L.append("Hysteresis is per sample (VPOR-up - VPOR-down of ONE realisation). `resolution` is the statistical resolution of that corner's sigma, "
             "1/sqrt(2(N-1)) of its valid N -- the number a future amendment must quote with any sigma from this table.")
    L.append("| corner | N valid/N run | VPOR-up mean ± sigma (V) | VPOR-down mean ± sigma (V) | hysteresis mean ± sigma (mV) | sigma resolution | excluded (of N) |")
    L.append("|---|---|---|---|---|---|---|")
    any_uncond = any(c["stats"]["n_valid"] == c["stats"]["n_samples"] and c["stats"]["n_samples"] for c in rec["corners"])
    for c in rec["corners"]:
        cid = f"{c['process']}/{cr.fmt_temp(c['temperature_c'])}C"
        st = c["stats"]
        res = st["sigma_resolution"]
        uncond = " (unconditional)" if st["n_valid"] == st["n_samples"] and st["n_samples"] else ""
        L.append(f"| {cid} | {st['n_valid']}/{st['n_samples']} | {fms(st['stats'], 'vpor_up_v')} | {fms(st['stats'], 'vpor_down_v')} | "
                 f"{fms(st['stats'], 'hysteresis_v', 1e3, '.1f')} | {f'{res:.1%}' if res is not None else 'n/a'} | "
                 f"{len(st['excluded'])}{' (' + st['result'] + ')' if st['result'] != 'OK' else ''}{uncond} |")
    if any_uncond:
        L.append("")
        L.append("`unconditional` in the last column marks corners where **every** run sample carried both edges (0 exclusions): the "
                 "mean/sigma of that corner are over ALL N run samples, not a releasing subset (issue #455 acceptance: unconditional "
                 "sigmas, stated as such rather than inferred from the N valid/N run column).")
    L.append("")
    excl = [(c, e) for c in rec["corners"] for e in c["stats"]["excluded"]]
    if excl:
        L.append("### Excluded samples (counted, never silently dropped)")
        L.append("| corner | sample | reason |")
        L.append("|---|---|---|")
        for c, e in excl:
            L.append(f"| {c['process']}/{cr.fmt_temp(c['temperature_c'])}C | mc{e['sample']} | {e['reason']} |")
        L.append("")
        stuck = [(c, s) for c in rec["corners"] for s in c["samples"]
                 if not s["valid"] and "no_transition" in (s.get("reason") or "")]
        if stuck:
            vrefs = [s["vref_max_v"] for _, s in stuck if s.get("vref_max_v") is not None]
            vref_txt = (f" In every one of them `bias_core`'s reference came up (max v(vref) over the sweep "
                        f"{min(vrefs):.3f}-{max(vrefs):.3f} V, the intended 1.25 V branch), so the failure is downstream of the "
                        "reference -- not a bias_core startup failure."
                        if vrefs and len(vrefs) == len(stuck) else
                        (f" Max v(vref) over the sweep among them: {min(vrefs):.3f}-{max(vrefs):.3f} V." if vrefs else
                         " No v(vref) waveform was retrieved for them, so a reference-side cause is not excluded."))
            L.append(f"**Failed-release realisations.** {len(stuck)} of the {sum(c['stats']['n_samples'] for c in rec['corners'])} samples "
                     f"graded `no_transition` with POR_RAW **held low through the entire sweep** -- in those realisations reset never "
                     f"releases within the 3.63 V peak.{vref_txt}")
            L.append(f"The per-corner distributions above therefore describe only the **releasing subset** of each corner; the failed-release "
                     f"fraction is part of the mismatch behaviour this record measures, and DR-004's corner margin does not capture it.")
            L.append("")
            L.append("### Failed-release mechanism diagnostics (issue #401)")
            L.append(f"Per-sample reduction of the enable/clamp path the netlist already saves (`v(bias_ok)`, `v(xdut.cmpo)`, `v(xdut.n1)`, "
                     f"`v(xdut.sns)`): each node's sweep max and its value at the sweep peak (t = tstop/2, interpolated; the VDD peak is "
                     f"{rec['matrix']['peak_v']:g} V). `BIAS_OK asserted` means its at-peak level is a rail swing -- at least "
                     f"{MC_BIAS_OK_ASSERTED_FRAC:g} of the at-peak supply; `CMPO released` means max v(xdut.cmpo) >= {MC_CMPO_RELEASED_V:g} V. "
                     "Both are diagnostic labels on recorded evidence, and the raw values below can be re-read against any other criterion. "
                     "`sns` at the peak carries the input-differential check: SNS sits at the divider ratio times the peak whether or not the "
                     "comparator trips, so a stuck sample still shows a release-direction differential.")
            L.append("")
            L.append("| corner | sample | class | BIAS_OK max (V) | BIAS_OK @peak (V) | VDD @peak (V) | CMPO max (V) | CMPO @peak (V) | N1 @peak (V) | SNS @peak (V) | vref max (V) |")
            L.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for c, s in stuck:
                fmtv = lambda k: "n/a" if s.get(k) is None else f"{s[k]:.3f}"  # noqa: E731
                L.append(f"| {c['process']}/{cr.fmt_temp(c['temperature_c'])}C | mc{s['sample']} | {s.get('stuck_class') or 'n/a'} | "
                         f"{fmtv('bias_ok_max_v')} | {fmtv('bias_ok_at_peak_v')} | {fmtv('vdd_at_peak_v')} | {fmtv('xdut_cmpo_max_v')} | "
                         f"{fmtv('xdut_cmpo_at_peak_v')} | {fmtv('xdut_n1_at_peak_v')} | {fmtv('xdut_sns_at_peak_v')} | {fmtv('vref_max_v')} |")
            L.append("")
            L.append(mc_mechanism_statement(stuck))
            L.append("")
            # OK-detector sub-attribution (issue #455): where inside the enable path.
            instrumented = [(c, s) for c, s in stuck if s.get("xbias_noko_at_peak_v") is not None]
            if instrumented:
                L.append("### OK-detector sub-attribution (issue #455)")
                L.append(f"Per-sample levels of the bias_core OK-detector's own nodes at the sweep peak (linearly interpolated at "
                         f"t = tstop/2), for the failed-release realisations the netlist instruments (the testbench saves "
                         f"`v(xbias.*)` since issue #455; realisations from records before that change carry no such fields and are "
                         f"not guessed). `settle signal` is V(NBTOP) - V(NA) -- the I*RT drop across `XRT` is the detector's entire "
                         "input signal, so the table shows each failing realisation's own signal beside the stage that failed to "
                         "respond to it. Classification labels (criteria are constants of this driver, stated beside the raw values): "
                         f"`first-stage-unbalanced` = TOK >= {MC_TOK_PRESENT_V:g} V and NKG <= {MC_NKG_LOW_V:g} V (tail present, clamp off) "
                         f"yet NOKO < {MC_NOKO_DRIVEN_V:g} V -- the XMOKA/XMOKB + XML1/XML2 stage never delivered net current to NOKO; "
                         f"`output-stage-fight` = NOKO >= {MC_NOKO_DRIVEN_V:g} V yet NOKX > {MC_NOKX_LOW_V:g} V -- XMOK2 lost the ratio "
                         f"fight against XMOK2P; `tok-collapsed` = TOK < {MC_TOK_PRESENT_V:g} V; `clamp-on` = NKG > {MC_NKG_LOW_V:g} V.")
                L.append("")
                L.append("| corner | sample | class | NA @peak (V) | NBTOP @peak (V) | settle signal (mV) | TOK @peak (V) | NOKL @peak (V) | NOKO @peak (V) | NOKX @peak (V) | NKG @peak (V) |")
                L.append("|---|---|---|---|---|---|---|---|---|---|---|")
                for c, s in instrumented:
                    na, nbtop = s.get("xbias_na_at_peak_v"), s.get("xbias_nbtop_at_peak_v")
                    sig = None if na is None or nbtop is None else (nbtop - na) * 1e3
                    fmtv = lambda k: "n/a" if s.get(k) is None else f"{s[k]:.3f}"  # noqa: E731
                    L.append(f"| {c['process']}/{cr.fmt_temp(c['temperature_c'])}C | mc{s['sample']} | {s.get('okdet_class') or 'n/a'} | "
                             f"{fmtv('xbias_na_at_peak_v')} | {fmtv('xbias_nbtop_at_peak_v')} | "
                             f"{'n/a' if sig is None else f'{sig:+.2f}'} | {fmtv('xbias_tok_at_peak_v')} | {fmtv('xbias_nokl_at_peak_v')} | "
                             f"{fmtv('xbias_noko_at_peak_v')} | {fmtv('xbias_nokx_at_peak_v')} | {fmtv('xbias_nkg_at_peak_v')} |")
                L.append("")
                L.append(mc_okdet_attribution_statement(okdet_attribution(rec["corners"])))
                L.append("")
    if rec.get("probe"):
        L.append("## Local deterministic single-device cross-check (`--backend local`-class probes, one ngspice -b each)")
        L.append(rec["probe"])
        L.append("")
    if rec.get("reproduction"):
        r = rec["reproduction"]
        L.append(f"## Reproduction of record {r['against']} (seed-for-seed)")
        verdict = ("**Reproduced.** " if r["pattern_reproduced"] else "**NOT reproduced.** ")
        L.append(verdict + f"{r['samples_compared']} samples across {r['corners_compared']} corner entries compared against the predecessor record "
                 f"by (process, temperature, sample index): derived seeds {'all match' if r['seeds_all_match'] else 'DIFFER'}, "
                 f"pass/fail pattern (valid flag + exclusion reason) {'all match' if r['pattern_all_match'] else 'DIFFERS'}, "
                 f"extracted values {'all within' if r['values_all_within_tol'] else 'EXCEED'} the stated "
                 f"{r['tol_v'] * 1e3:.1f} mV tolerance"
                 + (f" (max absolute delta {r['max_abs_delta_v'] * 1e3:.3f} mV)" if r["max_abs_delta_v"] is not None else "")
                 + ". A non-reproduction is stated here, never quietly re-baselined: the predecessor record stands as committed evidence.")
        if r["mismatch_count"]:
            L.append("")
            L.append(f"Mismatching samples ({r['mismatch_count']}"
                     + (f", listing first {len(r['mismatches'])}):" if r["mismatch_count"] > len(r["mismatches"]) else "):"))
            L.append("")
            L.append("| corner | sample | field | old | new |")
            L.append("|---|---|---|---|---|")
            for m in r["mismatches"]:
                for f, d in m["fields"].items():
                    L.append(f"| {m['corner']} | mc{m['sample']} | {f} | {d['old']} | {d['new']} |")
        L.append("")
    L.append("## Statistical disclosures (stated, not hidden)")
    L.append("- **NOT a spec claim.** This record supplies a distribution as evidence; it proposes no threshold. `spec/` is untouched and DR-004 is not edited.")
    L.append("- **Independent realisation sets per temperature**: each temperature is its own transient run and its own request, so temperatures draw "
             "independent mismatch realisations. Per-corner statistics are valid; this record makes NO per-sample temperature-drift or temperature-correlation claim.")
    L.append("- **Unguarded points**: the MC grid runs the primary 100 V/s rate only, WITHOUT the half-rate quasi-staticity guard. That guard is what makes the "
             "corner-matrix results quasi-static evidence; the MC points inherit the rate choice the nominal campaign established 15/15 at every corner and are disclosed as unguarded.")
    L.append("- **Not sampled**: global process Monte Carlo (MC_PR_SWITCH), the 50 V/s half-rate guard, the ideal-bias variant, the ll/hh passive-skew axis, "
             "post-layout parasitics, and the ff/sf/fs process sections.")
    L.append("")
    L.append("## Margin context (evidence toward a possible future amendment; no proposal)")
    L.append(MC_MARGIN_CONTEXT)
    ss27 = next((c for c in rec["corners"] if c["process"] == "ss" and c["temperature_c"] == 27), None)
    n_samples_total = sum(c["stats"]["n_samples"] for c in rec["corners"])
    n_stuck_total = sum(1 for c in rec["corners"] for s in c["samples"] if not s["valid"] and "no_transition" in (s.get("reason") or ""))
    if ss27 and ss27["stats"]["result"] == "OK":
        st = ss27["stats"]["stats"]
        L.append(f"Beside it: the ss/27 C mismatch distribution of VPOR-up is {st['vpor_up_v']['mean_v']:.4f} ± "
                 f"{(st['vpor_up_v']['sigma_v'] or float('nan')):.4f} V over N = {ss27['stats']['n_valid']} (sigma resolution "
                 f"{ss27['stats']['sigma_resolution']:.1%}). No number here amends or replaces DR-004's corner margin.")
    if n_stuck_total:
        L.append(f"Note also the failed-release realisations counted above: {n_stuck_total} of {n_samples_total} samples never release reset at all. "
                 "A margin computed over releasing realisations -- corner or distribution -- does not describe those samples.")
    L.append("")
    L.append("## Absent coverage (stated, not hidden)")
    for a in rec["absent_coverage"]:
        L.append(f"- {a}")
    L.append("")
    L += sim_common.record_footer_lines(rec, f"sim/{SLUG}/run_thresholds_campaign.py run --axis mc")
    return "\n".join(L)


def mc_runner_pdks(reps) -> list[dict | None]:
    """One `runner_pdk()` per graded MC request report (the fleet half of the record's pdk block)."""
    return [sim_common.runner_pdk(rep) for rep in reps]


def cmd_record_mc(args, man: dict, run_dir: Path, meta: dict) -> int:
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    git_info = cr.git_state()
    if git_info["dirty"] and not args.allow_dirty:
        raise SystemExit("working tree is dirty: commit first so the record carries a clean-tree SHA")
    now = datetime.now(timezone.utc)
    mc = mc_effective(man, meta.get("monte_carlo"))
    variant = meta["variants"][0]
    stamp = now
    record_id = f"{stamp:%Y%m%d}-{stamp:%H%M%S}-{git_info['sha']}-{variant}-mismatch-mc"
    rec_dir, snap_dir = HERE / "records", HERE / "netlist-snapshots" / record_id
    corners_dir = evidence_store.stage_dir_for(SLUG, record_id)  # git-ignored scratch; stored below
    sim_common.refuse_existing((rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", corners_dir, snap_dir, evidence_store.manifest_path(SLUG, record_id)))
    v = man["variants"][variant]
    units = [(p, t, o) for p, t, o in mc_units(man, mc)]
    submit_git = {}
    for mf in sorted(run_dir.glob("run*.json"), key=lambda p: p.stat().st_mtime):
        m = json.loads(mf.read_text())
        for s in m.get("submit_results", []):
            if s.get("process") and s.get("status") not in (None, "NO-JSON"):
                submit_git[f"{s['process']}_{cr.fmt_temp(s['temperature_c'])}c"] = m["git"]["sha"] + (" (DIRTY)" if m["git"].get("dirty") else " (clean)")
    corners, requests, fleet_pdks, graded_reps = [], [], [], []
    for proc, temp, offset in units:
        d = mc_dir(run_dir, variant, proc, temp)
        cid = f"{proc}_{cr.fmt_temp(temp)}c"
        rq = {"process": proc, "temperature_c": temp, "seed_offset": offset, "seed": mc_request_seed(mc, offset),
              "n": mc["n_per_corner"], "tag": f"mc_{cid}", "rate_v_per_s": mc["rate_v_per_s"],
              "tstop_s": tstop_for(mc["rate_v_per_s"], man)}
        attempts = sim_common.attempt_messages(d, run_dir, REPO_ROOT)
        if attempts:
            rq["failed_earlier_attempts"] = attempts
        rq["submit_git"] = submit_git.get(cid)
        rep, why = sim_common.load_request_report(d, run_dir, REPO_ROOT)
        uc = corners_dir / cid
        if rep is None:
            rq["outcome"] = why
            st = {"result": f"NOT-RUN ({why})", "n_samples": 0, "n_valid": 0, "excluded": [], "sigma_resolution": None, "stats": None}
            requests.append(rq)
            corners.append({"process": proc, "temperature_c": temp, "seed_offset": offset, "stats": st, "samples": []})
            continue
        rq.update(sim_common.fleet_job_fields(rep))
        requests.append(rq)
        graded_reps.append(rep)
        samples = mc_samples(rep, man, uc, run_dir)
        st = corner_mc_stats(samples)
        mc_per_sample_csv(uc / "samples.csv", samples, proc, temp)
        corners.append({"process": proc, "temperature_c": temp, "seed_offset": offset, "stats": st, "samples": samples})
    fleet_pdks = mc_runner_pdks(graded_reps)
    snap_dir.mkdir(parents=True)
    for proc, temp, _ in units:
        sim_common.snapshot_request_artifacts(mc_dir(run_dir, variant, proc, temp), f"mc_{proc}_{cr.fmt_temp(temp)}c", snap_dir, corners_dir, run_dir, REPO_ROOT)
    pdk_d, tools_d = sim_common.record_pdk_tools(
        pdk, pin, meta, [s for c in corners for s in c["samples"]], requests,
        lib_file=f"$PDK_ROOT/{pdk.variant}/{pin['ngspice_lib']} (fleet: models.pdk={pdk.variant}, models.lib={MODEL_LIB})",
        xschem_note=None)
    pdk_d |= sim_common.fleet_pdk_fields(fleet_pdks, pin)
    v = man["variants"][variant]
    art_manifest, art_summary = evidence_store.store_or_exit(SLUG, record_id, corners_dir)
    record = {
        "record_id": record_id,
        "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author or cr.default_author(),
        "supersedes": args.supersedes,
        "manifest_excerpt": {"title": man["title"], "claim": man["claim"], "primary_rate": man["rates"]["primary_v_per_s"][0]},
        "variant": {"name": variant, "description": v["description"], "bias_treatment": v["bias_treatment"], "schematic": "sim/" + SLUG + "/" + v["schematic"], "dut_netlists": v["dut_netlists"], "provenance": v.get("provenance"), "baseline_variant": v.get("baseline_variant")},
        "pdk": pdk_d,
        "tools": tools_d,
        "git": git_info,
        "run_git": meta.get("git"),
        "monte_carlo": {"n_per_corner": mc["n_per_corner"], "seed": mc["seed"], "vary": mc["vary"],
                        "statistical_convention": mc["statistical_convention"], "request_sizing": mc["request_sizing"],
                        "seed_offsets": mc["seed_offsets"],
                        "process_override": (meta.get("monte_carlo") or {}).get("process_override"),
                        "seed_override": (meta.get("monte_carlo") or {}).get("seed_override")},
        "matrix": {"axis": "mc", "process": mc["process"], "temperature_c": mc["temperature_c"], "peak_v": man["sweep"]["peak_v"],
                   "rates_v_per_s": [mc["rate_v_per_s"]], "n_corners": len(units), "is_subset": True,
                   "axis_note": "mismatch Monte Carlo supplement: real-bias-core only, _mm sections (local mismatch), primary rate only, no half-rate guard"},
        "definitions": {**man["grading"]["definitions"],
                        "mismatch sample": mc["execution"],
                        "edge extraction": f"VDD sample step <= {tx.MAX_BRACKET_V * 1e3:g} mV around an edge, linear interpolation inside the bracket; POR_RAW state evaluated for VDD >= {tx.V_VALID:g} V only",
                        "BIAS_OK asserted (diagnostic)": f"at the sweep peak, v(bias_ok) >= {MC_BIAS_OK_ASSERTED_FRAC:g} x the at-peak supply -- a rail swing; a diagnostic label on recorded evidence, the raw per-sample max and at-peak values are recorded beside every label (issue #401). BIAS_OK follows VDD through bias_core's weak XMO1P pullup whenever the NOKX pulldown is off, so a max-over-sweep test cannot distinguish assertion",
                        "CMPO released (diagnostic)": f"max v(xdut.cmpo) over the sweep >= {MC_CMPO_RELEASED_V:g} V; while it is below, XMDCMPO holds CMPO at VSS (the clamp) when BIAS_OKB is high (issue #401)",
                        "sweep peak": f"t = tstop/2 of the {mc['rate_v_per_s']:g} V/s triangle, where VDD reaches its {man['sweep']['peak_v']:g} V peak; at-peak values are linearly interpolated at that time",
                        "stuck class": "mechanism class of a failed-release realisation from its diagnostics: enable-clamp (BIAS_OK never asserted), comparator-stuck (BIAS_OK asserted, CMPO never rose), extractor-miss (both released yet graded no_transition); None = no diagnostic data"},
        "requests": requests,
        "corners": corners,
        "probe": (Path(args.probe_note_file).read_text().strip() if args.probe_note_file else ""),
        "absent_coverage": man["absent_coverage"],
        "links": {
            "testbench": "sim/" + SLUG + "/" + v["schematic"], "manifest": f"sim/{SLUG}/experiment.json", "driver": f"sim/{SLUG}/run_thresholds_campaign.py",
            "extractor": f"sim/{SLUG}/threshold_extractor.py", "netlist_snapshots": f"sim/{SLUG}/netlist-snapshots/{record_id}/",
            "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)), "artifact_summary": str(art_summary.relative_to(REPO_ROOT)), "json": f"sim/{SLUG}/records/{record_id}.json", "record": f"sim/{SLUG}/records/{record_id}.md",
        },
    }
    rec_dir.mkdir(parents=True, exist_ok=True)
    if args.against_record:
        old_path = HERE / "records" / f"{args.against_record}.json"
        if not old_path.is_file():
            raise SystemExit(f"--against-record: {old_path} not found")
        record["reproduction"] = mc_reproduction(json.loads(old_path.read_text()), record)
    (rec_dir / f"{record_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
    (rec_dir / f"{record_id}.md").write_text(render_mc_md(record))
    ok = sum(1 for c in corners if c["stats"]["result"] == "OK")
    repro_txt = ""
    if record.get("reproduction"):
        r = record["reproduction"]
        repro_txt = f"  (reproduction vs {r['against']}: {'REPRODUCED' if r['pattern_reproduced'] else 'NOT reproduced'}, {r['mismatch_count']} mismatching samples)"
    print(f"record {variant}: {record_id}  ({ok}/{len(corners)} corners with a distribution, "
          f"{sum(c['stats']['n_valid'] for c in corners)} valid samples of {mc['n_per_corner'] * len(units)}){repro_txt}")
    return 0


def cmd_record(args) -> int:
    evidence_store.preflight_or_exit()
    man = sim_common.load_manifest(MANIFEST)
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    if meta.get("axis") == "mc":
        return cmd_record_mc(args, man, run_dir, meta)
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    git_info = cr.git_state()
    if git_info["dirty"] and not args.allow_dirty:
        raise SystemExit("working tree is dirty: commit first so the record carries a clean-tree SHA")
    now = datetime.now(timezone.utc)
    axis = meta.get("axis", "main")
    procs = processes(man, axis)
    ids = []
    for idx, variant in enumerate(args.variant or meta["variants"]):
        stamp = now if idx == 0 else datetime.now(timezone.utc)
        record_id = f"{stamp:%Y%m%d}-{stamp:%H%M%S}-{git_info['sha']}-{variant}" + ("" if axis == "main" else f"-{axis}")
        rec_dir, snap_dir = HERE / "records", HERE / "netlist-snapshots" / record_id
        corners_dir = evidence_store.stage_dir_for(SLUG, record_id)  # git-ignored scratch; stored below
        sim_common.refuse_existing((rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", corners_dir, snap_dir, evidence_store.manifest_path(SLUG, record_id)))
        res = analyze_variant(variant, run_dir, man, corners_dir)
        # per-request submit commit: a retried request ran at the retry's (clean) commit, not run.json's
        submit_git = {}
        for mf in sorted(run_dir.glob("run*.json"), key=lambda p: p.stat().st_mtime):
            m = json.loads(mf.read_text())
            for s in m.get("submit_results", []):
                if s.get("variant") == variant and s.get("status") not in (None, "NO-JSON"):
                    submit_git[s["tag"]] = m["git"]["sha"] + (" (DIRTY)" if m["git"].get("dirty") else " (clean)")
        for rq in res["requests"]:
            rq["submit_git"] = submit_git.get(rq["tag"])
        table = point_table(man, res["points"], procs)
        b = binding(table)
        margin = None
        if "vpor_up" in b:
            lo, hi = man["rails"]["low_v"], man["rails"]["high_v"]
            margin = {
                "rail_v": lo, "rail_hi_v": hi,
                "vpor_up_max_v": b["vpor_up"]["max_v"], "vpor_up_max_corner": b["vpor_up"]["max_corner"],
                "vpor_up_min_v": b["vpor_up"]["min_v"], "vpor_up_min_corner": b["vpor_up"]["min_corner"],
                "margin_mv": (lo - b["vpor_up"]["max_v"]) * 1e3,
                "vpor_up_min_below_rail_mv": (lo - b["vpor_up"]["min_v"]) * 1e3,
                "vpor_up_max_below_hi_mv": (hi - b["vpor_up"]["max_v"]) * 1e3,
            }
        snap_dir.mkdir(parents=True, exist_ok=True)
        for rate, _ in all_rates(man):
            d = run_dir / variant / rate_tag(rate)
            if (d / "netlist.spice").is_file():
                shutil.copyfile(d / "netlist.spice", snap_dir / f"{variant}_{rate_tag(rate)}.spice")
                shutil.copyfile(d / "request.json", snap_dir / f"{variant}_{rate_tag(rate)}.request.json")
            if (d / "report.json").is_file():
                (corners_dir / rate_tag(rate)).mkdir(parents=True, exist_ok=True)
                (corners_dir / rate_tag(rate) / "klt-report.json").write_text(scrub((d / "report.json").read_text(), run_dir))
        probe_text = ""
        if args.probe_note_file:
            probe_text = Path(args.probe_note_file).read_text().strip()
        # This experiment's DUTs are per-variant (see `variant.dut_netlists` and the record's
        # `Netlist provenance` line), so the shared xschem note -- which names one committed
        # DUT export -- is not stated here.
        pdk_d, tools_d = sim_common.record_pdk_tools(
            pdk, pin, meta, res["points"], res["requests"],
            lib_file=f"$PDK_ROOT/{pdk.variant}/{pin['ngspice_lib']} (fleet: models.pdk={pdk.variant}, models.lib={MODEL_LIB})",
            xschem_note=None,
        )
        v = man["variants"][variant]
        art_manifest, art_summary = evidence_store.store_or_exit(SLUG, record_id, corners_dir)
        record = {
            "record_id": record_id,
            "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "author": args.author or cr.default_author(),
            "supersedes": args.supersedes,
            "manifest_excerpt": {"title": man["title"], "claim": man["claim"], "primary_rate": man["rates"]["primary_v_per_s"][0]},
            "variant": {"name": variant, "description": v["description"], "bias_treatment": v["bias_treatment"], "schematic": "sim/" + SLUG + "/" + v["schematic"], "dut_netlists": v["dut_netlists"], "provenance": v.get("provenance"), "baseline_variant": v.get("baseline_variant")},
            "pdk": pdk_d,
            "tools": tools_d,
            "git": git_info,
            "run_git": meta.get("git"),
            "matrix": {"axis": axis, "process": procs, "temperature_c": man["corners"]["temperature_c"], "peak_v": man["sweep"]["peak_v"],
                       "rates_v_per_s": [r for r, _ in all_rates(man)], "n_corners": len(procs) * len(man["corners"]["temperature_c"]), "is_subset": False,
                       "axis_note": "main = the 5 MOS process corners (the issue's 5x3 grid)" if axis == "main" else man["corners"]["passive_skew"]["note"]},
            "definitions": {**man["grading"]["definitions"], "sweep": man["sweep"]["construction"], "rates": man["rates"]["construction"], "edge extraction": f"VDD sample step <= {tx.MAX_BRACKET_V * 1e3:g} mV around an edge, linear interpolation inside the bracket; POR_RAW state evaluated for VDD >= {tx.V_VALID:g} V only"},
            "requests": res["requests"],
            "points": res["points"],
            "table": table,
            "binding": b,
            "margin": margin,
            "probe": probe_text,
            "absent_coverage": [c for c in man["absent_coverage"] if not (variant.endswith("-postlayout") and c.startswith("Post-layout parasitics are not included"))]
            + (["Post-layout scope: only por_comparator is extracted (lumped RC star per net, vertical-overlap coupling only, no lateral coupling, no distributed RC); the MOS models are rewritten 01v8 -> g5v0d10v5 because the layout lacks the hvi marker; bias_core and the testbench stimulus are schematic-level."] if variant.endswith("-postlayout") else []),
            "links": {
                "testbench": "sim/" + SLUG + "/" + v["schematic"], "manifest": f"sim/{SLUG}/experiment.json", "driver": f"sim/{SLUG}/run_thresholds_campaign.py",
                "extractor": f"sim/{SLUG}/threshold_extractor.py", "netlist_snapshots": f"sim/{SLUG}/netlist-snapshots/{record_id}/",
                "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)), "artifact_summary": str(art_summary.relative_to(REPO_ROOT)), "json": f"sim/{SLUG}/records/{record_id}.json", "record": f"sim/{SLUG}/records/{record_id}.md",
            },
        }
        rec_dir.mkdir(parents=True, exist_ok=True)
        (rec_dir / f"{record_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
        (rec_dir / f"{record_id}.md").write_text(render_md(record))
        ids.append(record_id)
        print(f"record {variant}: {record_id}  ({b['n_ok']}/{b['n_total']} corners with a clean result)")
    return 0


def cmd_selftest(_args) -> int:
    return subprocess.call([sys.executable, "-I", str(HERE / "threshold_extractor.py")])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    variants = ["ideal-bias", "real-bias-core", "ideal-bias-postlayout", "real-bias-core-postlayout"]
    r = sub.add_parser("run")
    r.add_argument("--variant", action="append", choices=variants)
    r.add_argument("--axis", choices=AXES, default="main", help="main = tt/ss/ff/sf/fs (the 5x3 grid); passive-skew = ll/hh resistor/cap sections (separate records); mc = mismatch Monte Carlo supplement (real-bias-core, tt/ss x -40/27/125 C, one request per (process, temperature), issue #348)")
    r.add_argument("--mc-process", action="append", help="mc axis only: override the monte_carlo.process list (repeat once per process, e.g. --mc-process tt --mc-process ff); recorded in run.json and honored by record (issue #455 fresh-seed ff/sf/fs extension)")
    r.add_argument("--mc-seed", type=int, help="mc axis only: override the monte_carlo.seed base (fresh-seed campaign; recorded in run.json and honored by record)")
    r.add_argument("--jobs", type=int, default=2, help="concurrent fleet submissions (max 2)")
    r.add_argument("--run-id")
    r.add_argument("--retry-failed", action="store_true")
    sim_common.add_capacity_wait_arg(r)
    r.add_argument("--allow-dirty", action="store_true", help="debugging only; such a run must not be recorded")
    p = sub.add_parser("probe")
    p.add_argument("--variant", choices=variants, default="ideal-bias")
    p.add_argument("--rate", type=float)
    p.add_argument("--process", default="tt")
    p.add_argument("--temp", type=float, default=27)
    p.add_argument("--run-id")
    r = sub.add_parser("record")
    r.add_argument("--run-id", required=True)
    r.add_argument("--variant", action="append", choices=variants)
    r.add_argument("--probe-note-file")
    r.add_argument("--author")
    r.add_argument("--supersedes")
    r.add_argument("--against-record", help="mc axis: compare this run seed-for-seed against a prior mismatch-mc record id (issue #401)")
    r.add_argument("--allow-dirty", action="store_true")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    return {"run": cmd_run, "probe": cmd_probe, "record": cmd_record, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
