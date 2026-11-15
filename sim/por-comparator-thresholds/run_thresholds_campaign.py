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


def mc_units(man: dict) -> list[tuple[str, float, int]]:
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
    mc = man["monte_carlo"]
    return [(p, t, i + 1) for i, (p, t) in enumerate((p, t) for p in mc["process"] for t in mc["temperature_c"])]


def mc_request_seed(man: dict, offset: int) -> int:
    return man["monte_carlo"]["seed"] + offset


def build_mc_request(proc: str, temp: float, offset: int, man: dict, backend: str, capacity_wait_s: float = 0) -> dict:
    """ONE mismatch Monte Carlo request: one `_mm` process section, one temperature, N mismatch samples.

    The `_mm` .lib section turns on the model library's local-mismatch sigmas and klt's
    `monte_carlo` block (vary=mismatch) re-runs the single corner point N times with
    per-sample seeds derived from `seed`.  Local mismatch only -- this is never
    MC_PR_SWITCH global process Monte Carlo."""
    mc = man["monte_carlo"]
    sw = man["sweep"]
    rate = mc["rate_v_per_s"]
    tstop = tstop_for(rate, man)
    return sim_common.base_request(
        "netlist.spice", backend,
        {"process": [f"{proc}_mm"], "supply_v": {"vset": [sw["peak_v"]]}, "temperature_c": [temp]},
        {"kind": "tran", "args": f"1u {tstop:.9g} 0 {sw['tmax_s']:.3g}"},
        [
            {"name": "vdd_end", "spice": f".meas tran vdd_end FIND v(vdd) AT={tstop - 1e-6:.9g}", "unit": "V"},
            {"name": "por_raw_max", "spice": ".meas tran por_raw_max MAX v(por_raw)", "unit": "V"},
        ],
        1500, capacity_wait_s,
        monte_carlo={"n": mc["n_per_corner"], "seed": mc_request_seed(man, offset), "vary": mc["vary"]},
    )


def mc_dir(run_dir: Path, variant_name: str, proc: str, temp: float) -> Path:
    """One MC request's directory, under the run dir next to the rate-tag dirs the main axis uses."""
    return run_dir / variant_name / f"mc_{proc}_{cr.fmt_temp(temp)}c"


def submit_mc(unit: tuple[str, float, int], variant_name: str, head: str, man: dict, run_dir: Path, capacity_wait_s: float) -> dict:
    proc, temp, offset = unit
    mc = man["monte_carlo"]
    netlist = build_netlist(head, man["variants"][variant_name], mc["rate_v_per_s"])
    req = build_mc_request(proc, temp, offset, man, "batch", capacity_wait_s)
    d = mc_dir(run_dir, variant_name, proc, temp)
    label = f"{proc}/{cr.fmt_temp(temp)}C"
    res = sim_common.submit_prepared(
        d, netlist, req,
        f"{variant_name} mc {label}: N={mc['n_per_corner']} mismatch samples, seed {req['monte_carlo']['seed']} -> batch fleet",
        f"{variant_name} mc {label}",
        retry=sim_common.cap_retry(d, f"mc {label}", 180, max_retries=59))
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
        work = list(mc_units(man))
        if args.retry_failed:
            work = [(p, t, o) for p, t, o in work
                    if not sim_common.report_usable(mc_dir(run_dir, variants[0], p, t) / "report.json")]
    else:
        variants = args.variant or [v for v in man["variants"] if not v.endswith("-postlayout")]  # post-layout variants only on explicit --variant
        work = [(v, r) for v in variants for r, _ in all_rates(man)]
        if args.retry_failed:
            work = [(v, r) for v, r in work if not sim_common.report_usable(run_dir / v / rate_tag(r) / "report.json")]
    heads = {v: tb_netlist_head(man["variants"][v], run_dir / ("retry" if args.retry_failed else "."), pdk) for v in variants}
    meta = {
        "run_id": run_id,
        "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variants": variants,
        "axis": axis,
        "process": processes(man, axis),
        "git": git_info,
        "klt_client": sim_common.klt_version(),
        "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"),
        "work": [list(item) for item in work],
    }
    if axis == "mc":
        mc = man["monte_carlo"]
        meta.update({
            "monte_carlo": {"n_per_corner": mc["n_per_corner"], "seed": mc["seed"], "vary": mc["vary"],
                            "rate_v_per_s": mc["rate_v_per_s"], "variant": variants[0],
                            "requests": [{"process": p, "temperature_c": t, "seed_offset": o, "seed": mc_request_seed(man, o)} for p, t, o in mc_units(man)],
                            "request_sizing": mc["request_sizing"]},
        })
    n_units = (f"{len(work)} requests x N={man['monte_carlo']['n_per_corner']} mismatch samples"
               if axis == "mc" else f"{len(work)} request(s)")
    say(f"run id {run_id}: {n_units}")
    if axis == "mc":
        results = sim_common.fan_out(
            lambda u: submit_mc(u, variants[0], heads[variants[0]], man, run_dir, args.capacity_wait), work, args.jobs)
    else:
        results = sim_common.fan_out(
            lambda vr: submit(vr[0], vr[1], heads[vr[0]], man, run_dir, args.capacity_wait, axis), work, args.jobs)
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


