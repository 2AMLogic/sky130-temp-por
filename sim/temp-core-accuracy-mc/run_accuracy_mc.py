#!/usr/bin/env python3
"""Full-signal-path mismatch Monte Carlo of temp_core: temperature error in degC, per-term attribution (issue #105).

Question: how large is the temperature error of the PTAT output of ``temp_core`` (sky130, plain
uncompensated DVBE core) under 3-sigma device mismatch, untrimmed and with a 1-point (27 C) gain
trim -- the DR-003 row-2 (``[TBD-1]``) structure -- and how much of it comes from each term (PNP
pair, amplifier offset, resistor ratio, mirror)?

Execution model (host rules): every Monte Carlo grid is ONE ``klt sim`` request with a
``monte_carlo`` block, submitted to the Spot batch fleet with an explicit ``--backend batch``.
This script NEVER launches ngspice over a grid itself and never falls back to a local grid if the
fleet refuses; refusals are recorded and the record says NOT-RUN.  ``probe`` runs SINGLE local
points only (a debug check, not evidence).

One request per *term* (all share the same corners, seed and N):

  nominal  no mismatch, plain process sections (the per-corner reference curve; no monte_carlo)
  none     negative control: ``_mm`` section, every device wrapped with sigma=0  -> spread must be 0
  pnp / amp / res / mirror / other   exactly one device group has mismatch live, the rest are wrapped
  all      every device has mismatch live (the aggregate)

A device is switched off by instantiating it through a ``mmoff_*`` wrapper subckt that re-declares the
model library's mismatch-sigma ``.param``s as 0 inside the wrapper scope (verified: the wrapped
instance equals the no-mismatch value exactly, an unwrapped sibling in the same deck does not).

Temperature is swept INSIDE each ngspice process (``dc temp -40 125 1``), not as a klt corner axis:
klt derives the per-sample seed from the corner index, so a temperature corner axis would draw a
DIFFERENT device realisation at each temperature and the PTAT-vs-T curve of a "sample" would be
meaningless.  The mismatch AGAUSS values are evaluated once at parse time, so one sample is one
device realisation across the whole temperature range.

Stages:  run | probe | record
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import statistics
import subprocess
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
SLUG = "temp-core-accuracy-mc"
BUILD = REPO_ROOT / "sim" / "build" / SLUG
MODEL_LIB = sim_common.MODEL_LIB
say = sim_common.say

PROCS = ["tt", "ss", "ff", "sf", "fs"]
SUPPLIES = [2.97, 3.3, 3.63]
TEMPS = [-40, 27, 125]  # the three evaluation temperatures (sweep is -40..125 step 1)
T_LO, T_HI, T_REF = -40, 125, 27
DEFAULT_N = 30
DEFAULT_SEED = 20261010

# Operating-point guards (physical-branch windows copied unchanged from the #86 solver campaign,
# plus a loop-closure check specific to a DC solve). A sample failing ANY guard at ANY of the three
# temperatures is INVALID: it is excluded from the statistics and counted/disclosed, never trimmed.
GUARDS = {
    "ptat_V": (0.3, 2.6), "ctat_V": (0.2, 1.1), "isup_A": (1e-8, 5e-5),
    "na_nb_abs_diff_V": (0.0, 0.1),  # amplifier loop closed: |V(NA)-V(NB)| (offset+finite gain is mV-scale)
    # Branch consistency (added after record 20261011-165400-69d13ac, Judge review of #167): the amplifier's
    # input-referred error V(NA)-V(NB) of ONE device realisation is set by its offset + finite gain and moves
    # only slowly with temperature (<= 0.32 mV over -40..125 C in every sample of that record that is on the
    # physical branch, even with several mV of offset). A DC solution that lands on a different branch at a
    # single temperature breaks loop closure there only, so the per-sample spread
    # max_T |d(T) - median_T d|, d = V(NA)-V(NB), is the branch-jump signature. Window: 0.5 mV.
    "na_nb_T_spread_V": (0.0, 5e-4),
}
BRANCH_GUARD = "na_nb_T_spread_V"
# Secondary off-trend scan (disclosure only, not a guard): deviation of the 27 C PTAT error from the chord
# through the -40 C and 125 C errors, in degC. Samples passing every guard but exceeding this are listed.
OFFTREND_SCAN_DEGC = 2.0

# ---------------------------------------------------------------------------------------------
# terms: which temp_core instances belong to which attribution group.  Everything in bias_core and
# every temp_core device not listed is group "other".
GROUPS = {
    "pnp": ["XQ1"] + [f"XQ8{c}" for c in "ABCDEFGH"],
    "amp": ["XMI1", "XMI2", "XML1", "XML2"],  # input pair + current-mirror load (offset sources)
    "res": ["XR1", "XR2", "XR2TRIM"],  # PTAT gain ratio (R2+R2TRIM)/R1
    "mirror": ["XMP1", "XMP2", "XMP3", "XMPC1", "XMPC2", "XMPC3"],  # branch-current mirror + cascodes
}
TERMS = ["pnp", "amp", "res", "mirror", "other"]
RUN_TERMS = ["none", *TERMS, "all"]  # + "nominal" (no mismatch)

# kind -> (zeroed sigma params, wrapper header, inner call template)
WRAP = {
    "pfet": ("sky130_fd_pr__pfet_g5v0d10v5", ["sw_mm_vth0_sky130_fd_pr__pfet_g5v0d10v5"],
             "d g s b", "l=1 w=1 nf=1 ad=0 as=0 pd=0 ps=0 nrd=0 nrs=0 sa=0 sb=0 sd=0 mult=1"),
    "nfet": ("sky130_fd_pr__nfet_g5v0d10v5", ["sw_mm_vth0_sky130_fd_pr__nfet_g5v0d10v5"],
             "d g s b", "l=1 w=1 nf=1 ad=0 as=0 pd=0 ps=0 nrd=0 nrs=0 sa=0 sb=0 sd=0 mult=1"),
    "pnp": ("sky130_fd_pr__pnp_05v5_W3p40L3p40",
            ["sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is", "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf"],
            "c b e", "mult=1"),
    "res": ("sky130_fd_pr__res_xhigh_po",
            ["sw_mm_sky130_fd_pr__res_xhigh_po", "sw_mm_sky130_fd_pr__res_generic_po_head"],
            "r0 r1 sub", "w=1 l=1 mult=1"),
    "cap": ("sky130_fd_pr__cap_mim_m3_1", ["sw_mm_cmim"], "c0 c1", "w=1 l=1 mult=1 mf=1"),
}
MODEL_KIND = {v[0]: k for k, v in WRAP.items()}


def wrapper_defs():
    out = []
    for kind, (model, zeros, pins, params) in WRAP.items():
        names = [p.split("=")[0] for p in params.split()]
        call = " ".join(f"{n}={{{n}}}" for n in names if n != "mf")
        out += [f".subckt mmoff_{kind} {pins} {params}",
                ".param " + " ".join(f"{z}=0" for z in zeros),
                f"Xi {pins} {model} {call}", ".ends", ""]
    return "\n".join(out)


def join_continuations(text):
    lines = []
    for ln in text.splitlines():
        if ln.startswith("+") and lines:
            lines[-1] += " " + ln[1:].strip()
        else:
            lines.append(ln)
    return lines


def temp_core_group(inst):
    for g, members in GROUPS.items():
        if inst.upper() in members:
            return g
    return "other"


def transform_cell(name, active):
    """Return the cell netlist with every device whose group is not in ``active`` routed through its mmoff wrapper."""
    txt = (REPO_ROOT / "design" / "netlist" / f"{name}.spice").read_text()
    out = []
    for ln in join_continuations(txt):
        tok = ln.split()
        if tok and tok[0].upper().startswith("X") and not ln.startswith(("*", ".")):
            model_i = next((i for i, t in enumerate(tok) if t.startswith("sky130_fd_pr__")), None)
            if model_i is not None:
                grp = temp_core_group(tok[0]) if name == "temp_core" else "other"
                kind = MODEL_KIND[tok[model_i]]
                if grp not in active:
                    declared = set(WRAP[kind][3].split()) and {p.split("=")[0] for p in WRAP[kind][3].split()}
                    for t in tok[model_i + 1:]:
                        k = t.split("=")[0].lower()
                        if k != "m" and k not in declared:
                            raise SystemExit(f"{tok[0]}: instance param {k} not declared by mmoff_{kind} wrapper")
                    tok[model_i] = f"mmoff_{kind}"
                ln = " ".join(tok)
        out.append(ln)
    return "\n".join(l for l in out if l.strip().lower() != ".end") + "\n"


def build_netlist(term):
    if term in ("nominal", "all"):
        active = set(TERMS)
    elif term == "none":
        active = set()
    else:
        active = {term}
    lines = [
        f"* generated by sim/{SLUG}/run_accuracy_mc.py (term={term}) -- do not edit",
        "* DC temperature sweep inside one ngspice process; EN tied to VDD; bias_core + temp_core as in the #86 solver bench.",
        "* ng_nomodcheck: carried in the netlist because the fleet runner ignores options.ngspice_init",
        *sim_common.NOMODCHECK_CONTROL.splitlines(),
        ".options wnflag=1",
        "VSUP VDD 0 3.3",
        "XBIAS VDD 0 IBIAS VREF BIAS_OK bias_core",
        "XDUT VDD 0 IBIAS VDD PTAT CTAT temp_core",
        "",
        wrapper_defs() if term not in ("nominal", "all") else "",
        transform_cell("bias_core", active),
        transform_cell("temp_core", active),
        ".end",
    ]
    return "\n".join(lines) + "\n"


def measurements():
    ms = []
    for t in TEMPS:
        tag = f"{'m' if t < 0 else 'p'}{abs(t)}"
        for nm, expr, unit in (("ptat", "v(ptat)", "V"), ("ctat", "v(ctat)", "V"), ("na", "v(xdut.na)", "V"),
                               ("nb", "v(xdut.nb)", "V"), ("isup", "i(vsup)", "A")):  # i(vsup) is negative when sourcing; negated in analysis
            ms.append({"name": f"{nm}_{tag}", "spice": f".meas dc {nm}_{tag} FIND {expr} AT={t}", "unit": unit})
    return ms


def build_request(term, backend, n, seed, corners=None, timeout=1800):
    procs, supplies = corners or (PROCS, SUPPLIES)
    mm = term != "nominal"
    return sim_common.base_request(
        "netlist.spice", backend,
        {"process": [f"{p}_mm" if mm else p for p in procs], "supply_v": {"vsup": supplies},
         "temperature_c": [T_REF]},
        {"kind": "dc", "args": f"temp {T_LO} {T_HI} 1"},
        measurements(),
        timeout,
        waveforms=False,
        monte_carlo={"n": n, "seed": seed, "vary": "mismatch"} if mm else None,
    )


def cmd_run(args):
    now = datetime.now(timezone.utc)
    git = cr.git_state()
    if git.get("dirty") and not args.allow_dirty:
        sys.exit("working tree is dirty: commit first so the record is provenance-clean (or --allow-dirty for a scratch run)")
    run_id = args.run_id or f"{now:%Y%m%d-%H%M%S}-{git['sha']}"
    run_dir = BUILD / run_id
    run_dir.mkdir(parents=True, exist_ok=args.resume)
    terms = args.term or ["nominal", *RUN_TERMS]
    this = {"started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "klt_client": sim_common.klt_version(),
            "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"), "git": git, "terms": terms,
            "n": args.n, "seed": args.seed}
    if args.resume and (run_dir / "run.json").is_file():
        meta = json.loads((run_dir / "run.json").read_text())
        meta.setdefault("resumes", []).append(this)
        cur = this
    else:
        meta = {"run_id": run_id, **this}
        cur = meta
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")

    def usable(rp):
        """a report with at least one corner that actually produced values (an all-error report, e.g. batch_job_timeout, is NOT usable)"""
        try:
            return any(c.get("status") != "error" for c in json.loads(rp.read_text()).get("corners", []))
        except (OSError, json.JSONDecodeError):
            return False

    def one(unit):
        term, proc = unit
        d = run_dir / term / proc if proc else run_dir / term
        if usable(d / "report.json"):
            return {"term": term, "proc": proc, "skipped": "usable report exists"}
        d.mkdir(parents=True, exist_ok=True)
        (d / "netlist.spice").write_text(build_netlist(term))
        seed = args.seed + (PROCS.index(proc) if proc else 0)
        (d / "request.json").write_text(json.dumps(build_request(term, "batch", args.n, seed, ([proc], SUPPLIES) if proc else None), indent=2) + "\n")
        units = (1 if term == "nominal" else args.n) * len(SUPPLIES) * (1 if proc else len(PROCS))
        say(f"[submit] {term}/{proc or 'all-proc'}: {units} ngspice units -> batch fleet")
        for attempt in range(1, 61):
            p = subprocess.run(["klt", "sim", str(d / "request.json"), "--backend", "batch", "-o", str(d / "out"), "--format", "json"],
                               capture_output=True, text=True, timeout=3 * 3600)
            # the fleet has a shared instance cap; a refused LAUNCH is retried later (never replaced by a local grid)
            if "BATCH_MAX_CONCURRENT_INSTANCES" in p.stdout + p.stderr and attempt < 60:
                (d / f"launch-refused-{attempt}.txt").write_text(p.stdout + p.stderr)
                time.sleep(180)
                continue
            break
        (d / "report.json").write_text(p.stdout)
        (d / "klt.stderr").write_text(p.stderr)
        try:
            st = json.loads(p.stdout).get("status", "?")
        except json.JSONDecodeError:
            st = "NO-JSON"
        say(f"[done]   {term}/{proc or 'all-proc'}: exit {p.returncode}, status {st}")
        return {"term": term, "proc": proc, "exit": p.returncode, "status": st}

    units_list = [(t, None) if t == "nominal" else (t, pr) for t in terms for pr in ([None] if t == "nominal" else PROCS)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, args.jobs)) as ex:
        for f in [ex.submit(one, u) for u in units_list]:
            try:
                results.append(f.result())
            except Exception as err:  # noqa: BLE001 -- recorded
                results.append({"error": repr(err)})
                say(f"[error] {err!r}")
    cur["submit_results"] = results
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def cmd_probe(args):
    """SINGLE-corner LOCAL probe (never a grid): one process/supply, n samples (default 3)."""
    run_dir = BUILD / args.run_id
    for term in args.term:
        d = run_dir / "probe" / term
        d.mkdir(parents=True, exist_ok=True)
        (d / "netlist.spice").write_text(build_netlist(term))
        req = build_request(term, "local", args.n, args.seed, ([args.process], [args.supply]))
        (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
        say(f"[probe] local single corner {term} {args.process} {args.supply} V, n={args.n}")
        pr = subprocess.run(["klt", "sim", str(d / "request.json"), "--backend", "local", "-o", str(d / "out"), "--format", "json"],
                            capture_output=True, text=True, timeout=3600)
        (d / "report.json").write_text(pr.stdout)
        (d / "klt.stderr").write_text(pr.stderr)
        say(f"[probe] exit {pr.returncode}")
    return 0


# ---------------------------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------------------------

SOLVER_RECORD = "sim/temp-core-startup-solver/records/20261010-200708-47b96e5"
PNP_RECORD = "sim/pnp-mismatch/records/20260825-220116-a9cac4b"
FIELDS = ["ptat", "ctat", "na", "nb", "isup"]


def tagT(t):
    return f"{'m' if t < 0 else 'p'}{abs(t)}"


def parse_cid(cid):
    parts = cid.split("/")
    proc = parts[0].removesuffix("_mm")
    supply = float(parts[1].rstrip("V"))
    sample = int(parts[3][2:]) if len(parts) > 3 and parts[3].startswith("mc") else None
    return proc, supply, sample


def load_term(run_dir, term):
    """-> {'report': dict|None, 'refusal': ..., 'missing_procs': [...], 'corners': {(proc, supply): {sample|None: {meas...} | {'_error': str}}}}

    nominal is one request; every mismatch term is one request PER PROCESS section (the fleet job limit is ~1 h at
    concurrency 1), merged here.  A process whose request has no usable report is listed in missing_procs."""
    ent = {"report": None, "refusal": None, "missing_procs": [], "jobs": {}, "corners": {}}
    dirs = [(None, run_dir / term)] if term == "nominal" else [(p, run_dir / term / p) for p in PROCS]
    reps = []
    for proc, d in dirs:
        rp = d / "report.json"
        rep = None
        try:
            rep = json.loads(rp.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        if rep and any(c.get("status") != "error" for c in rep.get("corners", [])):
            reps.append((proc, rep))
        else:
            ent["missing_procs"].append(proc or "all")
            why = None
            try:
                doc = json.loads((d / "klt.stderr").read_text() or "{}")
                why = doc.get("error")
            except (OSError, json.JSONDecodeError):
                pass
            if not why and rep:
                codes = (rep.get("diagnostic_counts") or {}).get("by_code")
                why = {"message": f"report has no usable corner; diagnostics {codes}; remote state {(rep.get('environment') or {}).get('remote', {}).get('state')}"}
            ent["refusal"] = why or {"message": "no usable report", "code": "unknown"}
    if reps:
        ent["report"] = {"corners": [], "environment": reps[0][1]["environment"]}
        for proc, rep in reps:
            ent["report"]["corners"] += rep["corners"]
            ent["jobs"][proc or "all"] = rep["environment"].get("remote", {})
            for c in rep["corners"]:
                pr_, supply, smp = parse_cid(c["corner_id"])
                vals = {m["name"]: m.get("value") for m in c["measurements"]}
                if c.get("status") == "error" or any(v is None for v in vals.values()):
                    vals = {**vals, "_error": f"klt corner status {c.get('status')}; unextractable: "
                            + ",".join(sorted(k for k, v in vals.items() if v is None))}
                ent["corners"].setdefault((pr_, supply), {})[smp] = vals
    return ent


def na_nb_T_spread(v):
    d = [v[f"na_{tagT(t)}"] - v[f"nb_{tagT(t)}"] for t in TEMPS]
    med = sorted(d)[len(d) // 2]
    return max(abs(x - med) for x in d)


def guard_check(v, branch_guard=True):
    """-> list of reason strings (empty = valid operating point at all three temperatures).

    branch_guard=False reproduces the guard set of record 20261011-165400-69d13ac (used only to report the
    headline with and without the branch-consistency guard)."""
    if "_error" in v:
        return [v["_error"]]
    why = []
    for t in TEMPS:
        g = tagT(t)
        x = {"ptat_V": v[f"ptat_{g}"], "ctat_V": v[f"ctat_{g}"], "isup_A": -v[f"isup_{g}"],
             "na_nb_abs_diff_V": abs(v[f"na_{g}"] - v[f"nb_{g}"])}
        for k, val in x.items():
            lo, hi = GUARDS[k]
            if not (math.isfinite(val) and lo <= val <= hi):
                why.append(f"{k}@{t}C={val:.4g} outside [{lo:g},{hi:g}]")
    p = [v[f"ptat_{tagT(t)}"] for t in TEMPS]
    if not (p[0] < p[1] < p[2]):
        why.append("PTAT not monotonic in T over -40/27/125")
    if branch_guard:
        sp = na_nb_T_spread(v)
        lo, hi = GUARDS[BRANCH_GUARD]
        if not (math.isfinite(sp) and lo <= sp <= hi):
            why.append(f"{BRANCH_GUARD}={sp:.4g} outside [{lo:g},{hi:g}] (V(NA)-V(NB) not consistent over T: suspected DC branch jump)")
    return why


def offtrend_degC(v, nom):
    """Deviation of the 27 C PTAT error from the chord through the -40/125 C errors, in degC (disclosure scan)."""
    s_nom = (nom["ptat_p125"] - nom["ptat_m40"]) / (T_HI - T_LO)
    e = [v[f"ptat_{tagT(t)}"] - nom[f"ptat_{tagT(t)}"] for t in TEMPS]
    return (e[1] - (e[0] + (e[2] - e[0]) * (T_REF - T_LO) / (T_HI - T_LO))) / s_nom


def errors(v, nom):
    """degC errors of one VALID sample against the same-corner nominal curve."""
    out = {}
    for sig, sgn in (("ptat", None), ("ctat", None)):
        s_nom = (nom[f"{sig}_p125"] - nom[f"{sig}_m40"]) / (T_HI - T_LO)
        gain = nom[f"{sig}_p27"] / v[f"{sig}_p27"] if sig == "ptat" else None
        for t in TEMPS:
            g = tagT(t)
            raw = (v[f"{sig}_{g}"] - nom[f"{sig}_{g}"]) / s_nom
            if sig == "ptat":  # 1-point trim: multiplicative gain trim to nominal at 27 C
                trim = (v[f"{sig}_{g}"] * gain - nom[f"{sig}_{g}"]) / s_nom
            else:  # CTAT has no gain: 1-point trim is an additive offset trim at 27 C
                trim = ((v[f"{sig}_{g}"] - (v[f"{sig}_p27"] - nom[f"{sig}_p27"])) - nom[f"{sig}_{g}"]) / s_nom
            out[(sig, "untrimmed", t)] = raw
            out[(sig, "trim1", t)] = trim
    return out


def stat(xs):
    n = len(xs)
    sd = statistics.stdev(xs) if n > 1 else float("nan")
    return {"n": n, "mean": statistics.fmean(xs) if n else float("nan"), "sd": sd, "k3sd": 3 * sd,
            "max_abs": max(abs(x) for x in xs) if n else float("nan")}


def analyse_term(ent, nominal_ent, branch_guard=True):
    """Per-(proc,supply) statistics for one mismatch term."""
    res = {}
    for key, samples in sorted(ent["corners"].items()):
        nom = nominal_ent["corners"].get(key, {}).get(None)
        nom_why = guard_check(nom, branch_guard) if nom else ["nominal point missing"]
        invalid = []
        errs = {}
        valid_vals = {}
        for smp, v in sorted(samples.items()):
            why = guard_check(v, branch_guard)
            if why:
                invalid.append({"sample": smp, "reasons": why})
            elif not nom_why:
                valid_vals[smp] = v
                for k, e in errors(v, nom).items():
                    errs.setdefault(k, []).append(e)
        res[key] = {"n_total": len(samples), "n_valid": len(valid_vals), "invalid": invalid, "nominal_invalid": nom_why,
                    "offtrend": sorted(((smp, offtrend_degC(v, nom)) for smp, v in valid_vals.items()
                                        if abs(offtrend_degC(v, nom)) > OFFTREND_SCAN_DEGC), key=lambda x: -abs(x[1])),
                    "max_abs_offtrend_degC": max((abs(offtrend_degC(v, nom)) for v in valid_vals.values()), default=None),
                    "stats": {k: stat(xs) for k, xs in errs.items()},
                    "max_dev_from_nominal_V": (max(abs(v[f"ptat_{tagT(t)}"] - nom[f"ptat_{tagT(t)}"]) for v in valid_vals.values() for t in TEMPS)
                                               if valid_vals and nom else None)}
    return res


def worst_over_T(corner_stats, sig, mode):
    ts = TEMPS if mode == "untrimmed" else [T_LO, T_HI]
    c = [(corner_stats["stats"][(sig, mode, t)]["k3sd"], t) for t in ts if (sig, mode, t) in corner_stats["stats"]]
    return max(c) if c else (float("nan"), None)


def term_summary(an, sig="ptat"):
    """Aggregate a term's per-corner stats: worst corner, tt/3.30, and RMS-pooled across corners."""
    out = {}
    for mode in ("untrimmed", "trim1"):
        rows = {key: worst_over_T(cs, sig, mode) for key, cs in an.items() if cs["n_valid"] > 1}
        if not rows:
            out[mode] = None
            continue
        wk = max(rows, key=lambda k: rows[k][0])
        ts = TEMPS if mode == "untrimmed" else [T_LO, T_HI]
        pooled = {}
        for t in ts:
            vs = [an[k]["stats"][(sig, mode, t)]["sd"] ** 2 for k in rows]
            pooled[t] = 3 * math.sqrt(statistics.fmean(vs))
        out[mode] = {"worst_corner": {"corner": f"{wk[0]}_{wk[1]:.2f}V", "k3sd": rows[wk][0], "at_T": rows[wk][1]},
                     "tt_3p30": ({"k3sd": rows[("tt", 3.3)][0], "at_T": rows[("tt", 3.3)][1]} if ("tt", 3.3) in rows else None),
                     "pooled_k3sd_by_T": pooled, "pooled_worst": max(pooled.values()),
                     "n_valid": sum(an[k]["n_valid"] for k in an), "n_total": sum(an[k]["n_total"] for k in an)}
    return out


