#!/usr/bin/env python3
"""Full-signal-path mismatch Monte Carlo of temp_core -- PTAT temperature error with per-term attribution (issue #105).

Question (DR-003 row 2, [TBD-1]): what is the temperature error, in degrees C, of the PTAT readout of
`temp_core` under 3-sigma device mismatch, untrimmed and with a 1-point (27 C) gain trim, and how much of
it does each mismatch term (PNP pair, amplifier offset, resistor ratio, mirror ratio) contribute?

Execution rule (host + issue): every Monte Carlo sample set is a ``klt sim`` request with ``monte_carlo``
submitted with an explicit ``--backend batch`` (Spot fleet).  This script never launches ngspice over a grid
itself and NEVER falls back to a local grid when the fleet refuses -- a refusal is recorded as NOT-RUN.
``probe`` runs ONE local single-corner point at a time (debug only).

Pairing across temperature: klt derives the per-sample seed from (base seed, corner_index, sample_index).
Putting the three temperatures into one request would give each temperature an independent draw, which
makes the 1-point trim (needs the SAME device sample at 27 C and at T) meaningless.  So there is ONE request
per (variant, process, supply, temperature), each with corner_index 0, hence identical per-sample seeds and
identical draws across temperature.  This is validated, not assumed: the record reports the cross-temperature
correlation of the per-sample PTAT deviation (about 1 if paired, about 0 if not).

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
TEMPLATE = HERE / "testbench" / "tb_temp_core_accuracy.spice"
MODEL_LIB = "libs.tech/combined/sky130.lib.spice"
MODELS_GLOBAL = "libs.tech/combined/continuous/models_global.spice"
say = sim_common.say

TEMPS = [-40, 27, 125]
TRIM_T = 27
SUPPLIES = [2.97, 3.3, 3.63]
PROCS = ["tt", "ss", "ff", "sf", "fs"]
TSTOP = 10e-3
STEP = 10e-6
TRAMP = 100e-6
OPTIONS = "method=gear trtol=7"  # the best-behaved #86 variant (44/45); starts are still guarded, never trusted
N_SAMPLES = 100
N_CONTROL = 10
N_EXTEND = 50  # all-native samples at the extra process/supply corners
SEED = 20261011
SIGMA_K = 3  # the 3-sigma convention (spec/porting-plan.md section 3.2); stated in experiment.json
TARGET_UNTRIMMED_C = 3.0  # DR-003 row 2 README numbers (NOT ratified; recorded for the ratio only)
TARGET_TRIMMED_C = 1.5

# Pelgrom-style threshold coefficients of the installed PDK (checked against models_global.spice at run time)
AVT = {"nfet": 8.2e-3, "pfet": 1.2e-2}
AVT_PARAM = {"nfet": "sw_mm_vth0_sky130_fd_pr__nfet_g5v0d10v5", "pfet": "sw_mm_vth0_sky130_fd_pr__pfet_g5v0d10v5"}

# explicit-injection devices: name -> (gate node in committed temp_core, kind, W, L, role)
INJECT = {
    "MI1": ("NA", "pfet", 32, 4, "amp"),
    "MI2": ("NB", "pfet", 32, 4, "amp"),
    "ML1": ("N1", "nfet", 8, 8, "amp"),
    "ML2": ("N1", "nfet", 8, 8, "amp"),
    "MP1": ("PG", "pfet", 8, 4, "mir"),
    "MP2": ("PG", "pfet", 8, 4, "mir"),
    "MP3": ("PG", "pfet", 8, 4, "mir"),
    "MPC1": ("PCAS", "pfet", 8, 1, "mir"),
    "MPC2": ("PCAS", "pfet", 8, 1, "mir"),
    "MPC3": ("PCAS", "pfet", 8, 1, "mir"),
}

ZERO = {  # native coefficient overrides that switch a family off
    "pnp": ["sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_is", "sw_mm_sky130_fd_pr__pnp_05v5_W0p68L0p68_bf"],
    "res": ["sw_mm_sky130_fd_pr__res_xhigh_po"],
    "mos": ["sw_mm_vth0_sky130_fd_pr__nfet_g5v0d10v5", "sw_mm_vth0_sky130_fd_pr__pfet_g5v0d10v5"],
    "cap": ["sw_mm_cmim"],
}

# variant -> (lib section suffix, native families kept ON, explicit roles ON, description)
VARIANTS = {
    "nominal": ("", set(), set(), "no mismatch; the per-corner reference transfer function"),
    "control-off": ("", set(), set(), "MC sampler on, every mismatch term off: sigma must be exactly 0 (negative control)"),
    "control-zeroed": ("_mm", set(), set(), "`_mm` lib section with every native coefficient overridden to 0: proves the override beats the lib (sigma must be 0)"),
    "pnp": ("_mm", {"pnp"}, set(), "PNP ratio-pair (Q1 vs Q8A..H) native Is/Bf mismatch only"),
    "res": ("_mm", {"res"}, set(), "xhigh_po resistor native mismatch only (R1/R2/R2TRIM; sets the R2/R1 ratio)"),
    "amp": ("", set(), {"amp"}, "amplifier input-referred offset only (explicit Vth injection on MI1/MI2/ML1/ML2)"),
    "mirror": ("", set(), {"mir"}, "PMOS gain-mirror ratio only (explicit Vth injection on MP1-3 and cascodes MPC1-3)"),
    "combined": ("_mm", {"pnp", "res"}, {"amp", "mir"}, "the four listed terms together (native PNP+RES, explicit AMP+MIRROR); excludes bias_core and tail/startup MOS"),
    "all": ("_mm", {"pnp", "res", "mos", "cap"}, set(), "everything the PDK mismatches, native (adds bias_core, tail/startup/enable MOS, MIM cap)"),
}
MC_VARIANTS = [v for v in VARIANTS if v != "nominal"]

# (variant, process list, supply list) groups.  Attribution at tt/3.30 V; the all-native aggregate also at
# the other process corners and the supply extremes.
ATTRIBUTION = ["pnp", "res", "amp", "mirror", "combined", "all"]
PLAN_MC = (
    [(v, "tt", 3.30) for v in ATTRIBUTION]
    + [("all", p, 3.30) for p in ("ss", "ff", "sf", "fs")]
    + [("all", "tt", 2.97), ("all", "tt", 3.63)]
    + [("control-off", "tt", 3.30), ("control-zeroed", "tt", 3.30)]
)

MEAS = ["ptat", "ptat_b", "ctat", "ctat_b", "na", "nb", "isup", "bias_ok"] + [f"dv_{d.lower()}" for d in INJECT]
WINDOWS = {  # copied from sim/temp-core-startup/experiment.json (not relaxed)
    "ptat": (0.3, 2.6), "ctat": (0.2, 1.1), "na": (-1.0, 4.7), "nb": (-1.0, 4.7),
    "isup": (1e-8, 5e-5), "bias_ok": (2.0, 3.7),
}
SETTLE_MAX = 1e-3  # |x(tstop) - x(tstop-1ms)| (V), same as the startup experiments


def subckt_text(name):
    txt = (REPO_ROOT / "design" / "netlist" / f"{name}.spice").read_text()
    return "\n".join(ln for ln in txt.splitlines() if ln.strip().lower() != ".end") + "\n"


def inject_temp_core(text):
    """Return the committed temp_core text with one series gate source per INJECT device.

    Only the gate token of the first line of each listed instance is rewritten; with every dv param = 0 the
    circuit is electrically the committed one (a 0 V source in each gate path).
    """
    out, added = [], []
    for ln in text.splitlines():
        tok = ln.split()
        if tok and tok[0].startswith("X") and tok[0][1:] in INJECT:
            dev = tok[0][1:]
            gate, kind, w, l, role = INJECT[dev]
            if tok[2] != gate:
                raise SystemExit(f"{dev}: committed gate node is {tok[2]}, expected {gate}; update INJECT")
            new = f"{gate}G_{dev}"
            tok[2] = new
            ln = " ".join(tok)
            added.append(f"VOS_{dev} {new} {gate} DC {{dv_{dev.lower()}}}")
            added.append(f"BOBS_{dev} OBS_{dev} VSS V = {{dv_{dev.lower()}}}")
        if ln.startswith(".ends"):
            out.extend(added)
            added = []
            out.append("* ---- series gate sources added by run_accuracy_mc.py (explicit Vth mismatch, see testbench header)")
        out.append(ln)
    return "\n".join(out) + "\n"


def check_avt(pdk_root):
    txt = (Path(pdk_root) / "sky130A" / MODELS_GLOBAL).read_text()
    for kind, pname in AVT_PARAM.items():
        m = re.search(rf"{pname}\s*=\s*([0-9.eE+-]+)", txt)
        if not m or abs(float(m.group(1)) - AVT[kind]) > 1e-12:
            raise SystemExit(f"installed PDK {pname} = {m and m.group(1)} != runner AVT[{kind}] = {AVT[kind]}; update the runner")


def build_netlist(variant):
    sect, native_on, roles_on, desc = VARIANTS[variant]
    params = [f".param tramp={TRAMP:.9g}", f".param tstop={TSTOP:.9g}",
              f".param sw_amp={1 if 'amp' in roles_on else 0}", f".param sw_mir={1 if 'mir' in roles_on else 0}"]
    zeroed = []
    if sect:
        for fam, plist in ZERO.items():
            if fam not in native_on:
                zeroed += plist
    for p in zeroed:
        params.append(f".param {p}=0")
    params.append("* explicit Vth mismatch: dv = sw * A_VT / sqrt(W*L) * AGAUSS(0,1,1)  (A_VT, W, L in the PDK's own units; same form as models_fet.spice)")
    for dev, (_g, kind, w, l, role) in INJECT.items():
        sw = "sw_amp" if role == "amp" else "sw_mir"
        params.append(f".param dv_{dev.lower()} = {{{sw}*{AVT[kind]:.6g}/sqrt({w}*{l})*agauss(0,1,1)}}")
    header = f"{SLUG} variant {variant}: {desc}  -- generated by sim/{SLUG}/run_accuracy_mc.py, do not edit"
    t = TEMPLATE.read_text()
    t = t.replace("@@HEADER@@", header).replace("@@PARAMS@@", "\n".join(params)).replace("@@OPTIONS@@", OPTIONS)
    t = t.replace("@@BIAS_CORE@@", subckt_text("bias_core")).replace("@@TEMP_CORE@@", inject_temp_core(subckt_text("temp_core")))
    return t


def corner_section(variant, proc):
    return proc + VARIANTS[variant][0]


def measurements():
    b = TSTOP - 1e-3
    ms = [
        ("ptat", f"v(ptat) AT={TSTOP:.6g}", "V"), ("ptat_b", f"v(ptat) AT={b:.6g}", "V"),
        ("ctat", f"v(ctat) AT={TSTOP:.6g}", "V"), ("ctat_b", f"v(ctat) AT={b:.6g}", "V"),
        ("na", f"v(xdut.na) AT={TSTOP:.6g}", "V"), ("nb", f"v(xdut.nb) AT={TSTOP:.6g}", "V"),
        ("isup", f"i(bvdd) AT={TSTOP:.6g}", "A"), ("bias_ok", f"v(bias_ok) AT={TSTOP:.6g}", "V"),
    ]
    out = [{"name": n, "spice": f".meas tran {n} FIND {e}", "unit": u} for n, e, u in ms]
    for dev in INJECT:
        out.append({"name": f"dv_{dev.lower()}", "spice": f".meas tran dv_{dev.lower()} FIND v(xdut.obs_{dev.lower()}) AT={TSTOP:.6g}", "unit": "V"})
    return out


def build_request(variant, procs, temps, supplies, backend, n=None, timeout=3000):
    req = {
        "netlist": "netlist.spice",
        "backend": backend,
        "models": {"pdk": "sky130A", "lib": MODEL_LIB},
        "corners": {"process": procs, "supply_v": {"vset": supplies}, "temperature_c": temps},
        "analysis": {"kind": "tran", "args": f"{STEP:.6g} {TSTOP:.6g} uic"},
        "measurements": measurements(),
        "options": {"timeout_s": timeout, "keep_artifacts": True, "waveforms": False},
    }
    if n:
        req["monte_carlo"] = {"n": n, "seed": SEED, "vary": "mismatch"}
    if backend == "batch":
        req["batch"] = {"runner_version_check": "warn"}
    return req


def group_n(v, p, s):
    if v.startswith("control"):
        return N_CONTROL
    return N_SAMPLES if (p, s) == ("tt", 3.30) else N_EXTEND


def units():
    """Every klt request of the campaign: (unit name, variant, procs, temps, supplies, n)."""
    u = [("nominal", "nominal", PROCS, TEMPS, SUPPLIES, None)]
    for v, p, s in PLAN_MC:
        n = group_n(v, p, s)
        for t in TEMPS:
            u.append((f"{v}__{p}_{s:.2f}v_{sim_common_t(t)}c", v, [corner_section(v, p)], [t], [s], n))
    return u


def sim_common_t(t):
    return cr.fmt_temp(t)


def klt_version():
    p = subprocess.run(["klt", "--version"], capture_output=True, text=True)
    return p.stdout.strip() or p.stderr.strip()


def cmd_run(args):
    pdk_root = os.environ.get("PDK_ROOT") or str(Path.home() / ".volare")
    check_avt(pdk_root)
    now = datetime.now(timezone.utc)
    git = cr.git_state()
    run_id = args.run_id or f"{now:%Y%m%d-%H%M%S}-{git['sha']}"
    run_dir = BUILD / run_id
    run_dir.mkdir(parents=True, exist_ok=args.resume)
    sel = [u for u in units() if (not args.only or any(re.search(o, u[0]) for o in args.only))]
    this = {"started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "klt_client": klt_version(),
            "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"), "git": git, "units": [u[0] for u in sel]}
    if args.resume and (run_dir / "run.json").is_file():
        meta = json.loads((run_dir / "run.json").read_text())
        meta.setdefault("resumes", []).append(this)
        cur = this
    else:
        meta = {"run_id": run_id, **this}
        cur = meta
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")

    def one(u):
        name, variant, procs, temps, sups, n = u
        d = run_dir / name
        if sim_common.report_usable(d / "report.json"):
            return {"unit": name, "skipped": "usable report exists"}
        d.mkdir(parents=True, exist_ok=True)
        (d / "netlist.spice").write_text(build_netlist(variant))
        (d / "request.json").write_text(json.dumps(build_request(variant, procs, temps, sups, "batch", n), indent=2) + "\n")
        npts = len(procs) * len(temps) * len(sups) * (n or 1)
        say(f"[submit] {name}: {npts} runs -> batch fleet")
        p = subprocess.run(["klt", "sim", str(d / "request.json"), "--backend", "batch", "-o", str(d / "out"), "--format", "json"],
                           capture_output=True, text=True, timeout=4 * 3600)
        (d / "report.json").write_text(p.stdout)
        (d / "klt.stderr").write_text(p.stderr)
        try:
            st = json.loads(p.stdout).get("status", "?")
        except json.JSONDecodeError:
            st = "NO-JSON"
        say(f"[done]   {name}: exit {p.returncode}, status {st}")
        return {"unit": name, "exit": p.returncode, "status": st}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, args.jobs)) as ex:
        for f in [ex.submit(one, u) for u in sel]:
            try:
                results.append(f.result())
            except Exception as err:  # noqa: BLE001 -- recorded, never retried locally
                results.append({"error": repr(err)})
                say(f"[error] {err!r}")
    cur["submit_results"] = results
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def cmd_probe(args):
    """ONE local single-corner, single-sample point (debug only; never a grid)."""
    variant, proc, temp, sup = args.variant, args.proc, float(args.temp), float(args.supply)
    d = BUILD / "probe" / f"{variant}__{proc}_{temp:g}c_{sup:.2f}v"
    d.mkdir(parents=True, exist_ok=True)
    (d / "netlist.spice").write_text(build_netlist(variant))
    req = build_request(variant, [corner_section(variant, proc)], [temp], [sup], "local", 1)
    (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
    say(f"[probe] local single point {d.name}")
    pr = subprocess.run(["klt", "sim", str(d / "request.json"), "--backend", "local", "-o", str(d / "out"), "--format", "json"],
                        capture_output=True, text=True, timeout=1800)
    (d / "report.json").write_text(pr.stdout)
    (d / "klt.stderr").write_text(pr.stderr)
    say(f"[probe] exit {pr.returncode}; {d}")
    return 0


# ----------------------------------------------------------------------------------------------- analysis

def mvals(c):
    m = {x["name"]: x.get("value") for x in c.get("measurements", [])}
    if m.get("isup") is not None:
        m["isup"] = -m["isup"]  # ngspice reports the source current into its + terminal; supply current is the negative
    return m


def guard(m):
    """Operating-point guard: None if the sample is a trustworthy physical-branch landing, else the reason."""
    if any(m.get(k) is None or not math.isfinite(m[k]) for k in MEAS[:8]):
        return "unextracted"
    for k, (lo, hi) in WINDOWS.items():
        if not lo <= m[k] <= hi:
            return f"{k} outside window"
    if abs(m["ptat"] - m["ptat_b"]) > SETTLE_MAX or abs(m["ctat"] - m["ctat_b"]) > SETTLE_MAX:
        return "not settled"
    return None


def load_unit(run_dir, name):
    rp = run_dir / name / "report.json"
    if not sim_common.report_usable(rp):
        try:
            err = json.loads((run_dir / name / "report.json").read_text()).get("error")
        except (OSError, json.JSONDecodeError):
            err = None
        if not err:
            try:
                err = json.loads((run_dir / name / "klt.stderr").read_text()).get("error")
            except (OSError, json.JSONDecodeError):
                err = {"message": "no report"}
        return {"report": None, "refusal": err}
    return {"report": json.loads(rp.read_text()), "refusal": None}


def slope_at(temps, p, i):
    """dP/dT at temps[i] from the quadratic through the three nominal points (Lagrange derivative)."""
    t0, t1, t2 = temps
    y = p
    x = temps[i]
    d0 = y[0] * (2 * x - t1 - t2) / ((t0 - t1) * (t0 - t2))
    d1 = y[1] * (2 * x - t0 - t2) / ((t1 - t0) * (t1 - t2))
    d2 = y[2] * (2 * x - t0 - t1) / ((t2 - t0) * (t2 - t1))
    return d0 + d1 + d2


def sd(x):
    return statistics.stdev(x) if len(x) > 1 else None


def pctl(x, q):
    s = sorted(x)
    if not s:
        return None
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def analyse(run_dir):
    """Everything the record states, computed from the retrieved fleet reports."""
    out = {"units": {}, "nominal": {}, "groups": {}, "controls": {}}
    # --- nominal reference
    nu = load_unit(run_dir, "nominal")
    nom, nom_inval = {}, {}
    if nu["report"]:
        for c in nu["report"]["corners"]:
            m = mvals(c)
            key = (c["process"], c["supply_v"]["vset"], c["temperature_c"])
            r = guard(m)
            if r:
                nom_inval[key] = {"reason": r, "ptat": m.get("ptat"), "isup": m.get("isup")}
            else:
                nom[key] = m["ptat"]
        out["nominal"] = {"n_points": len(nu["report"]["corners"]), "n_valid": len(nom),
                          "invalid": {f"{k[0]}_{k[2]:g}c_{k[1]:.2f}v": v for k, v in sorted(nom_inval.items())}}
        out["nominal_ptat"] = {f"{k[0]}_{k[2]:g}c_{k[1]:.2f}v": v for k, v in sorted(nom.items())}
    else:
        out["nominal"] = {"refusal": nu["refusal"], "n_valid": 0}
    # --- MC groups
    for v, p, s in PLAN_MC:
        g = {"variant": v, "process": p, "supply": s, "per_temp": {}, "units": {}, "missing": []}
        samples = {}  # sample_index -> {T: measurements}
        n_req = group_n(v, p, s)
        for t in TEMPS:
            name = f"{v}__{p}_{s:.2f}v_{sim_common_t(t)}c"
            ent = load_unit(run_dir, name)
            if not ent["report"]:
                g["missing"].append({"temp": t, "unit": name, "refusal": ent["refusal"]})
                continue
            rep = ent["report"]
            remote = rep.get("environment", {}).get("remote", {})
            g["units"][str(t)] = {k: remote.get(k) for k in ("job_id", "instance_type", "lifecycle", "elapsed_seconds")}
            g["units"][str(t)]["status"] = rep.get("status")
            g["units"][str(t)]["ngspice"] = rep.get("environment", {}).get("engine_version")
            g["family_mismatch"] = rep.get("environment", {}).get("monte_carlo", {}).get("family_mismatch")
            for c in rep["corners"]:
                si = (c.get("monte_carlo") or {}).get("sample_index")
                samples.setdefault(si, {})[t] = mvals(c)
            g["per_temp"][str(t)] = {"requested": n_req, "returned": sum(1 for sm in samples.values() if t in sm)}
        g["n_samples_seen"] = len(samples)
        # guard each (sample, T)
        inval = {str(t): {} for t in TEMPS}
        for si, by in samples.items():
            for t, m in by.items():
                r = guard(m)
                if r:
                    inval[str(t)][r] = inval[str(t)].get(r, 0) + 1
                    by[t] = dict(m, _invalid=r)
        g["invalid_by_temp"] = inval
        ref = [nom.get((p if not p.endswith("_mm") else p[:-3], s, t)) for t in TEMPS]
        # klt echoes the process string it was given (e.g. tt_mm); the nominal reference is the plain section
        g["nominal_ref_ptat"] = ref
        if v.startswith("control") or None in ref:
            if None in ref and not v.startswith("control"):
                g["note"] = "nominal reference invalid at one or more temperatures: errors NOT computed for this group"
            spread = {}
            for t in TEMPS:
                vals = [by[t]["ptat"] for by in samples.values() if t in by and "_invalid" not in by[t]]
                spread[str(t)] = {"n": len(vals), "sigma_ptat_V": sd(vals), "mean_ptat_V": statistics.mean(vals) if vals else None}
            g["ptat_spread"] = spread
            out["groups"][f"{v}__{p}_{s:.2f}v"] = g
            continue
        sl = [slope_at(TEMPS, ref, i) for i in range(3)]
        g["slope_V_per_C"] = sl
        res = {}
        for i, t in enumerate(TEMPS):
            un = []
            tr = []
            dnorm = []
            for si, by in samples.items():
                if t not in by or "_invalid" in by[t]:
                    continue
                e_un = (by[t]["ptat"] - ref[i]) / sl[i]
                un.append(e_un)
                dnorm.append((si, (by[t]["ptat"] - ref[i]) / ref[i]))
                a = by.get(TRIM_T)
                if a is not None and "_invalid" not in a:
                    gain = ref[TEMPS.index(TRIM_T)] / a["ptat"]
                    tr.append((by[t]["ptat"] * gain - ref[i]) / sl[i])
            res[str(t)] = {
                "n_untrimmed": len(un), "n_trimmed": len(tr),
                "untrimmed": {"mean_C": statistics.mean(un) if un else None, "sigma_C": sd(un), "k_sigma_C": (SIGMA_K * sd(un)) if sd(un) is not None else None,
                              "max_abs_C": max((abs(x) for x in un), default=None), "p99_7_abs_C": pctl([abs(x) for x in un], 0.997)},
                "trimmed": {"mean_C": statistics.mean(tr) if tr else None, "sigma_C": sd(tr), "k_sigma_C": (SIGMA_K * sd(tr)) if sd(tr) is not None else None,
                            "max_abs_C": max((abs(x) for x in tr), default=None), "p99_7_abs_C": pctl([abs(x) for x in tr], 0.997)},
                "_dnorm": dnorm,
            }
        g["errors"] = res
        # pairing diagnostic: correlation across temperature of the per-sample relative PTAT deviation
        corr = {}
        for a, b in ((-40, 27), (27, 125), (-40, 125)):
            da = dict(res[str(a)]["_dnorm"])
            db = dict(res[str(b)]["_dnorm"])
            common = sorted(set(da) & set(db))
            if len(common) > 3 and sd([da[k] for k in common]) and sd([db[k] for k in common]):
                corr[f"{a}/{b}"] = statistics.correlation([da[k] for k in common], [db[k] for k in common])
            else:
                corr[f"{a}/{b}"] = None
        g["pairing_correlation"] = corr
        for t in res:
            res[t].pop("_dnorm")
        # injected-offset sigma check (explicit terms)
        inj = {}
        for dev, (_g, kind, w, l, role) in INJECT.items():
            vals = [by[27][f"dv_{dev.lower()}"] for by in samples.values() if 27 in by and by[27].get(f"dv_{dev.lower()}") is not None]
            inj[dev] = {"n": len(vals), "sigma_V": sd(vals), "expected_sigma_V": AVT[kind] / math.sqrt(w * l)}
        g["injected_offsets"] = inj
        out["groups"][f"{v}__{p}_{s:.2f}v"] = g
    return out


# ----------------------------------------------------------------------------------------------- record

def fmt(x, f="{:.3g}"):
    return "n/a" if x is None else f.format(x)


def cmd_record(args):
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    last = meta.get("resumes", [None])[-1] or meta
    git = last["git"]
    if git["dirty"]:
        sys.exit("refusing to write a record from a run whose latest invocation had a dirty tree")
    now_git = cr.git_state()
    if now_git["dirty"]:
        sys.exit("refusing to write a record with a dirty working tree (commit the runner first)")
    klt_client = last.get("klt_client", meta["klt_client"])
    an = analyse(run_dir)
    now = datetime.now(timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{now_git['sha']}"
    rec_dir = SIM_DIR / SLUG
    if (rec_dir / "records" / f"{rid}.md").exists():
        sys.exit(f"refusing to overwrite record {rid}")
    snap = rec_dir / "netlist-snapshots" / rid
    snap.mkdir(parents=True)
    cdir = rec_dir / "corners" / rid
    cdir.mkdir(parents=True)
    for v in VARIANTS:
        (snap / f"{v}.spice").write_text(sim_common.scrub(build_netlist(v), run_dir, REPO_ROOT))
    # compact per-unit corner logs: request + report digest + fleet job
    for u in sorted(p for p in run_dir.iterdir() if p.is_dir() and (p / "request.json").is_file()):
        txt = ["request:", (u / "request.json").read_text()]
        try:
            rep = json.loads((u / "report.json").read_text())
            txt.append(f"status: {rep.get('status')}  summary: {json.dumps(rep.get('summary'))}")
            txt.append(f"remote: {json.dumps(rep.get('environment', {}).get('remote'))}")
            for c in rep.get("corners", []):
                m = mvals(c)
                txt.append(f"{c.get('corner_id')}  status={c.get('status')}  " + "  ".join(f"{k}={m.get(k)}" for k in MEAS[:8]))
        except (OSError, json.JSONDecodeError):
            txt.append("report: unusable; klt.stderr:\n" + (u / "klt.stderr").read_text() if (u / "klt.stderr").is_file() else "report: unusable")
        (cdir / f"{u.name}.log").write_text(sim_common.scrub("\n".join(txt), run_dir, REPO_ROOT) + "\n")

    G = an["groups"]

    def err(variant, proc="tt", sup=3.30, trim="untrimmed", t=None):
        g = G.get(f"{variant}__{proc}_{sup:.2f}v", {})
        if "errors" not in g:
            return None
        return g["errors"][str(t)][trim]["sigma_C"]

    # quadrature sum of the four single-term sigmas (untrimmed and trimmed), per temperature
    quad = {}
    for trim in ("untrimmed", "trimmed"):
        for t in TEMPS:
            parts = [err(v, trim=trim, t=t) for v in ("pnp", "res", "amp", "mirror")]
            quad[f"{trim}@{t}"] = None if any(x is None for x in parts) else math.sqrt(sum(x * x for x in parts))
    unmeasured = [
        "bias_core and the tail/startup/enable MOS of temp_core: covered ONLY inside the `all` native variant (not separately attributed)",
        "global (inter-die) process Monte Carlo (`vary` is `mismatch`; MC_PR_SWITCH is not exercised): only the five deterministic process corners are run, and the reference transfer function is re-derived per corner, so a die-to-die shift of the calibration is NOT in any figure here",
        "comparator/buffer offset: temp_core has no output buffer (design/temp_core.md); a downstream ADC/buffer offset is out of scope and unmeasured",
        "trim resolution and trim-switch/ladder error: the 1-point trim is an ideal continuous gain correction at 27 C (the physical strap ladder is not instantiated)",
        "CTAT-referenced readout: the temperature error is evaluated on the PTAT output only; CTAT error is not graded here",
        "temperatures between -40/27/125 C: the error is evaluated at those three points; curvature between them is unmeasured",
        "supply-ramp-rate dependence (one 100 us ramp; ramp-rate coverage belongs to sim/supply-ramp-top)",
    ]
    rec = {
        "record_id": rid, "experiment": SLUG, "issue": 105, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git, "git_at_record": now_git, "klt": klt_client, "backend": meta["klt_sim_backend_env"], "run_id": args.run_id,
        "sigma_convention": f"{SIGMA_K} x sample standard deviation (Bessel-corrected) of the per-sample temperature error; empirical max and 99.7th percentile reported alongside",
        "mc": {"n_samples": N_SAMPLES, "n_extend": N_EXTEND, "n_control": N_CONTROL, "seed": SEED, "vary": "mismatch"},
        "analysis": an, "quadrature_sum_of_single_terms": quad, "unmeasured": unmeasured,
        "targets_C": {"untrimmed": TARGET_UNTRIMMED_C, "trimmed": TARGET_TRIMMED_C},
        "resumes": meta.get("resumes", []), "supersedes": args.supersedes or "(none)", "author": cr.default_author(),
    }
    (rec_dir / "records" / f"{rid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")

    L = [f"# Record {rid}", "",
         f"- **Record ID**: {rid}",
         f"- **Experiment**: `{SLUG}` -- full-signal-path mismatch Monte Carlo of `temp_core`: PTAT temperature error with per-term attribution (issue #105, DR-003 row 2 `[TBD-1]`)",
         "- **Claim**: evidence only (the ratified spec is not edited and `[TBD-1]` stays open). Reports the measured temperature error in degC, untrimmed and with a 1-point (27 C) gain trim, per mismatch term and aggregate, and lists every term NOT measured.",
         "- **Netlist provenance**: committed `design/netlist/{bias_core,temp_core}.spice` in a generated testbench (`netlist-snapshots/%s/`); the explicit-injection variants add series gate sources to a copy of the committed `temp_core` text (0 V when off)" % rid,
         "- **PDK**: sky130A @ open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (sim/pdk.json pin), models `libs.tech/combined/sky130.lib.spice`",
         f"- **Tools**: {klt_client} (client); backend `{meta['klt_sim_backend_env']}` (every request submitted with an explicit `--backend batch`; nothing run locally, no local fallback)",
         f"- **Repo state**: `{git['sha']}` on `{git['branch']}` (working tree {'DIRTY' if git['dirty'] else 'clean'} at run time)"
         + "".join(f"; resumed {r['started_utc']} at `{r['git']['sha']}` (working tree {'DIRTY' if r['git']['dirty'] else 'clean'})" for r in meta.get("resumes", [])),
         f"- **MC settings**: N = {N_SAMPLES} samples per (variant, temperature) at tt/3.30 V, {N_EXTEND} for the all-native runs at the extra corners (controls N = {N_CONTROL}), `monte_carlo.vary = mismatch`, base seed {SEED}; one request per temperature so the draws are paired across -40/27/125 C",
         "- **PVT**: attribution at tt, 3.30 V; the all-native aggregate additionally at ss/ff/sf/fs (3.30 V) and tt at 2.97/3.63 V; every point at -40/27/125 C. The nominal reference is the full 45-point matrix.",
         f"- **Statistical convention**: {rec['sigma_convention']}",
         "- **Operating-point guard**: a sample is VALID only if ptat/ctat/na/nb/isup/bias_ok are inside the windows of `sim/temp-core-startup/experiment.json` (unrelaxed) and PTAT/CTAT moved < 1 mV over the last millisecond. Invalid samples are excluded from every statistic and counted below; they are never replaced.",
         "- **Cited, not duplicated**: solver record `sim/temp-core-startup-solver/records/20261010-200708-47b96e5` (issue #86): no real startup failure found, but PARTIAL (six historical FAILs did not reproduce; 4 of 10 combos NOT-RUN) and every variant it ran still produced 1-5 of 45 non-physical landings per matrix, which is why the guard above exists. PNP-pair-only mismatch: `sim/pnp-mismatch/records/20260825-220116-a9cac4b` (sigma(dVBE) 0.067-0.138 mV on the 1x-vs-8x array).",
         ""]
    nm = an["nominal"]
    L += ["## Nominal reference", ""]
    if "refusal" in nm:
        L += [f"- Nominal matrix NOT-RUN: {json.dumps(nm['refusal'])}. No error can be computed without it.", ""]
    else:
        L += [f"- {nm['n_valid']}/{nm['n_points']} points valid. Invalid nominal points (their groups have no error figure): "
              + ("; ".join(f"`{k}` ({v['reason']})" for k, v in nm["invalid"].items()) or "none"), ""]
    L += ["## Per-group sample accounting and fleet jobs", "",
          "| group | temp | requested | returned | invalid (by reason) | fleet job | status |", "|---|---|---|---|---|---|---|"]
    for gk, g in G.items():
        for t in TEMPS:
            pt = g["per_temp"].get(str(t))
            if pt is None:
                ms = next((m for m in g["missing"] if m["temp"] == t), None)
                L.append(f"| `{gk}` | {t} | - | NOT-RUN | - | - | {json.dumps(ms['refusal'] if ms else None)[:160]} |")
                continue
            inv = g["invalid_by_temp"][str(t)]
            ju = g["units"][str(t)]
            L.append(f"| `{gk}` | {t} | {pt['requested']} | {pt['returned']} | {sum(inv.values())} ({', '.join(f'{k}: {v}' for k, v in inv.items()) or '-'}) | {ju.get('job_id')} | {ju.get('status')} |")
    L += ["", "## Controls (negative controls: sigma must be exactly zero)", ""]
    for gk in ("control-off__tt_3.30v", "control-zeroed__tt_3.30v"):
        g = G.get(gk)
        if not g:
            L.append(f"- `{gk}`: not run")
            continue
        L.append(f"- `{gk}`: " + "; ".join(f"{t} C: n={d['n']}, sigma(PTAT)={fmt(d['sigma_ptat_V'], '{:.3e}')} V" for t, d in g["ptat_spread"].items()))
    L += ["", "## Per-term error budget (tt, 3.30 V; sigma of the PTAT-referred temperature error, degC; 3-sigma in parentheses)", "",
          "| term | variant | untrimmed -40 | untrimmed 27 | untrimmed 125 | trimmed -40 | trimmed 27 | trimmed 125 | valid n (27 C) |", "|---|---|---|---|---|---|---|---|---|"]
    names = {"pnp": "PNP pair (native Is/Bf)", "res": "resistor ratio R2/R1 (native)", "amp": "amplifier offset (explicit Vth)", "mirror": "mirror ratio (explicit Vth)",
             "combined": "four terms combined", "all": "everything native (incl. bias_core, tail MOS, MIM cap)"}
    for v in ATTRIBUTION:
        g = G.get(f"{v}__tt_3.30v")
        if not g or "errors" not in g:
            L.append(f"| {names[v]} | `{v}` | NOT MEASURED | | | | | | |")
            continue
        cells = []
        for trim in ("untrimmed", "trimmed"):
            for t in TEMPS:
                e = g["errors"][str(t)][trim]
                cells.append(f"{fmt(e['sigma_C'])} ({fmt(e['k_sigma_C'])})")
        L.append(f"| {names[v]} | `{v}` | " + " | ".join(cells) + f" | {g['errors']['27']['n_untrimmed']} |")
    L.append("| quadrature sum of pnp+res+amp+mirror | (derived) | " + " | ".join(
        fmt(quad[f'{tr}@{t}']) for tr in ("untrimmed", "trimmed") for t in TEMPS) + " | |")
    L += ["", "Cross-check: the `combined` row (same draws for all four terms) should be near the quadrature sum if the terms are independent and small-signal; the `all` row adds terms outside the four.", "",
          "## Aggregate 3-sigma temperature error (degC) -- the figure DR-003 row 2 asks for", "",
          "Aggregate = the `combined` variant (PNP + amplifier offset + resistor ratio + mirror ratio, jointly sampled) and, as an upper-side cross-check, the `all`-native variant. Worst of the three temperatures:", ""]
    for v in ("combined", "all"):
        g = G.get(f"{v}__tt_3.30v")
        if g and "errors" in g:
            wu = max(g["errors"][str(t)]["untrimmed"]["k_sigma_C"] for t in TEMPS if g["errors"][str(t)]["untrimmed"]["k_sigma_C"] is not None)
            wt = max(g["errors"][str(t)]["trimmed"]["k_sigma_C"] for t in TEMPS if g["errors"][str(t)]["trimmed"]["k_sigma_C"] is not None)
            L.append(f"- `{v}`: untrimmed 3-sigma = **{wu:.3g} degC** ({wu / TARGET_UNTRIMMED_C:.2g}x the README target of {TARGET_UNTRIMMED_C} degC); 1-point trimmed 3-sigma = **{wt:.3g} degC** ({wt / TARGET_TRIMMED_C:.2g}x the README target of {TARGET_TRIMMED_C} degC). Targets are the un-ratified README numbers (DR-003 keeps them `[TBD-1]`); the ratio is context, not a spec verdict.")
        else:
            L.append(f"- `{v}`: NOT MEASURED (see sample accounting)")
    L += ["", "All-native aggregate across process and supply corners (worst temperature, 3-sigma, degC):", "",
          "| corner | untrimmed | trimmed | valid n (27 C) |", "|---|---|---|---|"]
    for p, s in [("tt", 3.30), ("ss", 3.30), ("ff", 3.30), ("sf", 3.30), ("fs", 3.30), ("tt", 2.97), ("tt", 3.63)]:
        g = G.get(f"all__{p}_{s:.2f}v")
        if g and "errors" in g:
            wu = max(g["errors"][str(t)]["untrimmed"]["k_sigma_C"] or 0 for t in TEMPS)
            wt = max(g["errors"][str(t)]["trimmed"]["k_sigma_C"] or 0 for t in TEMPS)
            L.append(f"| {p} {s:.2f} V | {wu:.3g} | {wt:.3g} | {g['errors']['27']['n_untrimmed']} |")
        else:
            L.append(f"| {p} {s:.2f} V | NOT MEASURED | NOT MEASURED | - |")
    L += ["", "## Validation of the method", "",
          "Pairing of draws across temperature (correlation of the per-sample relative PTAT deviation; about 1 = same device sample, about 0 = independent draws):", ""]
    for gk, g in G.items():
        if "pairing_correlation" in g:
            L.append(f"- `{gk}`: " + ", ".join(f"{k} C: {fmt(v, '{:.2f}')}" for k, v in g["pairing_correlation"].items()))
    L += ["", "Explicit-injection sigma vs the PDK formula (A_VT/sqrt(W*L)), measured at 27 C in the `amp`/`mirror`/`combined` groups:", ""]
    for gk in ("amp__tt_3.30v", "mirror__tt_3.30v"):
        g = G.get(gk)
        if g and "injected_offsets" in g:
            role = "amp" if gk.startswith("amp") else "mir"
            L.append(f"- `{gk}`: " + "; ".join(f"{d} sigma={fmt(x['sigma_V'], '{:.2e}')} V (expected {x['expected_sigma_V']:.2e}, n={x['n']})" for d, x in g["injected_offsets"].items() if INJECT[d][4] == role))
    L += ["", "klt `family_mismatch` report (which device families the PDK deck actually mismatches), from the `all` group:", ""]
    fm = (G.get("all__tt_3.30v") or {}).get("family_mismatch")
    L.append("- " + (json.dumps(fm) if fm else "not available"))
    L += ["", "## NOT measured (stated explicitly; no complete aggregate is claimed)", ""] + [f"- {x}" for x in unmeasured]
    L += ["", "## Links", "", f"- driver: `sim/{SLUG}/run_accuracy_mc.py`; json twin `records/{rid}.json`; decks `netlist-snapshots/{rid}/`; per-request digests `corners/{rid}/`",
          "", f"- **Timestamp**: {rec['timestamp']}", f"- **Author**: {rec['author']}", f"- **Supersedes**: {rec['supersedes']}"]
    (rec_dir / "records" / f"{rid}.md").write_text("\n".join(L) + "\n")
    print(rid)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--run-id")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--only", action="append", help="regex on the unit name (repeatable)")
    r.add_argument("--jobs", type=int, default=2)
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("probe")
    p.add_argument("variant", choices=list(VARIANTS))
    p.add_argument("proc")
    p.add_argument("temp")
    p.add_argument("supply")
    p.set_defaults(fn=cmd_probe)
    rc = sub.add_parser("record")
    rc.add_argument("--run-id", required=True)
    rc.add_argument("--supersedes", default=None)
    rc.set_defaults(fn=cmd_record)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
