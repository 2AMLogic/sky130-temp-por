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
import json
import math
import os
import re
import statistics
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
GRID = [(p, v) for p in PROCS for v in SUPPLIES]  # the 15 corners every term is expected to cover
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

# `none` negative control: the switching wrappers zero every mismatch source, so a sample must
# reproduce its corner's nominal curve bit-for-bit.  Anything below this is "exactly the
# no-mismatch curve"; see none_control() for why a NOT-COMPARED corner is not 0 V.
CONTROL_FLAT_V = 1e-9

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


# Variant "mirror-degen" (issue #284, DR-007 item 2): a rewrite of the GENERATED deck only, never of design/.
# XMP1..3 go L4 W8 -> L4 W32 (4x area) and each gets a series res_xhigh_po between VDD and its source pin; the
# cascodes XMPC1..3 (L1 W8) are unchanged.  R = W2 L660 of res_xhigh_po = 679 kOhm at tt/27 C (measured with one
# local op point: 0.3 V across it draws 0.442 uA, the 0.44 uA leg current DR-007 quotes -> ~0.3 V drop).
VARIANTS = ["baseline", "mirror-degen"]
MIRROR_LEGS = ["XMP1", "XMP2", "XMP3"]
DEGEN_W, DEGEN_L = 2, 660
MIRROR_W_NEW = 32
VARIANT_EXTRA_MIRROR = {"mirror-degen": [f"XRDEG{i}" for i in (1, 2, 3)]}  # degeneration resistors belong to the mirror term
VARIANT_DESC = {
    "baseline": "committed design/netlist unchanged",
    "mirror-degen": (f"XMP1..3 rewritten L4 W8 -> L4 W{MIRROR_W_NEW} (ad/as/pd/ps/nrd/nrs rescaled with W; cascodes XMPC1..3 unchanged), "
                     f"series sky130_fd_pr__res_xhigh_po W={DEGEN_W} L={DEGEN_L} (about 679 kOhm at tt/27 C) XRDEG1..3 between VDD and each "
                     "mirror source (new nodes SDG1..3); the XRDEG resistors are part of the `mirror` mismatch group"),
}


def degenerate_mirror(lines):
    """mirror-degen deck rewrite on continuation-joined temp_core lines; returns the new line list."""
    out, seen = [], 0
    for ln in lines:
        tok = ln.split()
        if tok and tok[0].upper() in MIRROR_LEGS:
            n = tok[0][-1]
            kv = {t.split("=")[0].lower(): t.split("=", 1)[1] for t in tok if "=" in t}
            if kv["l"] != "4" or kv["w"] != "8" or tok[3].upper() != "VDD":
                raise SystemExit(f"{tok[0]}: unexpected netlist (L={kv['l']} W={kv['w']} source={tok[3]}); variant rewrite refuses")
            w = float(MIRROR_W_NEW)
            new = {"w": f"{w:g}", "ad": f"{w * 0.29:.6g}", "as": f"{w * 0.29:.6g}", "pd": f"{2 * (w + 0.29):.6g}",
                   "ps": f"{2 * (w + 0.29):.6g}", "nrd": f"{0.29 / w:.6g}", "nrs": f"{0.29 / w:.6g}"}
            tok[3] = f"SDG{n}"
            tok = [f"{t.split('=')[0]}={new[t.split('=')[0].lower()]}" if "=" in t and t.split("=")[0].lower() in new else t for t in tok]
            out.append(" ".join(tok))
            out.append(f"XRDEG{n} VDD SDG{n} VSS sky130_fd_pr__res_xhigh_po W={DEGEN_W} L={DEGEN_L} mult=1 m=1")
            seen += 1
        else:
            out.append(ln)
    if seen != len(MIRROR_LEGS):
        raise SystemExit(f"mirror-degen: rewrote {seen} of {len(MIRROR_LEGS)} mirror legs")
    return out


def temp_core_group(inst, variant="baseline"):
    for g, members in GROUPS.items():
        if inst.upper() in members:
            return g
    if inst.upper() in VARIANT_EXTRA_MIRROR.get(variant, []):
        return "mirror"
    return "other"


def transform_cell(name, active, variant="baseline"):
    """Return the cell netlist with every device whose group is not in ``active`` routed through its mmoff wrapper."""
    txt = (REPO_ROOT / "design" / "netlist" / f"{name}.spice").read_text()
    out = []
    src = join_continuations(txt)
    if variant == "mirror-degen" and name == "temp_core":
        src = degenerate_mirror(src)
    for ln in src:
        tok = ln.split()
        if tok and tok[0].upper().startswith("X") and not ln.startswith(("*", ".")):
            model_i = next((i for i, t in enumerate(tok) if t.startswith("sky130_fd_pr__")), None)
            if model_i is not None:
                grp = temp_core_group(tok[0], variant) if name == "temp_core" else "other"
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