def transient_crosscheck(nominal_ent):
    """Compare the nominal DC-sweep PTAT/CTAT against the #86 EN-high `base` transient values (same PVT points)."""
    logs = REPO_ROOT / SOLVER_RECORD.replace("records", "corners") / "en-high__base"
    rows, worst = [], {"d_ptat": (0.0, None), "d_ctat": (0.0, None)}
    for (proc, supply), smp in sorted(nominal_ent["corners"].items()):
        v = smp.get(None)
        if not v or "_error" in v:
            continue
        for t in TEMPS:
            f = logs / f"{proc}_{cr.fmt_temp(t)}c_{supply:.2f}v.log"
            if not f.is_file():
                continue
            m = re.search(r"graded: ptat=([-0-9.e+]+); ctat=([-0-9.e+]+)", f.read_text())
            if not m or "status=pass" not in f.read_text().splitlines()[0]:
                rows.append({"corner": f.stem, "note": "transient point not on physical branch / unparsable; skipped"})
                continue
            g = tagT(t)
            dp, dc = v[f"ptat_{g}"] - float(m.group(1)), v[f"ctat_{g}"] - float(m.group(2))
            rows.append({"corner": f.stem, "d_ptat_V": dp, "d_ctat_V": dc})
            for k, d in (("d_ptat", dp), ("d_ctat", dc)):
                if abs(d) >= abs(worst[k][0]):
                    worst[k] = (d, f.stem)
    cmp_rows = [r for r in rows if "d_ptat_V" in r]
    return {"source": SOLVER_RECORD, "n_compared": len(cmp_rows), "n_skipped": len(rows) - len(cmp_rows),
            "worst_d_ptat_V": worst["d_ptat"], "worst_d_ctat_V": worst["d_ctat"]}