def mc_samples(rep: dict, man: dict, corners_dir: Path, run_dir: Path) -> list[dict]:
    """Per-sample extraction of ONE mismatch-MC request's report (one (process, temperature) corner).

    Each sample is its own `corners[]` entry with its own waveform artifact, so VPOR-up /
    VPOR-down are extracted from each realisation's own transient and hysteresis is formed
    WITHIN the sample.  A per-sample log and change-triggered trace are staged as fleet
    evidence; the returned list is sorted by sample index."""
    out = []
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
        pt["valid"], pt["reason"] = classify_mc_sample(pt["extract"])
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
    """Change-triggered trace (VDD, POR_RAW, VREF, IBIAS): a row whenever a column moved >= dv, or an anchor."""
    cols = [c for c in ("time", "v(vdd)", "v(por_raw)", "v(vref)", "v(ibias)") if c in wave]
    t = wave["time"]
    rows, last = [], None
    for i in range(len(t)):
        cur = [wave[c][i] for c in cols[1:]]
        if last is None or i == len(t) - 1 or any(abs(a - b) >= dv for a, b in zip(cur, last[1])) or t[i] - last[0] >= anchor_s:
            rows.append([t[i]] + cur)
            last = (t[i], cur)
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
                pt["error_class"] = "model_not_found" if "could not find a valid modelname" in log_text else "no waveform retrieved"
            deck = Path(art["deck"]).read_text() if art.get("deck") and Path(art["deck"]).is_file() else "(no deck retrieved)"
            header = [f"# point: {SLUG} {variant} {tag} {cid}", f"# process={proc} temp={cr.fmt_temp(temp)}C rate={rate:g} V/s tstop={tstop_for(rate, man):.6g}s klt status: {c.get('status')}"]
            body = header + ["", "# ==== klt sim deck ====", *[f"| {ln}" for ln in deck.splitlines()], "", "# ==== klt diagnostics ====",
                             *[f"| {g['severity']}/{g['code']}: {g['message']}" for g in pt["diagnostics"]], "", "# ==== ngspice stdout+stderr ====", log_text.rstrip(), ""]
            (corners_dir / tag).mkdir(parents=True, exist_ok=True)
            (corners_dir / tag / f"{cid}.log").write_text(scrub("\n".join(body), run_dir))
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
            "vref_max_v", "klt_status", "runtime_s", "seed", "process_seed", "mismatch_seed"]
    lines = [",".join(cols)]
    for s in samples:
        ex = s.get("extract") or {}
        up = (ex.get("up") or {}).get("vdd_v")
        dn = (ex.get("down") or {}).get("vdd_v")
        hys = ex.get("hysteresis_v")
        vref = s.get("vref_max_v")
        lines.append(",".join([
            proc, f"{temp:g}", str(s["sample"]), str(int(s["valid"])), (s.get("reason") or "").replace(",", ";"),
            "" if up is None else f"{up:.7g}",
            "" if dn is None else f"{dn:.7g}",
            "" if hys is None else f"{hys:.7g}",
            "" if vref is None else f"{vref:.7g}",
            str(s.get("klt_status")), f"{s.get('runtime_s'):g}" if s.get("runtime_s") is not None else "",
            str(s.get("seed")), str(s.get("process_seed")), str(s.get("mismatch_seed")),
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
    for c in rec["corners"]:
        cid = f"{c['process']}/{cr.fmt_temp(c['temperature_c'])}C"
        st = c["stats"]
        res = st["sigma_resolution"]
        L.append(f"| {cid} | {st['n_valid']}/{st['n_samples']} | {fms(st['stats'], 'vpor_up_v')} | {fms(st['stats'], 'vpor_down_v')} | "
                 f"{fms(st['stats'], 'hysteresis_v', 1e3, '.1f')} | {f'{res:.1%}' if res is not None else 'n/a'} | "
                 f"{len(st['excluded'])}{' (' + st['result'] + ')' if st['result'] != 'OK' else ''} |")
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
                        "reference -- not a bias_core startup failure; the cause is not established further here."
                        if vrefs and len(vrefs) == len(stuck) else
                        (f" Max v(vref) over the sweep among them: {min(vrefs):.3f}-{max(vrefs):.3f} V." if vrefs else
                         " No v(vref) waveform was retrieved for them, so a reference-side cause is not excluded."))
            L.append(f"**Failed-release realisations.** {len(stuck)} of the {sum(c['stats']['n_samples'] for c in rec['corners'])} samples "
                     f"graded `no_transition` with POR_RAW **held low through the entire sweep** -- in those realisations reset never "
                     f"releases within the 3.63 V peak.{vref_txt}")
            L.append(f"The per-corner distributions above therefore describe only the **releasing subset** of each corner; the failed-release "
                     f"fraction is part of the mismatch behaviour this record measures, and DR-004's corner margin does not capture it.")
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
    mc = man["monte_carlo"]
    variant = meta["variants"][0]
    stamp = now
    record_id = f"{stamp:%Y%m%d}-{stamp:%H%M%S}-{git_info['sha']}-{variant}-mismatch-mc"
    rec_dir, snap_dir = HERE / "records", HERE / "netlist-snapshots" / record_id
    corners_dir = evidence_store.stage_dir_for(SLUG, record_id)  # git-ignored scratch; stored below
    sim_common.refuse_existing((rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", corners_dir, snap_dir, evidence_store.manifest_path(SLUG, record_id)))
    v = man["variants"][variant]
    units = [(p, t, o) for p, t, o in mc_units(man)]
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
        rq = {"process": proc, "temperature_c": temp, "seed_offset": offset, "seed": mc_request_seed(man, offset),
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
                        "seed_offsets": mc["seed_offsets"]},
        "matrix": {"axis": "mc", "process": processes(man, "mc"), "temperature_c": mc["temperature_c"], "peak_v": man["sweep"]["peak_v"],
                   "rates_v_per_s": [mc["rate_v_per_s"]], "n_corners": len(units), "is_subset": True,
                   "axis_note": "mismatch Monte Carlo supplement: real-bias-core only, _mm sections (local mismatch), primary rate only, no half-rate guard"},
        "definitions": {**man["grading"]["definitions"],
                        "mismatch sample": mc["execution"],
                        "edge extraction": f"VDD sample step <= {tx.MAX_BRACKET_V * 1e3:g} mV around an edge, linear interpolation inside the bracket; POR_RAW state evaluated for VDD >= {tx.V_VALID:g} V only"},
        "requests": requests,
        "corners": corners,
        "probe": "",
        "absent_coverage": man["absent_coverage"],
        "links": {
            "testbench": "sim/" + SLUG + "/" + v["schematic"], "manifest": f"sim/{SLUG}/experiment.json", "driver": f"sim/{SLUG}/run_thresholds_campaign.py",
            "extractor": f"sim/{SLUG}/threshold_extractor.py", "netlist_snapshots": f"sim/{SLUG}/netlist-snapshots/{record_id}/",
            "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)), "artifact_summary": str(art_summary.relative_to(REPO_ROOT)), "json": f"sim/{SLUG}/records/{record_id}.json", "record": f"sim/{SLUG}/records/{record_id}.md",
        },
    }
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / f"{record_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
    (rec_dir / f"{record_id}.md").write_text(render_mc_md(record))
    ok = sum(1 for c in corners if c["stats"]["result"] == "OK")
    print(f"record {variant}: {record_id}  ({ok}/{len(corners)} corners with a distribution, "
          f"{sum(c['stats']['n_valid'] for c in corners)} valid samples of {mc['n_per_corner'] * len(units)})")
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
    r.add_argument("--jobs", type=int, default=2, help="concurrent fleet submissions (max 2)")
    r.add_argument("--run-id")
    r.add_argument("--retry-failed", action="store_true")
    r.add_argument("--capacity-wait", type=float, default=0)
    r.add_argument("--allow-dirty", action="store_true", help="debugging only; such a run must not be recorded")
    p = sub.add_parser("probe")
    p.add_argument("--variant", choices=variants, default="ideal-bias")
    p.add_argument("--rate", type=float)
    p.add_argument("--process", default="tt")
    p.add_argument("--temp", type=float, default=27)
    p.add_argument("--run-id")
    c = sub.add_parser("record")
    c.add_argument("--run-id", required=True)
    c.add_argument("--variant", action="append", choices=variants)
    c.add_argument("--probe-note-file")
    c.add_argument("--author")
    c.add_argument("--supersedes")
    c.add_argument("--allow-dirty", action="store_true")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    return {"run": cmd_run, "probe": cmd_probe, "record": cmd_record, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