def build_netlist(term, variant="baseline"):
    if term in ("nominal", "all"):
        active = set(TERMS)
    elif term == "none":
        active = set()
    else:
        active = {term}
    lines = [
        f"* generated by sim/{SLUG}/run_accuracy_mc.py (term={term}{'' if variant == 'baseline' else ', variant=' + variant}) -- do not edit",
        *([f"* variant {variant}: {VARIANT_DESC[variant]}"] if variant != "baseline" else []),
        "* DC temperature sweep inside one ngspice process; EN tied to VDD; bias_core + temp_core as in the #86 solver bench.",
        "* ng_nomodcheck: carried in the netlist because the fleet runner ignores options.ngspice_init",
        *sim_common.NOMODCHECK_CONTROL.splitlines(),
        ".options wnflag=1",
        "VSUP VDD 0 3.3",
        "XBIAS VDD 0 IBIAS VREF BIAS_OK bias_core",
        "XDUT VDD 0 IBIAS VDD PTAT CTAT temp_core",
        "",
        wrapper_defs() if term not in ("nominal", "all") else "",
        transform_cell("bias_core", active, variant),
        transform_cell("temp_core", active, variant),
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


def build_request(term, backend, n, seed, corners=None, timeout=1800, capacity_wait_s=0):
    procs, supplies = corners or (PROCS, SUPPLIES)
    mm = term != "nominal"
    return sim_common.base_request(
        "netlist.spice", backend,
        {"process": [f"{p}_mm" if mm else p for p in procs], "supply_v": {"vsup": supplies},
         "temperature_c": [T_REF]},
        {"kind": "dc", "args": f"temp {T_LO} {T_HI} 1"},
        measurements(),
        timeout,
        capacity_wait_s=capacity_wait_s,
        waveforms=False,
        monte_carlo={"n": n, "seed": seed, "vary": "mismatch"} if mm else None,
    )


def variant_dir(base, variant):
    """baseline lives in the run directory itself (unchanged layout); a variant in <run dir>/<variant>/"""
    return base if variant == "baseline" else base / variant


def cmd_run(args):
    git = cr.git_state()
    sim_common.refuse_unsubmittable(git, args.allow_dirty)
    variant = args.variant
    if variant != "baseline" and not args.run_id:
        sys.exit("--variant needs --run-id: the variant shares the run id (and pin) of its baseline run")
    run_id, run_dir, now = sim_common.open_run(
        BUILD, args.run_id, git["sha"], reuse="allow" if args.resume else None,
        sub=None if variant == "baseline" else variant)
    terms = args.term or ["nominal", *RUN_TERMS]
    this = {"variant": variant, "capacity_wait_s": args.wait_for_capacity, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "klt_client": sim_common.klt_version(),
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
        seed = args.seed + (PROCS.index(proc) if proc else 0)
        req = build_request(term, "batch", args.n, seed, ([proc], SUPPLIES) if proc else None, capacity_wait_s=args.wait_for_capacity)
        units = (1 if term == "nominal" else args.n) * len(SUPPLIES) * (1 if proc else len(PROCS))
        name = f"{term}/{proc or 'all-proc'}"
        # the fleet has a shared instance cap; a refused LAUNCH is retried later (never replaced by a local grid)
        res = sim_common.submit_prepared(
            d, build_netlist(term, variant), req, f"{name}: {units} ngspice units -> batch fleet", name,
            retry=sim_common.cap_retry(d, name, 180, max_retries=59))
        return {"term": term, "proc": proc, **res}

    units_list = [(t, None) if t == "nominal" else (t, pr) for t in terms for pr in ([None] if t == "nominal" else PROCS)]
    results = sim_common.fan_out(one, units_list, args.jobs)
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
        (d / "netlist.spice").write_text(build_netlist(term, args.variant))
        req = build_request(term, "local", args.n, args.seed, ([args.process], [args.supply]))
        (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
        say(f"[probe] local single corner {term} {args.process} {args.supply} V, n={args.n}")
        pr = sim_common.run_local_probe(d)
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
    concurrency 1), merged here.  A process whose request has no usable report is listed in missing_procs.

    `report['environment']` is the FIRST usable process section only, so it is not a safe source of
    fleet-wide provenance: a full run is one job per process per term (36 jobs), and the other
    sections' runners may be on different installs.  `jobs` and `engines` therefore keep every
    process job's own `environment.remote` and `environment.engine_version` -- the per-job
    provenance `observed_provenance()` joins over (issue #312)."""
    ent = {"report": None, "refusal": None, "missing_procs": [], "jobs": {}, "engines": {}, "corners": {}}
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
            ent["engines"][proc or "all"] = rep["environment"].get("engine_version")
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


def none_control(an):
    """Grade the `none` negative control three-state: PASS / FAIL / NOT VERIFIED (issue #310).

    `analyse_term` leaves ``max_dev_from_nominal_V`` at ``None`` for a corner with no valid
    sample or no usable nominal point -- nothing was compared there.  Folding that to 0.0 V
    (``max_dev or 0.0``, the pre-#310 behaviour) turned "nothing was compared" into
    "0 V deviation" and rendered the control as PASS, so an all-invalid `none` term could
    certify the per-term attribution it is supposed to police, and corners that dropped out
    of a partially failed run silently left the max.

    A corner that was not compared therefore makes the whole control **NOT VERIFIED**,
    whatever the compared corners show; the max is reported over the compared corners only
    (``None`` when there are none) and the uncompared corners are named.

    Grading runs over the **expected** corner grid ``PROCS x SUPPLIES``, not over the keys
    `an` happens to carry (issue #318).  A process section whose request produced no usable
    report is recorded in ``missing_procs`` and contributes no key at all, so its corners
    reach `analyse_term` as absent rather than as present-with-nothing-compared; grading only
    what was present let a `none` term that lost a whole process section read PASS over "all
    12 corners", certifying three corners that were never simulated.  An absent corner counts
    exactly like one whose ``max_dev_from_nominal_V`` is ``None``.  The grid is a floor, never
    a filter: a key outside it is still graded, so no data handed in is silently dropped.
    """
    keys = GRID + sorted(k for k in an if k not in set(GRID))
    maxes = {k: (an[k]["max_dev_from_nominal_V"] if k in an else None) for k in keys}
    not_compared = sorted(f"{p}_{v:.2f}V" for (p, v) in keys if maxes[(p, v)] is None)
    devs = [d for d in maxes.values() if d is not None]
    max_dev = max(devs) if devs else None
    return {"max_dev_from_nominal_V": max_dev,
            "n_corners": len(keys),
            "n_corners_compared": len(devs),
            "corners_not_compared": not_compared,
            "flat_threshold_V": CONTROL_FLAT_V,
            "verdict": ("NOT VERIFIED" if not_compared or max_dev is None
                        else "PASS" if max_dev < CONTROL_FLAT_V else "FAIL")}


def control_line(ctrl):
    """The record's negative-control bullet, three-state (issue #310).

    A `none` term that compared nothing -- or compared only some of its corners -- can never
    render PASS here, because the max it would report is not a measurement of the corners
    that dropped out.  `ctrl` is `none_control()`'s dict, or `{}` when the term is absent.
    """
    head = "- Negative control (`none`: `_mm` section + Monte Carlo, every device wrapped to sigma = 0): "
    if not ctrl:
        return head + "**NOT AVAILABLE** (term not run / no usable result); the per-term attribution is not independently checked by this record."
    if ctrl["verdict"] == "NOT VERIFIED":
        return (head + f"**NOT VERIFIED**: {len(ctrl['corners_not_compared'])} of {ctrl['n_corners']} corners compared nothing "
                "(no valid sample, no usable nominal point, or no report at all): " + ", ".join(ctrl["corners_not_compared"]) + ". "
                + (f"Over the {ctrl['n_corners_compared']} corners that were compared, max |PTAT(sample) - PTAT(nominal)| = {ctrl['max_dev_from_nominal_V']:.3g} V, "
                   "but a max over a subset cannot certify the switching wrappers on the corners that dropped out"
                   if ctrl["n_corners_compared"] else "No corner was compared at all, so there is no measurement here")
                + " -- the per-term attribution cannot be trusted on this record's control.")
    return (head + f"max |PTAT(sample) - PTAT(nominal)| over all samples, all {ctrl['n_corners']} corners and all temperatures "
            f"= {ctrl['max_dev_from_nominal_V']:.3g} V "
            + (f"(PASS: exactly the no-mismatch curve, below {ctrl['flat_threshold_V']:g} V; the switching wrappers zero every mismatch source, and nothing else varies)"
               if ctrl["verdict"] == "PASS" else "(**FAIL**: the control is not flat; the per-term attribution cannot be trusted)"))


def compare_control_line(name, c):
    """The variant-compare record's per-deck `none == nominal` control bullet (same three states)."""
    head = f"- `none == nominal` control, {name} deck: "
    if c is None:
        return head + "**NOT AVAILABLE** (term not run / no usable result); not verified."
    if c["verdict"] == "NOT VERIFIED":
        return (head + f"**NOT VERIFIED** -- {len(c['corners_not_compared'])} of {c['n_corners']} corners compared nothing "
                "(no valid sample, no usable nominal point, or no report at all): " + ", ".join(c["corners_not_compared"]) + "; "
                + (f"max |PTAT(sample) - PTAT(nominal)| over the {c['n_corners_compared']} compared corners = {c['max_dev_from_nominal_V']:.3g} V, which does not cover the rest"
                   if c["n_corners_compared"] else "no corner was compared at all")
                + ". Attribution cannot be trusted on this control.")
    return (head + f"max |PTAT(sample) - PTAT(nominal)| over all {c['n_corners']} corners = {c['max_dev_from_nominal_V']:.3g} V "
            + (f"(PASS: below {c['flat_threshold_V']:g} V)" if c["verdict"] == "PASS" else "(**FAIL**: attribution cannot be trusted)"))


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
    # Resolved before anything is written: a record whose PDK line cannot be derived is a
    # record that must not exist, and failing here leaves no half-written record behind.
    # This makes `record` require an installed PDK, as the seven campaign runners and
    # `run_solver_sweep.py` already do -- the alternative, rendering `unknown` for the
    # host half, would weaken every record to spare a host that cannot reproduce the run.
    pdk = cr.resolve_pdk(cr.load_pin())
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
    # Fleet-side provenance off the reports themselves, so the header states what ran
    # rather than what was current when this code was written (issue #312).
    prov = observed_provenance(ents, pdk.pin)
    not_run = [t for t in RUN_TERMS if ents[t]["report"] is None] + (["nominal"] if nominal["report"] is None else [])
    partial = {t: ents[t]["missing_procs"] for t in RUN_TERMS if ents[t]["report"] is not None and ents[t]["missing_procs"]}
    xcheck = transient_crosscheck(nominal) if nominal["report"] else None
    # --- negative control (liveness rows are rendered straight from `summ`)
    ctrl = none_control(anal["none"]) if anal.get("none") else {}
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
    (rec_dir / "records" / f"{rid}.md").write_text(render_md(rec, anal, summ, summ_ctat, rss, ctrl, xcheck, not_run, fleet, meta, args, pdk, prov) + "\n")
    print(rid)
    return 0


def observed_provenance(ents, pin):
    """The fleet-side halves of the record header, derived from the run's own reports.

    Joined over every PROCESS JOB of every term -- a full run is 7 mismatch terms x 5
    process sections + nominal = 36 fleet jobs, each free to land on a runner with its own
    PDK install and engine.  Both values go through `sim_common.joined_versions()`, so each
    is the sorted SET of what was actually observed and reads `unknown` when no job
    reported one -- never first-found-only, and never a literal that goes stale (#312).
    Engines are tagged `ngspice-<n>` *before* joining because the report carries the bare
    number ("46") and `ngspice-unknown` is not a version.

    `*_jobs` / `*_reporting` are the coverage of each value: how many jobs reported one at
    all, out of how many ran.  Rendering uses them to keep a PARTIAL answer from reading
    like a unanimous one; see `render_pdk_tools_lines()`.

    The PDK of each job is read by `sim_common.runner_pdk()` -- the repo's one reader of
    the runner's own stamp, never the client-resolved `provenance.pdk` (issue #328) -- and
    deliberately off `ent['jobs']` rather than the merged `report['environment']`, which
    is the FIRST usable process section only: a term's other four runners (and any
    different install among them) were invisible that way (issue #315).

    `pin` is the `sim/pdk.json` pin those stamps are compared against, yielding the
    three-state `fleet_matches_pin` verdict the header line renders; before issue #333
    this block stated the stamp alone, with no verdict beside it.
    """
    jv = sim_common.joined_versions
    engines = [{"tag": f"ngspice-{v}"} if v else {}
               for e in ents.values() for v in (e.get("engines") or {}).values()]
    return {**sim_common.fleet_pdk_fields((sim_common.runner_pdk(j) for e in ents.values()
                                           for j in (e.get("jobs") or {}).values()), pin),
            "fleet_engine": jv(engines, "tag"),
            "fleet_engine_jobs": len(engines), "fleet_engine_reporting": sum(1 for e in engines if e.get("tag"))}


def coverage_note(prov, which):
    """A ` (from N of M fleet jobs; ...)` suffix when only SOME jobs reported `which`, else `""`.

    A set joined over 36 jobs of which 3 answered is not the same claim as one all 36
    agreed on, and the header sentence ("the fleet runners that executed the grid
    reported ...") reads as the latter.  The note is deliberately absent in the two
    unambiguous cases: every job reported (the value speaks for itself), and none did
    (the value is already `unknown`, which says exactly that).
    """
    n, m = prov[f"{which}_reporting"], prov[f"{which}_jobs"]
    return f" (from {n} of {m} fleet jobs; the rest reported none)" if 0 < n < m else ""


def render_pdk_tools_lines(rec, pdk, prov, fleet):
    """The record's `PDK` and `Tools` header lines.

    The grid ran on the fleet but the record is written here, so the PDK line names both
    halves explicitly and lets neither stand in for the other: the recording host's
    resolved install (with the same `sim_common.pin_state()` ternary
    `sim_common.render_pdk_tools_repo_state()` uses) and the stamp the fleet runners
    reported.  Before issue #312 this line stated one literal commit labelled
    "(sim/pdk.json pin)" that was in fact neither the pin nor this host's install, but the
    October fleet runners' stamp -- so the claim was wrong in both halves at once.
    """
    jobs = ", ".join(f"{t}[{k}]={j['job_id']}" for t, f in fleet.items() for k, j in f["jobs"].items())
    return [
        f"- **PDK**: {pdk.variant} @ open_pdks `{pdk.installed_commit}` ({sim_common.pin_state(pdk.matches_pin)}) on the host"
        f" that wrote this record, models `{pdk.pin['ngspice_lib']}` (`_mm` sections for"
        f" mismatch); the fleet runners that executed the grid reported `{prov['fleet_pdk']}`"
        + coverage_note(prov, "fleet_pdk")
        + f" (verdict: {sim_common.fleet_pin_state(prov['fleet_matches_pin'])});"
        f" that comparison is of commits only, so {sim_common.PIN_COMMIT_LIMIT}",
        f"- **Tools**: {rec['klt']} (client); backend `{rec['backend']}`; fleet engine"
        f" {prov['fleet_engine']}{coverage_note(prov, 'fleet_engine')}; fleet jobs: {jobs}",
    ]


def render_md(rec, anal, summ, summ_ctat, rss, ctrl, xcheck, not_run, fleet, meta, args, pdk, prov):
    rid, git = rec["record_id"], rec["git"]
    N = meta["n"]
    L = [f"# Record {rid}", "",
         f"- **Record ID**: {rid}",
         f"- **Experiment**: `{SLUG}` -- full-signal-path mismatch Monte Carlo of `temp_core`: temperature error in degC, per-term attribution (issue #105; DR-003 row 2 `[TBD-1]`)",
         "- **Claim**: NOT a spec claim and no `spec/` edit. Evidence toward `[TBD-1]`: the PTAT-referred temperature error of `temp_core` under local device mismatch, untrimmed and with a 1-point (27 C) gain trim, with the contribution of each mismatch term separated.",
         f"- **Netlist provenance**: schematic-derived committed `design/netlist/{{bias_core,temp_core}}.spice` in a generated testbench (`netlist-snapshots/{rid}/`); per-term device switching by `mmoff_*` wrapper subckts (see README)",
         *render_pdk_tools_lines(rec, pdk, prov, fleet),
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
    L.append(control_line(ctrl))
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


# ---------------------------------------------------------------------------------------------
# compare: baseline vs deck variant, mirror term only (issue #284)
# ---------------------------------------------------------------------------------------------

CMP_TERMS = ["nominal", "none", "mirror"]
DR007_PROJECTION = 0.10  # DR-007 decision item 2: mirror term projected at 0.10 x the record value
DR007_RECORD = "sim/temp-core-accuracy-mc/records/20261011-165907-69d13ac"


def _grade_variant(run_dir):
    ents = {t: load_term(run_dir, t) for t in CMP_TERMS}
    nominal = ents["nominal"]
    anal = {t: analyse_term(ents[t], nominal) if nominal["report"] and ents[t]["report"] else None for t in ("none", "mirror")}
    summ = {t: term_summary(a, "ptat") if a else None for t, a in anal.items()}
    return ents, anal, summ


def _ratio(a, b):
    return b / a if a and not math.isnan(a) and not math.isnan(b) else float("nan")


def _guard_counts(ent, an):
    """per-corner dict: n_total, n_invalid, n_invalid_at_125C, n_invalid_at_m40C, nominal_invalid reasons"""
    out = {}
    for key, cs in sorted(an.items()):
        out[key] = {"n_total": cs["n_total"], "n_valid": cs["n_valid"], "n_invalid": len(cs["invalid"]),
                    "n_invalid_125C": sum(any("@125C" in r or "T=125" in r for r in i["reasons"]) for i in cs["invalid"]),
                    "n_invalid_m40C": sum(any("@-40C" in r for r in i["reasons"]) for i in cs["invalid"]),
                    "nominal_invalid": cs["nominal_invalid"]}
    return out


def cmd_compare(args):
    variant = args.variant
    base_dir, var_dir = BUILD / args.run_id, variant_dir(BUILD / args.run_id, variant)
    metas = {}
    for name, d in (("baseline", base_dir), (variant, var_dir)):
        try:
            metas[name] = json.loads((d / "run.json").read_text())
        except (OSError, json.JSONDecodeError):
            sys.exit(f"no run.json under {d}: run `run --run-id {args.run_id}` for both variants first")
    gits = {k: (m.get("resumes", [None])[-1] or m)["git"] for k, m in metas.items()}
    for k, g in gits.items():
        if g["dirty"] and not args.allow_dirty:
            sys.exit(f"the {k} run was made from a DIRTY tree: not provenance-clean")
    grade_git = cr.git_state()
    if grade_git.get("dirty") and not args.allow_dirty:
        sys.exit("the grading tree is DIRTY: commit the analysis code first so the record is provenance-clean")
    now = datetime.now(timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{gits['baseline']['sha']}"
    rec_dir = SIM_DIR / SLUG
    if (rec_dir / "records" / f"{rid}.md").exists():
        sys.exit(f"refusing to overwrite record {rid}")
    pdk = json.loads((SIM_DIR / "pdk.json").read_text())
    graded = {}
    for name, d in (("baseline", base_dir), (variant, var_dir)):
        graded[name] = _grade_variant(d)
    snap, cdir = rec_dir / "netlist-snapshots" / rid, rec_dir / "corners" / rid
    for d in (rec_dir / "records", snap, cdir):
        d.mkdir(parents=True, exist_ok=True)
    fleet = {}
    for name, d in (("baseline", base_dir), (variant, var_dir)):
        ents, anal, _ = graded[name]
        (snap / name).mkdir()
        (cdir / name).mkdir()
        fleet[name] = {}
        for t in CMP_TERMS:
            subs = [(None, d / t)] if t == "nominal" else [(pr, d / t / pr) for pr in PROCS]
            for pr, dd in subs:
                if (dd / "netlist.spice").is_file():
                    tag = t if pr is None else f"{t}.{pr}"
                    (snap / name / f"{tag}.spice").write_text(sim_common.scrub((dd / "netlist.spice").read_text(), d, REPO_ROOT))
                    (snap / name / f"{tag}.request.json").write_text(sim_common.scrub((dd / "request.json").read_text(), d, REPO_ROOT))
            ent = ents[t]
            if ent["report"] is not None:
                env0 = ent["report"]["environment"]
                fleet[name][t] = {"jobs": {k: {kk: v.get(kk) for kk in ("job_id", "instance_type", "lifecycle", "runner_klt_version", "elapsed_seconds", "state")}
                                           for k, v in ent["jobs"].items()},
                                  "missing_procs": ent["missing_procs"], "engine_version": env0.get("engine_version"),
                                  "models_lib_sha256": env0.get("models_lib_sha256"),
                                  "models_lib_sha256_scope": env0.get("models_lib_sha256_scope")}
            if t != "nominal" and anal.get(t):
                write_samples_csv(cdir / name / f"samples-{t}.csv", t, ent, anal[t])
        nom = ents["nominal"]
        if nom["report"]:
            for c in nom["report"]["corners"]:
                proc, supply, _ = parse_cid(c["corner_id"])
                vals = {m["name"]: m.get("value") for m in c["measurements"]}
                why = guard_check(vals) if all(v is not None for v in vals.values()) else ["unextractable measurement"]
                (cdir / name / f"nominal_{proc}_{supply:.2f}v.log").write_text(
                    f"corner {c['corner_id']}  variant {name}  term nominal  klt status={c.get('status')}  guards={'ok' if not why else why}\n"
                    + "\n".join(f"{k} = {v}" for k, v in vals.items()) + "\n")
    # --- numbers
    cmp_rows = {}
    for key in sorted(set(graded["baseline"][1]["mirror"] or {}) & set(graded[variant][1]["mirror"] or {})):
        row = {}
        for mode in ("untrimmed", "trim1"):
            b = worst_over_T(graded["baseline"][1]["mirror"][key], "ptat", mode)
            v = worst_over_T(graded[variant][1]["mirror"][key], "ptat", mode)
            row[mode] = {"baseline": b, variant: v, "ratio": _ratio(b[0], v[0])}
        cmp_rows[key] = row
    sb, sv = graded["baseline"][2]["mirror"], graded[variant][2]["mirror"]
    head = {}
    if sb and sv:
        for mode in ("untrimmed", "trim1"):
            if sb[mode] and sv[mode]:
                head[mode] = {
                    "worst_corner": {"baseline": sb[mode]["worst_corner"], variant: sv[mode]["worst_corner"],
                                     "ratio": _ratio(sb[mode]["worst_corner"]["k3sd"], sv[mode]["worst_corner"]["k3sd"])},
                    "tt_3p30": ({"baseline": sb[mode]["tt_3p30"], variant: sv[mode]["tt_3p30"],
                                 "ratio": _ratio(sb[mode]["tt_3p30"]["k3sd"], sv[mode]["tt_3p30"]["k3sd"])}
                                if sb[mode]["tt_3p30"] and sv[mode]["tt_3p30"] else None),
                    "pooled": {"baseline": sb[mode]["pooled_worst"], variant: sv[mode]["pooled_worst"],
                               "ratio": _ratio(sb[mode]["pooled_worst"], sv[mode]["pooled_worst"])}}
    guards = {name: {t: _guard_counts(graded[name][0][t], graded[name][1][t]) for t in ("none", "mirror") if graded[name][1][t]} for name in graded}
    nom_bad = {name: sorted(f"{p}_{v:.2f}V" for t in ("none", "mirror") if graded[name][1][t] for (p, v), cs in graded[name][1][t].items() if cs["nominal_invalid"])
               for name in graded}
    ctrl = {}
    for name in graded:
        a = graded[name][1]["none"]
        ctrl[name] = none_control(a) if a else None
    rec = {"record_id": rid, "experiment": SLUG, "issue": 284, "kind": "variant-compare", "variant": variant,
           "variant_description": VARIANT_DESC[variant], "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": args.run_id,
           "runs_git": gits, "graded_at_git": grade_git, "pdk_pin": pdk["open_pdks_commit"], "klt": metas["baseline"].get("klt_client"),
           "backend": metas["baseline"].get("klt_sim_backend_env"), "n_per_corner": metas["baseline"]["n"], "seed": metas["baseline"]["seed"],
           "capacity_wait_s": {k: m.get("capacity_wait_s") for k, m in metas.items()},
           "resumes": {k: {"resumes": m.get("resumes", [])} for k, m in metas.items()},
           "dr007_projection_ratio": DR007_PROJECTION, "headline": head, "per_corner": {f"{k[0]}_{k[1]:.2f}V": r for k, r in cmp_rows.items()},
           "guard_counts": {n: {t: {f"{k[0]}_{k[1]:.2f}V": c for k, c in g.items()} for t, g in gt.items()} for n, gt in guards.items()},
           "nominal_invalid_corners": nom_bad, "none_control": ctrl, "fleet": fleet,
           "dimensions": {"degen_W": DEGEN_W, "degen_L": DEGEN_L, "mirror_W_new": MIRROR_W_NEW}, "author": cr.default_author()}
    (rec_dir / "records" / f"{rid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    (rec_dir / "records" / f"{rid}.md").write_text(render_compare_md(rec, graded, variant, guards, cmp_rows, head) + "\n")
    print(rid)
    return 0


def render_compare_md(rec, graded, variant, guards, cmp_rows, head):
    rid, N = rec["record_id"], rec["n_per_corner"]
    L = [f"# Record {rid}", "",
         f"- **Record ID**: {rid}",
         f"- **Experiment**: `{SLUG}` -- mirror-term Monte Carlo, baseline vs `{variant}` deck (issue #284; measures the DR-007 item 2 projection)",
         "- **Claim**: NOT a spec claim; no `spec/` or `design/` edit, DR-007 untouched. Measures the mirror-term ratio DR-007 only projects.",
         f"- **Variant `{variant}`** (a rewrite of the generated deck only): {VARIANT_DESC[variant]}. Resistor: `res_xhigh_po` W={DEGEN_W} L={DEGEN_L}, ~679 kOhm at tt/27 C. "
         f"Mirror group = XMP1..3 (rewritten) **and** the unchanged cascodes XMPC1..3, as in the baseline record's mirror term, plus XRDEG1..3 in the variant.",
         f"- **PDK**: sky130A @ open_pdks `{rec['pdk_pin']}` (`sim/pdk.json` pin). Baseline and variant ran in ONE run (`{rec['run_id']}`) under this pin; "
         f"the 2026-10-11 record `{DR007_RECORD}` was made under `c6d73a3` and is NOT the baseline here.",
         f"- **Tools**: {rec['klt']} (client); backend `{rec['backend']}`; `batch.capacity_wait_s` {rec['capacity_wait_s']}",
         "- **Fleet jobs**: " + "; ".join(f"{n}/{t}[{k}]={j['job_id']}" for n, ft in rec["fleet"].items() for t, f in ft.items() for k, j in f["jobs"].items()),
         "- **Model library identity**: the request names the PDK `sky130A` and the library path; the report records the library sha256 `" + (next((f["models_lib_sha256"] for ft in rec["fleet"].values() for f in ft.values() if f.get("models_lib_sha256")), "?")) + "` with scope `client` (hashed on the submitting host, whose `~/.ciel/sky130A` resolves to the pinned open_pdks version). It is NOT an independent check of the library the fleet runner loaded.",
         "- **Resumes**: " + ("; ".join(f"{n}: resumed {r['started_utc']} (terms {r['terms']}) at `{r['git']['sha']}`" for n, m in rec["resumes"].items() for r in m.get("resumes", [])) or "none")
         + ". A unit whose fleet job ended without usable results (e.g. `batch_job_interrupted`, a Spot reclaim) is resubmitted to the fleet and its earlier attempt is archived under `attemptN/` in the git-ignored run directory; no unit was run locally.",
         f"- **Repo state**: baseline run `{rec['runs_git']['baseline']['sha']}`, variant run `{rec['runs_git'][variant]['sha']}` (working trees clean at run time); graded at `{rec['graded_at_git']['sha']}`",
         f"- **PVT + MC**: process tt/ss/ff/sf/fs (`_mm`) x 2.97/3.30/3.63 V = 15 corners; -40..125 C swept in-process, evaluated at -40/27/125 C; `vary: mismatch`, **N = {N} per corner**, seed {rec['seed']}; terms `nominal`, `none` (control), `mirror`.",
         "- **Convention / error definition / guards**: identical to the base experiment (3 sigma = 3 x sample sd per corner; error vs same-corner nominal through the nominal PTAT slope; same operating-point guards, invalid samples excluded and counted). Variant statistics use the variant's OWN nominal.", ""]
    L += [f"## Mirror-term ratio, measured vs DR-007's projection of {DR007_PROJECTION:.2f}x", ""]
    if head:
        L += [f"| mode | scope | baseline 3 sigma (degC) | {variant} 3 sigma (degC) | **measured ratio** | DR-007 projection |", "|---|---|---|---|---|---|"]
        for mode, nm in (("untrimmed", "untrimmed"), ("trim1", "1-pt 27 C trim")):
            if mode not in head:
                continue
            h = head[mode]
            wb, wv = h["worst_corner"]["baseline"], h["worst_corner"][variant]
            L.append(f"| {nm} | worst corner (own worst each) | {f3(wb['k3sd'], 2)} (`{wb['corner']}`, {wb['at_T']} C) | {f3(wv['k3sd'], 2)} (`{wv['corner']}`, {wv['at_T']} C) | **{f3(h['worst_corner']['ratio'], 3)}** | {DR007_PROJECTION:.2f} |")
            if h["tt_3p30"]:
                L.append(f"| {nm} | tt / 3.30 V | {f3(h['tt_3p30']['baseline']['k3sd'], 2)} | {f3(h['tt_3p30'][variant]['k3sd'], 2)} | **{f3(h['tt_3p30']['ratio'], 3)}** | {DR007_PROJECTION:.2f} |")
            L.append(f"| {nm} | RMS-pooled over corners | {f3(h['pooled']['baseline'], 2)} | {f3(h['pooled'][variant], 2)} | **{f3(h['pooled']['ratio'], 3)}** | {DR007_PROJECTION:.2f} |")
        L += ["", "### Per corner (worst of the evaluated temperatures; ratio = variant / baseline)", "",
              f"| corner | untrimmed base | untrimmed {variant} | ratio | 1-pt trim base | 1-pt trim {variant} | ratio |", "|---|---|---|---|---|---|---|"]
        for key, r in sorted(cmp_rows.items()):
            u, t_ = r["untrimmed"], r["trim1"]
            L.append(f"| {key[0]}_{key[1]:.2f}V | {f3(u['baseline'][0], 2)} | {f3(u[variant][0], 2)} | {f3(u['ratio'], 3)} | {f3(t_['baseline'][0], 2)} | {f3(t_[variant][0], 2)} | {f3(t_['ratio'], 3)} |")
    else:
        L += ["**NOT AVAILABLE**: the `mirror` or `nominal` term has no usable result for one of the variants; no ratio is claimed.", ""]
    L += ["", "## Operating-point guard failures per corner (DR-007's headroom question)", "",
          "Counts are samples excluded by the operating-point guards (any temperature); the `@125C` / `@-40C` columns count those whose reasons include a failure at that temperature. "
          "**2.97 V corners are the headroom question** (PTAT branch at 2.97 V / 125 C, DR-007 'feasible but tight and unsimulated'); they are marked.", ""]
    for t in ("mirror", "none"):
        L += [f"### term `{t}`", "", f"| corner | base invalid / total | base @125C | base @-40C | {variant} invalid / total | {variant} @125C | {variant} @-40C | nominal point ok (base / {variant}) |", "|---|---|---|---|---|---|---|---|"]
        gb, gv = guards["baseline"].get(t, {}), guards[variant].get(t, {})
        for key in sorted(set(gb) | set(gv)):
            b, v = gb.get(key), gv.get(key)
            mark = " **(2.97 V)**" if key[1] == 2.97 else ""
            fmt_ = lambda c, k: "n/a" if c is None else str(c[k])
            nok = lambda c: "n/a" if c is None else ("ok" if not c["nominal_invalid"] else "FAIL")
            L.append(f"| {key[0]}_{key[1]:.2f}V{mark} | {fmt_(b, 'n_invalid')} / {fmt_(b, 'n_total')} | {fmt_(b, 'n_invalid_125C')} | {fmt_(b, 'n_invalid_m40C')} | "
                     f"{fmt_(v, 'n_invalid')} / {fmt_(v, 'n_total')} | {fmt_(v, 'n_invalid_125C')} | {fmt_(v, 'n_invalid_m40C')} | {nok(b)} / {nok(v)} |")
        tb = sum(c["n_invalid"] for c in gb.values()) if gb else None
        tv = sum(c["n_invalid"] for c in gv.values()) if gv else None
        L += ["", f"Total invalid: baseline {tb}, {variant} {tv}.", ""]
    for name in ("baseline", variant):
        L.append(f"- Corners whose nominal reference failed a guard ({name}; all their samples excluded): " + (", ".join(sorted(set(rec["nominal_invalid_corners"][name]))) or "none"))
    L += ["", "## Controls", ""]
    for name in ("baseline", variant):
        L.append(compare_control_line(name, rec["none_control"][name]))
    for t in ("mirror",):
        for name in ("baseline", variant):
            sm = graded[name][2][t]
            if sm and sm["untrimmed"]:
                L.append(f"- Liveness `{t}`, {name}: pooled untrimmed 3 sigma = {sm['untrimmed']['pooled_worst']:.3g} degC")
    L += ["", "## Not measured / limits", "",
          "- Only the `mirror` term (plus `nominal` and the `none` control) was run; the all-terms aggregate and the other attribution terms are not re-measured, so no new untrimmed/trim total is claimed.",
          "- Variant deck is a rewrite of the generated testbench, not a schematic change; layout parasitics, resistor self-heating and systematic mismatch are not modelled. Local mismatch only (global process MC not sampled); DC sweep, not a cold-start transient.",
          "- The degeneration resistor value is one sizing (about 0.3 V at 27 C, per DR-007 item 2); no optimisation across values was done. DR-007 is not edited; its update belongs to the ratification lane.",
          f"- Statistical resolution: N = {N} per corner (chi-square 95 % interval on a per-corner sigma: about -13 % / +17 % at n = 100); a ratio of two such estimates carries both.", ""]
    L += ["## Links", "", f"- driver `sim/{SLUG}/run_accuracy_mc.py` (`run --variant`, `compare`); json twin `records/{rid}.json`; decks and requests `netlist-snapshots/{rid}/<variant>/`; samples `corners/{rid}/<variant>/`",
          f"- **Timestamp**: {rec['timestamp']}", f"- **Author**: {rec['author']}", "- **Supersedes**: (none)"]
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
    r.add_argument("--variant", choices=VARIANTS, default="baseline",
                   help="deck variant (issue #284); 'mirror-degen' needs --run-id of the baseline run and writes under <run dir>/mirror-degen/")
    r.add_argument("--wait-for-capacity", type=int, default=0, metavar="S",
                   help="request batch.capacity_wait_s (host rule: 600 on every batch submit); 0 = leave out (default)")
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("probe")
    p.add_argument("--run-id", required=True)
    p.add_argument("--term", action="append", required=True, choices=["nominal", *RUN_TERMS])
    p.add_argument("--process", default="tt")
    p.add_argument("--supply", type=float, default=3.3)
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--variant", choices=VARIANTS, default="baseline")
    p.set_defaults(fn=cmd_probe)
    rc = sub.add_parser("record")
    rc.add_argument("--run-id", required=True)
    rc.add_argument("--supersedes", default=None, help="record id this record replaces (append-only: the old record is untouched)")
    rc.add_argument("--allow-dirty", action="store_true")
    rc.set_defaults(fn=cmd_record)
    cp = sub.add_parser("compare", help="issue #284: grade a baseline + mirror-degen run pair (nominal/none/mirror) into one new record")
    cp.add_argument("--run-id", required=True)
    cp.add_argument("--variant", choices=VARIANTS[1:], default="mirror-degen")
    cp.add_argument("--allow-dirty", action="store_true")
    cp.set_defaults(fn=cmd_compare)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