def write_samples_csv(path, term, ent, an):
    cols = [f"{f}_{tagT(t)}" for t in TEMPS for f in FIELDS]
    lines = ["term,process,supply_V,sample,valid,reason," + ",".join(cols)]
    for (proc, supply), samples in sorted(ent["corners"].items()):
        bad = {i["sample"]: "; ".join(i["reasons"]) for i in an[(proc, supply)]["invalid"]}
        for smp, v in sorted(samples.items(), key=lambda kv: (-1 if kv[0] is None else kv[0])):
            ok = smp not in bad
            vals = ",".join("" if v.get(c) is None else f"{v[c]:.7g}" for c in cols)
            lines.append(f"{term},{proc},{supply:.2f},{'' if smp is None else smp},{int(ok)},{bad.get(smp, '').replace(',', ';')},{vals}")
    path.write_text("\n".join(lines) + "\n")


def f3(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def cmd_record(args):
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    last = meta.get("resumes", [None])[-1] or meta
    git = last["git"]
    klt_client = last.get("klt_client", meta["klt_client"])
    now = datetime.now(timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{git['sha']}"
    rec_dir = SIM_DIR / SLUG
    if (rec_dir / "records" / f"{rid}.md").exists():
        sys.exit(f"refusing to overwrite record {rid}")
    if git["dirty"] and not args.allow_dirty:
        sys.exit("the run was made from a DIRTY tree: this record would not be provenance-clean (re-run from a clean commit)")
    grade_git = cr.git_state()  # the analysis code that graded the run (may be later than the run SHA on a re-grade)
    if grade_git.get("dirty") and not args.allow_dirty:
        sys.exit("the grading tree is DIRTY: commit the analysis code first so the record is provenance-clean")
    ents ={t: load_term(run_dir, t) for t in ["nominal", *RUN_TERMS]}
    nominal = ents["nominal"]
    for d in ("records", "netlist-snapshots", "corners"):
        (rec_dir / d).mkdir(exist_ok=True)
    snap, cdir = rec_dir / "netlist-snapshots" / rid, rec_dir / "corners" / rid
    snap.mkdir()
    cdir.mkdir()
    anal, summ, summ_ctat, fleet = {}, {}, {}, {}
    summ_legacy, branch_suspects = {}, {}
    for t, ent in ents.items():
        if t == "nominal":
            subs = [(None, run_dir / t)]
        else:
            subs = [(pr, run_dir / t / pr) for pr in PROCS]
        for pr, d in subs:
            nl = d / "netlist.spice"
            if nl.is_file():
                tag = t if pr is None else f"{t}.{pr}"
                (snap / f"{tag}.spice").write_text(sim_common.scrub(nl.read_text(), run_dir, REPO_ROOT))
                (snap / f"{tag}.request.json").write_text(sim_common.scrub((d / "request.json").read_text(), run_dir, REPO_ROOT))
        if ent["report"] is None:
            continue
        env0 = ent["report"]["environment"]
        jobs = {k: {kk: v.get(kk) for kk in ("job_id", "instance_type", "lifecycle", "runner_klt_version", "client_klt_version", "elapsed_seconds", "state")}
                for k, v in ent["jobs"].items()}
        fleet[t] = {"jobs": jobs, "missing_procs": ent["missing_procs"],
                    "engine_version": env0.get("engine_version"),
                    "monte_carlo": {k: v for k, v in env0.get("monte_carlo", {}).items() if k != "family_mismatch"},
                    "family_mismatch": env0.get("monte_carlo", {}).get("family_mismatch")}
        if t == "nominal":
            continue
        anal[t] = analyse_term(ent, nominal) if nominal["report"] else None
        if anal[t] is not None:
            write_samples_csv(cdir / f"samples-{t}.csv", t, ent, anal[t])
            summ[t] = term_summary(anal[t], "ptat")
            summ_ctat[t] = term_summary(anal[t], "ctat")
            # with/without: the same data graded WITHOUT the branch-consistency guard (= the superseded guard set)
            legacy = analyse_term(ent, nominal, branch_guard=False)
            summ_legacy[t] = term_summary(legacy, "ptat")
            sus = []
            for key, cs in sorted(anal[t].items()):
                old_bad = {i["sample"] for i in legacy[key]["invalid"]}
                nom = nominal["corners"][key][None]
                for i in cs["invalid"]:
                    if i["sample"] in old_bad:
                        continue
                    v = ent["corners"][key][i["sample"]]
                    sus.append({"corner": f"{key[0]}_{key[1]:.2f}V", "sample": i["sample"],
                                "na_minus_nb_mV": {T: 1e3 * (v[f"na_{tagT(T)}"] - v[f"nb_{tagT(T)}"]) for T in TEMPS},
                                "ptat_minus_nominal_mV": {T: 1e3 * (v[f"ptat_{tagT(T)}"] - nom[f"ptat_{tagT(T)}"]) for T in TEMPS},
                                "offtrend_degC": offtrend_degC(v, nom)})
            branch_suspects[t] = sus
    # nominal per-corner logs
    if nominal["report"]:
        for c in nominal["report"]["corners"]:
            proc, supply, _ = parse_cid(c["corner_id"])
            vals = {m["name"]: m.get("value") for m in c["measurements"]}
            why = guard_check(vals) if all(v is not None for v in vals.values()) else ["unextractable measurement"]
            (cdir / f"nominal_{proc}_{supply:.2f}v.log").write_text(
                f"corner {c['corner_id']}  term nominal  klt status={c.get('status')}  guards={'ok' if not why else why}\n"
                + "\n".join(f"{k} = {v}" for k, v in vals.items()) + "\n")
    not_run = [t for t in RUN_TERMS if ents[t]["report"] is None] + (["nominal"] if nominal["report"] is None else [])
    partial = {t: ents[t]["missing_procs"] for t in RUN_TERMS if ents[t]["report"] is not None and ents[t]["missing_procs"]}
    xcheck = transient_crosscheck(nominal) if nominal["report"] else None
    # --- negative control + liveness
    ctrl = {}
    if "none" in anal and anal["none"]:
        ctrl["none_max_dev_from_nominal_V"] = max((cs["max_dev_from_nominal_V"] or 0.0) for cs in anal["none"].values())
        ctrl["none_max_sd_V"] = 0.0
    live = {t: (summ[t]["untrimmed"]["pooled_worst"] if t in summ and summ[t]["untrimmed"] else None) for t in TERMS if t in summ}
    rss = None
    if all(t in summ and summ[t]["untrimmed"] for t in TERMS) and "all" in summ and summ["all"]["untrimmed"]:
        rss = {}
        for mode in ("untrimmed", "trim1"):
            rss[mode] = {"worst_corner_RSS_of_terms": math.sqrt(sum(summ[t][mode]["worst_corner"]["k3sd"] ** 2 for t in TERMS)),
                         "pooled_RSS_of_terms": math.sqrt(sum(summ[t][mode]["pooled_worst"] ** 2 for t in TERMS)),
                         "all_worst_corner": summ["all"][mode]["worst_corner"]["k3sd"], "all_pooled": summ["all"][mode]["pooled_worst"]}
    rec = {"record_id": rid, "experiment": SLUG, "issue": 105, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "git": git, "klt": klt_client, "backend": meta["klt_sim_backend_env"], "run_id": args.run_id,
           "n_per_corner": meta["n"], "seed": meta["seed"], "guards": GUARDS, "groups": GROUPS, "fleet": fleet,
           "not_run_terms": not_run, "partial_terms_missing_process_sections": partial, "summary_ptat": summ, "summary_ctat": summ_ctat, "rss_check": rss, "controls": ctrl,
           "transient_crosscheck": xcheck, "resumes": meta.get("resumes", []), "graded_at_git": grade_git,
           "summary_ptat_without_branch_guard": summ_legacy, "branch_guard_suspects": branch_suspects,
           "offtrend_scan_threshold_degC": OFFTREND_SCAN_DEGC,
           "per_corner": {t: {f"{k[0]}_{k[1]:.2f}V": {"n_total": v["n_total"], "n_valid": v["n_valid"], "n_invalid": len(v["invalid"]),
                                                       "invalid": v["invalid"][:50], "nominal_invalid": v["nominal_invalid"],
                                                       "offtrend_over_threshold": v["offtrend"], "max_abs_offtrend_degC": v["max_abs_offtrend_degC"],
                                                       "stats": {f"{a}|{b}|{c}": s for (a, b, c), s in v["stats"].items()}}
                              for k, v in a.items()} for t, a in anal.items() if a},
           "supersedes": args.supersedes or "(none)", "author": cr.default_author()}
    (rec_dir / "records" / f"{rid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    (rec_dir / "records" / f"{rid}.md").write_text(render_md(rec, anal, summ, summ_ctat, rss, ctrl, xcheck, not_run, fleet, meta, args) + "\n")
    print(rid)
    return 0


def render_md(rec, anal, summ, summ_ctat, rss, ctrl, xcheck, not_run, fleet, meta, args):
    rid, git = rec["record_id"], rec["git"]
    N = meta["n"]
    L = [f"# Record {rid}", "",
         f"- **Record ID**: {rid}",
         f"- **Experiment**: `{SLUG}` -- full-signal-path mismatch Monte Carlo of `temp_core`: temperature error in degC, per-term attribution (issue #105; DR-003 row 2 `[TBD-1]`)",
         "- **Claim**: NOT a spec claim and no `spec/` edit. Evidence toward `[TBD-1]`: the PTAT-referred temperature error of `temp_core` under local device mismatch, untrimmed and with a 1-point (27 C) gain trim, with the contribution of each mismatch term separated.",
         f"- **Netlist provenance**: schematic-derived committed `design/netlist/{{bias_core,temp_core}}.spice` in a generated testbench (`netlist-snapshots/{rid}/`); per-term device switching by `mmoff_*` wrapper subckts (see README)",
         "- **PDK**: sky130A @ open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (sim/pdk.json pin), models `libs.tech/combined/sky130.lib.spice` (`_mm` sections for mismatch)",
         f"- **Tools**: {rec['klt']} (client); backend `{rec['backend']}`; fleet engine ngspice-{next((f['engine_version'] for f in fleet.values() if f.get('engine_version')), '?')}; fleet jobs: "
         + ", ".join(f"{t}[{k}]={j['job_id']}" for t, f in fleet.items() for k, j in f["jobs"].items()),
         f"- **Repo state**: `{git['sha']}` on `{git['branch']}` (working tree {'DIRTY' if git['dirty'] else 'clean'} at run time)"
         + "".join(f"; resumed {r['started_utc']} at `{r['git']['sha']}` ({'DIRTY' if r['git']['dirty'] else 'clean'})" for r in meta.get("resumes", []))
         + f"; graded (analysis code) at `{rec['graded_at_git']['sha']}` (working tree {'DIRTY' if rec['graded_at_git']['dirty'] else 'clean'})",
         f"- **PVT + MC settings**: process tt/ss/ff/sf/fs (`<p>_mm` sections) x supply 2.97/3.30/3.63 V = 15 corners; temperature swept -40..125 C (step 1) inside each ngspice process, evaluated at -40/27/125 C; Monte Carlo `vary: mismatch`, **N = {N} samples per corner per term**, base seed {meta['seed']} (all terms share it)",
         "- **Statistical convention**: **3 sigma = 3 x the sample standard deviation (n-1) of the temperature error over the valid Monte Carlo samples of one PVT corner**, i.e. a +/-3 sigma half-width about the sample mean; mean and empirical max |error| are tabulated alongside. Global process MC (`MC_PR_SWITCH`) is NOT sampled: the process axis is the five corner sections, mismatch is local only.",
         "- **Error definition**: `err(T) = (PTAT_sample(T) - PTAT_nominal(T)) / S` where nominal is the same-corner no-mismatch run and `S = (PTAT_nom(125 C) - PTAT_nom(-40 C))/165 C` (degC from volts via the nominal full-range slope). *Untrimmed* = as-is. *1-point trim* = ideal multiplicative gain trim so PTAT(27 C) equals nominal at 27 C, error evaluated at -40 and 125 C (27 C is zero by construction; trim resolution/quantization not modelled).",
         f"- **Operating-point trust**: DC sweep (not a cold-start transient). Operating-point trust is taken from the #86 solver-sweep record `{SOLVER_RECORD}` and its limits are inherited (six historical FAILs not reproduced on the current netlist, but some variant combos NOT-RUN; the original FAIL records remain). Physical guards applied to EVERY sample at all three temperatures: " + "; ".join(f"{k} in [{lo:g},{hi:g}]" for k, (lo, hi) in GUARDS.items() if k != BRANCH_GUARD) + "; PTAT strictly increasing over -40/27/125 C; **branch consistency** `" + BRANCH_GUARD + f"` = max over T of |d(T) - median_T d|, d = V(NA)-V(NB), in [{GUARDS[BRANCH_GUARD][0]:g},{GUARDS[BRANCH_GUARD][1]:g}] V (one device realisation keeps its amplifier offset across temperature; a DC solution on another branch at one temperature breaks loop closure there only). A sample failing any guard is INVALID: excluded from the statistics, never trimmed or substituted, and counted below.", ""]
    if rec["supersedes"] != "(none)":
        L += [f"**Supersedes `{rec['supersedes']}`** (that record is left untouched; records are append-only). This is a **re-grade of the same fleet outputs** "
              f"(run id `{rec['run_id']}`, the same {sum(len(f['jobs']) for f in fleet.values())} fleet job ids listed above); **no new simulation was run**. "
              "The only change is the analysis: the branch-consistency guard above was added because the superseded record's guards (absolute windows plus "
              "PTAT monotonicity over three points) could not see a single-temperature jump to another DC solution, and one such sample set its 1-point-trim "
              "headline. The headline is reported below with and without the newly excluded samples.", ""]
    if not_run:
        L += [f"**PARTIAL: terms NOT-RUN (fleet refusal/timeout): {', '.join(not_run)}.** Nothing was substituted by a local grid.", ""]
    if rec.get("partial_terms_missing_process_sections"):
        L += ["**PARTIAL process coverage (those process-section requests had no usable fleet result; statistics cover the remaining sections only): "
              + "; ".join(f"{t}: missing {', '.join(m)}" for t, m in rec["partial_terms_missing_process_sections"].items()) + ".**", ""]
    # headline
    L += ["## Headline (PTAT-referred temperature error, 3 sigma, degC)", ""]
    if "all" in summ and summ["all"]["untrimmed"]:
        a = summ["all"]
        L += ["| | worst corner (of 15) | tt / 3.30 V | RMS-pooled over the 15 corners |", "|---|---|---|---|"]
        for mode, name in (("untrimmed", "untrimmed (worst of -40/27/125 C)"), ("trim1", "1-point 27 C trim (worst of -40/125 C)")):
            m = a[mode]
            tt = m["tt_3p30"]
            L.append(f"| all terms, {name} | **{f3(m['worst_corner']['k3sd'], 2)}** (`{m['worst_corner']['corner']}`, at {m['worst_corner']['at_T']} C) | "
                     f"{f3(tt['k3sd'], 2) if tt else 'n/a'} | {f3(m['pooled_worst'], 2)} |")
        L += ["", "DR-003 row-2 targets for reference: untrimmed +/-3 C, 1-point trim +/-1.5 C (a comparison of figures only; this record ratifies nothing).", ""]
        leg = rec["summary_ptat_without_branch_guard"]
        L += ["### Headline with and without the branch-consistency guard (same data)", "",
              "| term | mode | WITH suspected branch jumps (superseded guard set): worst corner / tt 3.30 / pooled | branch-jump samples EXCLUDED (this record): worst corner / tt 3.30 / pooled | valid / total (with -> excluded) |",
              "|---|---|---|---|---|"]

        def trio(m):
            return (f"{f3(m['worst_corner']['k3sd'], 2)} (`{m['worst_corner']['corner']}`, {m['worst_corner']['at_T']} C) / "
                    f"{f3(m['tt_3p30']['k3sd'], 2) if m['tt_3p30'] else 'n/a'} / {f3(m['pooled_worst'], 2)}")
        for t in [*TERMS, "all"]:
            if t not in summ or not summ[t]["untrimmed"] or t not in leg or not leg[t]["untrimmed"]:
                continue
            for mode in ("untrimmed", "trim1"):
                o, n_ = leg[t][mode], summ[t][mode]
                L.append(f"| {t} | {mode} | {trio(o)} | {trio(n_)} | {o['n_valid']} -> {n_['n_valid']} / {n_['n_total']} |")
        L += ["", "Only the rows whose figures move are affected by the excluded samples; see \"Branch-consistency scan\" below for the samples themselves.", ""]
    else:
        L += ["The `all`-terms aggregate is NOT AVAILABLE (term not run / no valid samples); no aggregate figure is claimed.", ""]
    # attribution
    L += ["## Per-term attribution (PTAT, 3 sigma, degC; each row has ONLY that term's mismatch live)", "",
          "| term | devices | untrimmed worst corner | untrimmed tt/3.30 | untrimmed pooled | 1-pt trim worst corner | 1-pt trim tt/3.30 | 1-pt trim pooled | valid / total |", "|---|---|---|---|---|---|---|---|---|"]
    devs = {**{k: ", ".join(v).replace("X", "") for k, v in GROUPS.items()}, "other": "all `bias_core` devices + remaining `temp_core` devices (bias mirror/tail, 2nd stage, startup, enable, CC, RZ, RISO)", "all": "everything live"}
    for t in [*TERMS, "all"]:
        if t not in summ or not summ[t]["untrimmed"]:
            L.append(f"| {t} | {devs[t]} | NOT AVAILABLE | | | | | | |")
            continue
        u, tr = summ[t]["untrimmed"], summ[t]["trim1"]
        tt_u = f3(u['tt_3p30']['k3sd'], 2) if u['tt_3p30'] else 'n/a'
        tt_t = f3(tr['tt_3p30']['k3sd'], 2) if tr['tt_3p30'] else 'n/a'
        L.append(f"| **{t}** | {devs[t]} | {f3(u['worst_corner']['k3sd'], 2)} (`{u['worst_corner']['corner']}`) | {tt_u} | {f3(u['pooled_worst'], 2)} | "
                 f"{f3(tr['worst_corner']['k3sd'], 2)} (`{tr['worst_corner']['corner']}`) | {tt_t} | {f3(tr['pooled_worst'], 2)} | {u['n_valid']} / {u['n_total']} |")
    if rss:
        L += ["", "Consistency of the attribution (terms are independent draws, so their variances should add):", "",
              "| | RSS of the five term rows | `all` row |", "|---|---|---|"]
        for mode, nm in (("untrimmed", "untrimmed"), ("trim1", "1-pt trim")):
            r = rss[mode]
            L.append(f"| {nm}, worst corner | {r['worst_corner_RSS_of_terms']:.2f} | {r['all_worst_corner']:.2f} |")
            L.append(f"| {nm}, pooled | {r['pooled_RSS_of_terms']:.2f} | {r['all_pooled']:.2f} |")
        L.append("")
        L.append("(The worst-corner RSS sums each term's own worst corner, so it can exceed the `all` row when the terms peak at different corners; the pooled rows are the like-for-like check.)")
    # per-T detail for tt 3.30
    L += ["", "## Error statistics per temperature at tt / 3.30 V (PTAT, degC)", "",
          "| term | mode | T (C) | n valid | mean | sigma | 3 sigma | max abs |", "|---|---|---|---|---|---|---|---|"]
    for t in [*TERMS, "all"]:
        cs = anal.get(t, {}) and anal[t].get(("tt", 3.3))
        if not cs:
            continue
        for mode in ("untrimmed", "trim1"):
            for T in (TEMPS if mode == "untrimmed" else [T_LO, T_HI]):
                s = cs["stats"].get(("ptat", mode, T))
                if s:
                    L.append(f"| {t} | {mode} | {T} | {s['n']} | {s['mean']:.3f} | {s['sd']:.3f} | {s['k3sd']:.3f} | {s['max_abs']:.3f} |")
    # full corner table for all
    if "all" in anal and anal["all"]:
        L += ["", "## `all`-terms 3 sigma at every PVT corner (PTAT, degC)", "", "| process | supply (V) | n valid / total | untrimmed 3 sigma (worst T) | 1-pt trim 3 sigma (worst T) |", "|---|---|---|---|---|"]
        for (p, v), cs in sorted(anal["all"].items()):
            u, tr = worst_over_T(cs, "ptat", "untrimmed"), worst_over_T(cs, "ptat", "trim1")
            L.append(f"| {p} | {v:.2f} | {cs['n_valid']} / {cs['n_total']} | {f3(u[0], 2)} (at {u[1]} C) | {f3(tr[0], 2)} (at {tr[1]} C) |")
    # CTAT
    if "all" in summ_ctat and summ_ctat["all"] and summ_ctat["all"]["untrimmed"]:
        c = summ_ctat["all"]
        L += ["", "## CTAT (secondary output; same convention, slope from nominal CTAT; 1-pt trim = additive offset trim at 27 C), `all` terms, 3 sigma degC", "",
              "| mode | worst corner | tt / 3.30 V | pooled |", "|---|---|---|---|"]
        for mode in ("untrimmed", "trim1"):
            m = c[mode]
            L.append(f"| {mode} | {f3(m['worst_corner']['k3sd'], 2)} (`{m['worst_corner']['corner']}`) | {f3(m['tt_3p30']['k3sd'], 2) if m['tt_3p30'] else 'n/a'} | {f3(m['pooled_worst'], 2)} |")
    # branch-consistency scan
    sus = rec["branch_guard_suspects"]
    n_sus = sum(len(v) for v in sus.values())
    L += ["", "## Branch-consistency scan (suspected DC branch jumps; excluded)", "",
          f"Every sample of every term and all 15 corners was scanned for the branch-jump signature. Samples that passed every guard of the superseded record but fail the branch-consistency guard: **{n_sus}** in total ("
          + ", ".join(f"{t}: {len(sus.get(t, []))}" for t in RUN_TERMS if t in sus) + "). They are excluded from every statistic in this record and listed here:", ""]
    if n_sus:
        L += ["| term | corner | sample | V(NA)-V(NB) mV at -40 / 27 / 125 C | PTAT - nominal mV at -40 / 27 / 125 C | 27 C off-chord (degC) |", "|---|---|---|---|---|---|"]
        for t in RUN_TERMS:
            for s in sus.get(t, []):
                d, p = s["na_minus_nb_mV"], s["ptat_minus_nominal_mV"]
                L.append(f"| {t} | {s['corner']} | {s['sample']} | {' / '.join(f'{d[T]:.2f}' for T in TEMPS)} | {' / '.join(f'{p[T]:.1f}' for T in TEMPS)} | {s['offtrend_degC']:.2f} |")
        L.append("")
    off = [(t, f"{k[0]}_{k[1]:.2f}V", smp, x) for t in RUN_TERMS if t in anal and anal[t] for k, cs in sorted(anal[t].items()) for smp, x in cs["offtrend"]]
    mx = max((cs["max_abs_offtrend_degC"] or 0.0) for t in RUN_TERMS if t in anal and anal[t] for cs in anal[t].values())
    L += [f"Secondary off-trend scan (disclosure only, not a guard; three evaluation temperatures are all the sample CSVs hold, the dense sweep is not kept): deviation of the 27 C PTAT error from the chord through the -40 C and 125 C errors, over every sample that passes all guards in this record. "
          f"Largest |deviation| = {mx:.2f} degC; samples above {OFFTREND_SCAN_DEGC:g} degC: "
          + (", ".join(f"{t} {c} #{s} ({x:.2f})" for t, c, s, x in off) if off else "**none**") + ".", ""]
    # validity
    L += ["## Operating-point guards: invalid samples (disclosed, excluded)", "", "| term | invalid / total | corners affected |", "|---|---|---|"]
    for t in [*RUN_TERMS]:
        if t not in anal or not anal[t]:
            L.append(f"| {t} | NOT-RUN | |")
            continue
        inv = sum(len(cs["invalid"]) for cs in anal[t].values())
        tot = sum(cs["n_total"] for cs in anal[t].values())
        aff = ", ".join(f"{p}_{v:.2f}V ({len(cs['invalid'])})" for (p, v), cs in sorted(anal[t].items()) if cs["invalid"]) or "none"
        L.append(f"| {t} | {inv} / {tot} | {aff} |")
    bad_nom = [f"{p}_{v:.2f}V" for t_ in [*RUN_TERMS] if t_ in anal and anal[t_] for (p, v), cs in anal[t_].items() if cs["nominal_invalid"]]
    L += ["", "Reasons per invalid sample are in the json twin (`per_corner.<term>.<corner>.invalid`, first 50 per corner) and in the `valid`/`reason` columns of `corners/" + rid + "/samples-<term>.csv`.",
          "Corners whose NOMINAL reference failed a guard (all their samples are excluded): " + (", ".join(sorted(set(bad_nom))) or "none") + ".", ""]
    # controls
    L += ["## Controls and cross-checks", ""]
    if ctrl:
        L.append(f"- Negative control (`none`: `_mm` section + Monte Carlo, every device wrapped to sigma = 0): max |PTAT(sample) - PTAT(nominal)| over all samples, corners and temperatures = {ctrl['none_max_dev_from_nominal_V']:.3g} V "
                 + ("(PASS: exactly the no-mismatch curve; the switching wrappers zero every mismatch source, and nothing else varies)" if ctrl['none_max_dev_from_nominal_V'] < 1e-9 else "(**FAIL**: the control is not flat; the per-term attribution cannot be trusted)"))
    else:
        L.append("- Negative control (`none`) NOT AVAILABLE.")
    for t in TERMS:
        if t in summ and summ[t]["untrimmed"]:
            L.append(f"- Liveness `{t}`: pooled untrimmed 3 sigma = {summ[t]['untrimmed']['pooled_worst']:.3g} degC " + ("(nonzero: that term's mismatch is live)" if summ[t]['untrimmed']['pooled_worst'] > 0 else "(**ZERO: term inert**)"))
    fm = next((f["family_mismatch"] for f in fleet.values() if f.get("family_mismatch")), None)
    if fm:
        L.append("- klt per-family mismatch report: " + "; ".join(f"{x['family']}: active={x['active']}" for x in fm) + ". Families reported `null` (resistor, capacitor) are not curated by klt; the resistor term is confirmed live by the `res` liveness row above rather than by that report.")
    if xcheck:
        L.append(f"- Operating-point cross-check vs the #86 EN-high `base` transient (`{xcheck['source']}`): nominal DC sweep vs transient final value at the same {xcheck['n_compared']} PVT points ({xcheck['n_skipped']} skipped as not on the physical branch in the transient): worst |dPTAT| = {abs(xcheck['worst_d_ptat_V'][0]):.3g} V at `{xcheck['worst_d_ptat_V'][1]}`, worst |dCTAT| = {abs(xcheck['worst_d_ctat_V'][0]):.3g} V at `{xcheck['worst_d_ctat_V'][1]}`.")
    L += ["- Attribution is by switching, not by a model of the error: the PNP row uses `XQ1`+`XQ8A..H` (both `is` and `bf` mismatch), the amp row the input pair `MI1/MI2` and mirror load `ML1/ML2` (Vth mismatch), the res row `R1`, `R2`, `R2TRIM`, the mirror row `MP1..3` and cascodes `MPC1..3`, `other` everything else. Interaction terms are inside the `all` row only.",
          f"- Cross-reference (not duplicated): PNP-pair-only sigma from the earlier mismatch campaign `{PNP_RECORD}` (DVBE sigma 0.065-0.180 mV); the `pnp` row above is the same physics propagated to degC.", ""]
    # unmeasured
    L += ["## Not measured / limits of this record", "",
          "- **Global process Monte Carlo** (`MC_PR_SWITCH`, e.g. absolute resistor/PNP spread): not sampled; the five process corners are deterministic points. Absolute-value spread is outside the error definition used here (error is relative to the same corner's nominal), but a PTAT-gain error from global process would be removed by the 27 C trim and is untrimmed-only.",
          "- **Systematic / gradient / layout-dependent mismatch, stress, aging, self-heating**: only the PDK's local (Pelgrom-style) mismatch is modelled.",
          "- **Dynamic behaviour**: DC solutions only; cold-start and supply-ramp behaviour is #86's and the startup campaigns' business, not re-measured here. This campaign shares #86's inherited limits.",
          "- **Trim**: the 1-point trim is an ideal continuous gain correction; the physical strap-ladder resolution and its own mismatch are not modelled.",
          "- **Readout chain**: error is referred through the nominal PTAT slope; no ADC/buffer/pad load. Supply sensitivity beyond the three supply points is not swept.",
          ("- **NOT-RUN terms**: " + ", ".join(not_run) + " -- unmeasured; the `all` row still includes their physics but their individual share is unknown."
           if not_run else "- **Statistical resolution**: N = " + str(N) + " samples per corner gives a coarse sigma estimate (chi-square 95 % interval on a per-corner sigma at n = 30: about -20 % / +34 %); every term, the `none` control and the `nominal` reference ran on all 15 corners (none NOT-RUN)."),
          "- **Branch detection resolution**: the branch-consistency guard sees only the three evaluation temperatures stored per sample; a branch excursion confined strictly between -40, 27 and 125 C would not be seen (the dense -40..125 C sweep is evaluated by `.meas` only at those points).", ""]
    L += ["## Links", "", f"- driver `sim/{SLUG}/run_accuracy_mc.py`; json twin `records/{rid}.json`; netlists and requests `netlist-snapshots/{rid}/`; raw per-sample values `corners/{rid}/samples-<term>.csv`; nominal points `corners/{rid}/nominal_*.log`",
          f"- **Timestamp**: {rec['timestamp']}", f"- **Author**: {rec['author']}", f"- **Supersedes**: {rec['supersedes']}"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--run-id")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--term", action="append", choices=["nominal", *RUN_TERMS])
    r.add_argument("--n", type=int, default=DEFAULT_N)
    r.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r.add_argument("--jobs", type=int, default=2)
    r.add_argument("--allow-dirty", action="store_true")
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("probe")
    p.add_argument("--run-id", required=True)
    p.add_argument("--term", action="append", required=True, choices=["nominal", *RUN_TERMS])
    p.add_argument("--process", default="tt")
    p.add_argument("--supply", type=float, default=3.3)
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.set_defaults(fn=cmd_probe)
    rc = sub.add_parser("record")
    rc.add_argument("--run-id", required=True)
    rc.add_argument("--supersedes", default=None, help="record id this record replaces (append-only: the old record is untouched)")
    rc.add_argument("--allow-dirty", action="store_true")
    rc.set_defaults(fn=cmd_record)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
