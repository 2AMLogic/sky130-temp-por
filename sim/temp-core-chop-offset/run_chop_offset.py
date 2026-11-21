#!/usr/bin/env python3
"""Chopped-amplifier residual input offset of the `chop-degen` temp_core variant (issue #461).

Question (DR-007 item 1): DR-007 recommends chopping (or auto-zeroing) the temp_core
amplifier so the residual input offset is <= 0.05 mV, and explicitly does NOT verify that
number ("design target, an assumption this DR does not verify").  This experiment builds
the chopped + degenerated-mirror deck (variant `chop-degen` of sim/temp-core-accuracy-mc:
the #284 mirror rewrite plus cross-coupled input/output choppers around the input pair)
and MEASURES the residual input-referred offset under local mismatch.

Method:

  static, two-phase DC   per mismatch sample, BOTH chop phases are solved as DC
                         temperature sweeps on the same physical draw (the phase A and B
                         decks are byte-identical except the four chopper control
                         literals, so two klt requests sharing corners/seed/N re-draw the
                         same devices per sample index -- klt derives the sample seed from
                         the corner index, the same property the #105 campaign's
                         per-process-section split already relies on).  Each phase is
                         guard-checked on its own; only complete, fully valid pairs are
                         averaged (PTAT and CTAT separately), the pair average is compared
                         against the variant's own phase-averaged nominal at the same PVT,
                         and the difference is referred to the amplifier input through
                         G = dPTAT/dVos = 26 V/V (DR-007's (R2+R2TRIM)/R1; the chopper
                         adds no device in that path).  An incomplete pair is counted as
                         invalid, never substituted.
  clocked transient      a small corner set (tt / 3.30 V and the worst static-residual
                         point) with a real make-before-break chopping clock: PTAT and
                         CTAT peak-to-peak ripple (charge injection + clock feedthrough +
                         loop response, reported separately) and the integer-cycle-average
                         residual vs the no-mismatch transient at the same PVT, input
                         referred through the same G.  The larger of the DC and transient
                         residuals is the reported one.

Negative control: the variant's own `none` term (every device wrapped to sigma = 0) is
graded phase-matched against the variant's `nominal` on the driver's expected 15-corner
grid, with the driver's existing three-state grader (a missing corner reads NOT VERIFIED).

Execution model (host rules): every grid is ONE `klt sim` request per (term, phase,
process section) -- or per (point, term) for the transient -- with a `monte_carlo` block,
`--backend batch` and `batch.capacity_wait_s` 600.  This script NEVER launches ngspice
over a grid itself and never falls back to a local grid if the fleet refuses; refusals are
recorded and the record says NOT-RUN.  `probe` runs SINGLE local points only.

Stages:  run --stage dc|tran|both | probe | record
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR / "temp-core-accuracy-mc"))
import evidence_store  # noqa: E402
import sim_common  # noqa: E402
import run_accuracy_mc as m  # noqa: E402

cr = sim_common.load_corner_run()
SLUG = "temp-core-chop-offset"
BUILD = REPO_ROOT / "sim" / "build" / SLUG
say = sim_common.say

VARIANT = m.CHOP_VARIANT
PHASES = ["a", "b"]
TERMS = ["nominal", "none", "amp"]  # amp = amplifier group live: input pair + mirror load + chopper switches
DEFAULT_N = 100
DEFAULT_SEED = 20261121
N_TRAN = 8
TRAN_PTS_DEFAULT = [("tt", 3.30, 27), ("ss", 3.63, -40)]  # tt/3.30 V + the #105 historical worst amp-term point
TRAN_TIMEOUT = 3000

DR007_RESIDUAL_MV = 0.05  # DR-007 item 1: residual input offset <= 0.05 mV (a sigma assumption there)
DR007_SENSITIVITY = 26.0  # DR-007: dPTAT/dVos = (R2+R2TRIM)/R1 V/V for this cell's PTAT path
CHI_LO, CHI_HI = 0.76, 1.43  # chi-square 95 % interval on a per-corner sigma at n = 100 (approximate)
# Pairing evidence threshold: if phases were drawn independently, the paired sd would be
# 1/sqrt(2) ~ 0.707 of the single-phase sd; a measured factor clearly below that evidences
# same-draw pairing + first-order cancellation.
PAIRING_FACTOR_LIMIT = 0.707


def dc_dir(run_dir, phase, term, proc=None):
    d = run_dir / "dc" / f"phase-{phase}" / term
    return d if proc is None else d / proc


def tran_tag(proc, supply, temp):
    return f"{proc}_{supply:.2f}v_{cr.fmt_temp(temp)}c"


def tran_dir(run_dir, proc, supply, temp, term):
    return run_dir / "tran" / tran_tag(proc, supply, temp) / term


def parse_tran_pt(s):
    proc, supply, temp = s.split(",")
    return (proc, float(supply), float(temp))


def build_tran_request(term, proc, supply, temp_c, n, seed, capacity_wait_s):
    tr = m.CHOP_TRAN_DEFAULT
    mm = term != "nominal"
    return sim_common.base_request(
        "netlist.spice", "batch",
        {"process": [f"{proc}_mm" if mm else proc], "supply_v": {"vsup": [supply]}, "temperature_c": [temp_c]},
        {"kind": "tran", "args": f"{tr['tmax_s']:.6g} {tr['tstop_s']:.6g} 0 {tr['tmax_s']:.6g} uic"},
        m.tran_measurements(tr),
        TRAN_TIMEOUT,
        capacity_wait_s=capacity_wait_s,
        waveforms=False,
        monte_carlo={"n": n, "seed": seed, "vary": "mismatch"} if mm else None,
    )


def cmd_run(args):
    evidence_store.preflight_or_exit()  # fail closed before anything is submitted
    git = cr.git_state()
    sim_common.refuse_unsubmittable(git, args.allow_dirty)
    run_id, run_dir, now = sim_common.open_run(BUILD, args.run_id, git["sha"], reuse="allow" if args.resume else None)
    this = {"stage": args.stage, "variant": VARIANT, "n": args.n, "seed": args.seed, "n_tran": args.n_tran,
            "capacity_wait_s": args.wait_for_capacity, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "klt_client": sim_common.klt_version(), "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"), "git": git}
    if args.resume and (run_dir / "run.json").is_file():
        meta = json.loads((run_dir / "run.json").read_text())
        meta.setdefault("resumes", []).append(this)
    else:
        meta = {"run_id": run_id, **this}
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")

    def usable(rp):
        try:
            return any(c.get("status") != "error" for c in json.loads(rp.read_text()).get("corners", []))
        except (OSError, json.JSONDecodeError):
            return False

    results = []

    def one_dc(unit):
        phase, term, proc = unit
        d = dc_dir(run_dir, phase, term, proc)
        if usable(d / "report.json"):
            return {"unit": f"dc/{phase}/{term}" + (f"/{proc}" if proc else ""), "skipped": "usable report exists"}
        seed = args.seed + (m.PROCS.index(proc) if proc else 0)
        req = m.build_request(term, "batch", args.n, seed, ([proc], m.SUPPLIES) if proc else None,
                              capacity_wait_s=args.wait_for_capacity)
        units = (1 if term == "nominal" else args.n) * len(m.SUPPLIES) * (1 if proc else len(m.PROCS))
        name = f"dc phase-{phase} {term}/{proc or 'all-proc'}"
        res = sim_common.submit_prepared(d, m.build_netlist(term, VARIANT, phase=phase), req,
                                         f"{name}: {units} ngspice units -> batch fleet", name)
        return {"unit": name, **res}

    def one_tran(unit):
        (proc, supply, temp), term = unit
        d = tran_dir(run_dir, proc, supply, temp, term)
        if usable(d / "report.json"):
            return {"unit": f"tran/{tran_tag(proc, supply, temp)}/{term}", "skipped": "usable report exists"}
        n = 1 if term == "nominal" else args.n_tran
        req = build_tran_request(term, proc, supply, temp, n, args.seed, args.wait_for_capacity)
        name = f"tran {tran_tag(proc, supply, temp)} {term}"
        res = sim_common.submit_prepared(d, m.build_netlist(term, VARIANT, tran=m.CHOP_TRAN_DEFAULT), req,
                                         f"{name}: {n} transient unit(s) -> batch fleet", name)
        return {"unit": name, **res}

    if args.stage in ("dc", "both"):
        dc_terms = args.term or TERMS
        units = [(ph, t, None if t == "nominal" else pr) for ph in PHASES for t in dc_terms for pr in ([None] if t == "nominal" else m.PROCS)]
        results += sim_common.fan_out(one_dc, units, args.jobs, label=lambda u: f"dc/{u[0]}/{u[1]}/{u[2] or 'all'}")
    if args.stage in ("tran", "both"):
        pts = [parse_tran_pt(s) for s in (args.tran_pt or [])] or TRAN_PTS_DEFAULT
        units = [(pt, t) for pt in pts for t in ("nominal", "amp")]
        results += sim_common.fan_out(one_tran, units, args.jobs, label=lambda u: f"tran/{tran_tag(*u[0])}/{u[1]}")
    meta.setdefault("submit_results", []).extend(results)
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def cmd_probe(args):
    """SINGLE-corner LOCAL probe (never a grid): one DC phase or one transient point, one process/supply."""
    run_dir = BUILD / args.run_id
    proc, supply, temp = parse_tran_pt(args.point)
    for term in args.term:
        if args.mode == "dc":
            d = run_dir / "probe" / f"phase-{args.phase}" / term
            d.mkdir(parents=True, exist_ok=True)
            (d / "netlist.spice").write_text(m.build_netlist(term, VARIANT, phase=args.phase))
            req = m.build_request(term, "local", args.n, args.seed, ([proc], [supply]))
        else:
            d = run_dir / "probe" / "tran" / tran_tag(proc, supply, temp) / term
            d.mkdir(parents=True, exist_ok=True)
            (d / "netlist.spice").write_text(m.build_netlist(term, VARIANT, tran=m.CHOP_TRAN_DEFAULT))
            req = build_tran_request(term, proc, supply, temp, args.n, args.seed, 0)
            req["backend"] = "local"
            req.pop("batch", None)
        (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
        say(f"[probe] local single corner {args.mode} {term} {proc} {supply} V"
            + (f" phase {args.phase}" if args.mode == "dc" else f" @ {temp:g} C") + f", n={args.n}")
        pr = sim_common.run_local_probe(d)
        say(f"[probe] exit {pr.returncode}")
    return 0


# ---------------------------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------------------------

def load_dc(run_dir):
    return {ph: {t: m.load_term(run_dir / "dc" / f"phase-{ph}", t) for t in TERMS} for ph in PHASES}


def _nominal_of(ent):
    """-> {(proc, supply): (value dict or None, guard reasons)}"""
    out = {}
    for key, samples in ent["corners"].items():
        v = samples.get(None)
        if v is None:
            out[key] = (None, ["nominal point missing"])
        else:
            why = m.guard_check(v)
            out[key] = (None, why) if why else (v, [])
    return out


def pair_phases(ents, nominal_ents):
    """Phase-pair the `amp` term against the variant's phase-averaged nominal.

    -> per-corner dict: n_total (union of sample ids), n_pairs, incomplete (sample ids with a
    missing phase), invalid ({sample, reasons per phase}), nominal_invalid (reasons per phase),
    pairs (sample -> averaged value dict), nom_avg (phase-averaged nominal or None).
    """
    res = {}
    ea, eb = ents["a"]["corners"], ents["b"]["corners"]
    noma, nomb = _nominal_of(nominal_ents["a"]), _nominal_of(nominal_ents["b"])
    for key in sorted(set(ea) | set(eb)):
        sa, sb = ea.get(key, {}), eb.get(key, {})
        (na, whya), (nb, whyb) = noma.get(key, (None, ["nominal point missing"])), nomb.get(key, (None, ["nominal point missing"]))
        sids = [s for s in sorted((set(sa) | set(sb)) - {None}) if s is not None]
        incomplete, invalid, pairs = [], [], {}
        for smp in sids:
            va, vb = sa.get(smp), sb.get(smp)
            if va is None or vb is None:
                incomplete.append(smp)
                continue
            why = {"a": m.guard_check(va), "b": m.guard_check(vb)}
            if why["a"] or why["b"]:
                invalid.append({"sample": smp, "reasons": {p: w for p, w in why.items() if w}})
                continue
            pairs[smp] = {f: 0.5 * (va[f] + vb[f]) for f in va if f in vb}
        res[key] = {"n_total": len(sids), "n_pairs": len(pairs), "incomplete": incomplete, "invalid": invalid,
                    "nominal_invalid": {"a": whya, "b": whyb},
                    "pairs": pairs,
                    "nom_avg": {f: 0.5 * (na[f] + nb[f]) for f in na} if na and nb else None}
    return res


def residual_mV(pairing, sens=DR007_SENSITIVITY):
    """Per-corner, per-temperature, per-sample input-referred residual (mV) of every valid pair."""
    out = {}
    for key, cs in pairing.items():
        nom = cs["nom_avg"]
        if nom is None or not cs["pairs"]:
            out[key] = None
            continue
        r = {t: {} for t in m.TEMPS}
        for smp, v in sorted(cs["pairs"].items()):
            for t in m.TEMPS:
                g = m.tagT(t)
                r[t][smp] = 1e3 * (v[f"ptat_{g}"] - nom[f"ptat_{g}"]) / sens
        out[key] = r
    return out


def single_phase_residual_mV(ents, nominal_ents, phase="a", sens=DR007_SENSITIVITY):
    """The unpaired (one chop phase) residual per corner/T -- the number chopping is supposed to
    cancel; its sd feeds the pairing-evidence cancellation factor."""
    e, nom_e = ents[phase]["corners"], _nominal_of(nominal_ents[phase])
    out = {}
    for key, samples in sorted(e.items()):
        nom, _nom_why = nom_e.get(key, (None, ["nominal point missing"]))
        if nom is None:
            continue
        vals = {t: [] for t in m.TEMPS}
        for smp, v in sorted(samples.items()):
            if smp is None or m.guard_check(v):
                continue
            for t in m.TEMPS:
                g = m.tagT(t)
                vals[t].append(1e3 * (v[f"ptat_{g}"] - nom[f"ptat_{g}"]) / sens)
        if any(vals.values()):
            out[key] = vals
    return out


def stat_mV(xs):
    n = len(xs)
    return {"n": n, "mean": statistics.fmean(xs) if n else float("nan"),
            "sd": statistics.stdev(xs) if n > 1 else float("nan"),
            "k3sd": 3 * statistics.stdev(xs) if n > 1 else float("nan"),
            "max_abs": max((abs(x) for x in xs), default=float("nan"))}


def _stat_from_dict(d):
    return stat_mV(list(d.values())) if d else None


def load_tran(run_dir):
    """-> {(proc, supply, temp): {'nominal': vals|None, 'samples': {sid: vals}, 'error': str|None}}"""
    out = {}
    if not (run_dir / "tran").is_dir():
        return out
    for d in sorted((run_dir / "tran").iterdir()):
        if not d.is_dir():
            continue
        proc, supply, temp = d.name.split("_")[0], float(d.name.split("_")[1].rstrip("v")), float(d.name.split("_")[2].rstrip("c").replace("m", "-"))
        pt = {"nominal": {"vals": None, "error": None}, "amp": {"samples": {}, "error": None}}
        rep_path = d / "nominal" / "report.json"
        try:
            rep = json.loads(rep_path.read_text())
            c = next((c for c in rep.get("corners", []) if c.get("status") != "error"), None)
            pt["nominal"]["vals"] = {mm["name"]: mm.get("value") for mm in c["measurements"]} if c else None
            pt["nominal"]["error"] = None if c else "no usable corner in report"
        except (OSError, json.JSONDecodeError, StopIteration) as err:
            pt["nominal"]["error"] = repr(err)
        rep_path = d / "amp" / "report.json"
        try:
            rep = json.loads(rep_path.read_text())
            for c in rep.get("corners", []):
                sid = m.parse_cid(c["corner_id"])[2]
                vals = {mm["name"]: mm.get("value") for mm in c["measurements"]}
                if c.get("status") == "error" or any(v is None for v in vals.values()):
                    pt["amp"]["samples"][sid] = {**vals, "_error": "unextractable"}
                else:
                    pt["amp"]["samples"][sid] = vals
        except (OSError, json.JSONDecodeError) as err:
            pt["amp"]["error"] = repr(err)
        out[(proc, supply, temp)] = pt
    return out


def tran_residual_mV(tran):
    """Per transient point: nominal ripple, per-sample input-referred cycle-average residual (mV, via the
    same sensitivity as the DC statistic) and ripple (mV output-referred)."""
    out = {}
    for pt, d in tran.items():
        nom = d["nominal"]["vals"]
        rows = []
        for sid, v in sorted(d["amp"]["samples"].items()):
            if "_error" in v or nom is None or nom.get("ptat_avg") is None:
                rows.append({"sample": sid, "valid": False, "reason": "unextractable" if "_error" in v else "no nominal transient"})
                continue
            rows.append({"sample": sid, "valid": True,
                         "resid_in_mV": 1e3 * (v["ptat_avg"] - nom["ptat_avg"]) / DR007_SENSITIVITY,
                         "ptat_pp_mV": 1e3 * v["ptat_pp"], "ctat_pp_mV": 1e3 * v["ctat_pp"],
                         "ctat_resid_mV": 1e3 * (v["ctat_avg"] - nom["ctat_avg"])})
        valid = [r for r in rows if r.get("valid")]
        out[pt] = {"nominal": nom, "rows": rows,
                   "nom_ptat_pp_mV": 1e3 * nom["ptat_pp"] if nom and nom.get("ptat_pp") is not None else None,
                   "nom_ctat_pp_mV": 1e3 * nom["ctat_pp"] if nom and nom.get("ctat_pp") is not None else None,
                   "resid_stats": stat_mV([r["resid_in_mV"] for r in valid]),
                   "ptat_pp_stats": stat_mV([r["ptat_pp_mV"] for r in valid]),
                   "ctat_pp_stats": stat_mV([r["ctat_pp_mV"] for r in valid])}
    return out


def f3(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def render_md(rec):
    rid = rec["record_id"]
    N = rec["n_per_corner"]
    L = [f"# Record {rid}", "",
         f"- **Record ID**: {rid}",
         f"- **Experiment**: `{SLUG}` -- chopped-amplifier residual input offset of the `{VARIANT}` temp_core deck (issue #461, part a of #456; measures the DR-007 item 1 assumption)",
         "- **Claim**: NOT a spec claim and no `spec/` or `design/` edit. Measures the residual input-referred offset of a chopped, degenerated-mirror `temp_core` amplifier under local mismatch, against DR-007 item 1's <= 0.05 mV design target (there a sigma assumption). A miss is a valid outcome; DR-007 is not edited.",
         f"- **Variant `{VARIANT}`** (a rewrite of the generated deck only): {m.VARIANT_DESC[VARIANT]}",
         f"- **Method -- static**: per mismatch sample, BOTH chop phases solved as DC temperature sweeps on the same physical draw (phase A/B decks differ only in the four chopper control literals; two klt requests sharing corners/seed/N re-draw the same devices per sample index -- klt derives the sample seed from the corner index, the property the #105 campaign's per-process-section split already relies on). Each phase guard-checked on its own (the #105 guard set); only complete, fully valid pairs averaged; the pair average vs the variant's own phase-averaged nominal at the same PVT; referred to the input through G = dPTAT/dVos = {DR007_SENSITIVITY:g} V/V (DR-007's (R2+R2TRIM)/R1 = {DR007_SENSITIVITY:g}; the chopper adds no device in the R1/R2 path, so the unchopped figure applies to the chopped deck too).",
         f"- **Method -- clocked**: real make-before-break chopping clock ({m.CHOP_TRAN_DEFAULT['period_s'] * 1e3:g} ms period = {1 / m.CHOP_TRAN_DEFAULT['period_s'] / 1e3:g} kHz, {m.CHOP_TRAN_DEFAULT['duty']:.2f} duty overlap so a chopper gate is never floating, {m.CHOP_TRAN_DEFAULT['rise_s'] * 1e6:g} us edges, control swing 0/{m.CHOP_VHI:g} V); settle {m.CHOP_TRAN_DEFAULT['settle_s'] * 1e3:g} ms ({round(m.CHOP_TRAN_DEFAULT['settle_s'] / m.CHOP_TRAN_DEFAULT['period_s'])} cycles), average over {m.CHOP_TRAN_DEFAULT['ncycles_avg']} integer cycles; PTAT/CTAT peak-to-peak ripple reported separately from the input-referred cycle-average residual; the residual is vs the no-mismatch transient at the same PVT, through the same G.",
         f"- **PVT + MC**: static: process tt/ss/ff/sf/fs (`_mm`) x 2.97/3.30/3.63 V = 15 corners, temperature swept -40..125 C in-process, evaluated at -40/27/125 C, `vary: mismatch`, **N = {N} per corner per phase** (200 draws per corner, paired), seed {rec['seed']} (phase A and B share it; process section k uses seed + k). Clocked: the small corner set below, **N = {rec['n_tran']}** samples per point.",
         "- **Statistical convention**: the residual is reported as sample mean (a systematic offset stays visible), sample sd (1 sigma -- the quantity DR-007's 0.05 mV assumption is about), 3 sigma and max |.|, input-referred, per corner and temperature.",
         *render_prov_lines(rec),
         f"- **Repo state**: run `{rec['git']['sha']}` (working tree clean at run time); graded at `{rec['graded_at_git']['sha']}` (working tree {'DIRTY' if rec['graded_at_git']['dirty'] else 'clean'})", ""]
    # headline
    L += ["## Headline: residual input-referred offset vs DR-007's 0.05 mV (static, two-phase DC)", ""]
    h = rec["headline_static"]
    if h:
        L += ["| statistic (input-referred mV) | worst corner | temperature | tt / 3.30 V |", "|---|---|---|---|",
              f"| mean (systematic) | {f3(h['worst_mean']['value'])} | {h['worst_mean']['T']} C | {f3(h['tt_mean'])} |",
              f"| **sample sd (1 sigma)** | **{f3(h['worst_sd']['value'])}** | {h['worst_sd']['T']} C | {f3(h['tt_sd'])} |",
              f"| 3 sigma | {f3(h['worst_k3sd']['value'])} | {h['worst_k3sd']['T']} C | {f3(h['tt_k3sd'])} |",
              f"| max abs | {f3(h['worst_max']['value'])} | {h['worst_max']['T']} C | {f3(h['tt_max'])} |", "",
              f"DR-007 item 1's design target is a residual input offset <= {DR007_RESIDUAL_MV} mV (used there as a sigma assumption). "
              f"Measured sample sd, worst corner/temperature: **{f3(h['worst_sd']['value'])} mV** -- "
              + ("WITHIN the assumption." if h['worst_sd']['value'] <= DR007_RESIDUAL_MV
                 else "EXCEEDS the assumption (a valid outcome; DR-007's amplifier projection would need re-derivation).")
              + f" Chi-square 95 % interval on a per-corner sd at n = {h['n_at_worst']}: about -{1 - CHI_LO:.0%} / +{CHI_HI - 1:.0%}.", ""]
    else:
        L += ["**NOT AVAILABLE**: no corner produced a valid phase pair; no static figure is claimed.", ""]
    # cancellation evidence
    L += ["## Pairing evidence (the same-draw assumption, checked from the data itself)", ""]
    ce = rec["cancellation"]
    if ce["rows"]:
        L += ["If the two phases were drawn INDEPENDENTLY, the paired sd would be 1/sqrt(2) ~ 0.707 of the single-phase sd. "
              "Measured paired/single-phase sd ratio (worst temperature per corner):", "",
              "| corner | single-phase sd (mV) | paired sd (mV) | ratio |", "|---|---|---|---|"]
        for r in ce["rows"]:
            L.append(f"| {r['corner']} | {f3(r['single_sd'])} | {f3(r['paired_sd'])} | {f3(r['ratio'])} |")
        L += ["", f"Worst ratio **{f3(ce['worst_ratio'])}** (limit {PAIRING_FACTOR_LIMIT:.3f}): "
              + ("clearly below the independent-draw value, so the phases carry the same draw and the first-order offset cancels."
                 if ce["worst_ratio"] is not None and ce["worst_ratio"] < PAIRING_FACTOR_LIMIT
                 else "NOT below the independent-draw value -- the same-draw pairing assumption is NOT supported by this run; treat the headline as pairing-limited."), ""]
    else:
        L += ["NOT AVAILABLE (no corner with both single-phase and paired statistics).", ""]
    # per corner
    L += ["## Static residual per corner (input-referred mV, sample sd; each row = worst of -40/27/125 C)", "",
          "| corner | n pairs / total | incomplete pairs | invalid pairs | sd (worst T) | mean (worst T) | max abs |", "|---|---|---|---|---|---|---|"]
    for key in sorted(rec["per_corner"]):
        row = rec["per_corner"][key]
        L.append(f"| {key} | {row['n_pairs']} / {row['n_total']} | {row['n_incomplete']} | {row['n_invalid']} | "
                 f"{f3(row['worst_sd'])} ({row['worst_sd_T']} C) | {f3(row['worst_mean'])} ({row['worst_mean_T']} C) | {f3(row['worst_max'])} |")
    nb = rec["nominal_bad_corners"]
    L += ["", "Corners whose NOMINAL reference failed a guard in either phase (all their pairs excluded): " + (", ".join(nb) or "none") + ".", "",
          "Per-temperature detail, every valid pair and both phases' raw values are in the stored `samples-dc.csv`; the json twin carries the per-corner statistics.", ""]
    # controls
    L += ["## Controls", ""]
    for ph in PHASES:
        L.append(m.compare_control_line(f"chop-degen phase-{ph} (DC deck)", rec["none_control"][ph]))
    L += [f"- Phase-pair completeness: {sum(r['n_incomplete'] for r in rec['per_corner'].values())} incomplete pair(s) over all corners "
          "(a sample with only one phase solved is counted invalid, never substituted); "
          f"{sum(r['n_invalid'] for r in rec['per_corner'].values())} pair(s) excluded by operating-point guards.",
          f"- Liveness `amp` (chopper switches + input pair + mirror load live): see the single-phase column of the pairing table -- "
          "the unpaired offset this experiment exists to cancel.", ""]
    # transient
    L += ["## Clocked-transient check (charge injection, clock feedthrough, ripple)", ""]
    tr = rec["transient"]
    if tr:
        L += ["| point | n valid | input-referred cycle-avg residual: mean / sd (mV) | PTAT ripple pp (mV): nominal / worst sample | CTAT ripple pp (mV): nominal / worst sample |", "|---|---|---|---|---|"]
        for pt, r in sorted(tr.items()):
            label = pt if isinstance(pt, str) else f"{pt[0]} / {pt[1]:.2f} V / {pt[2]:g} C"
            L.append(f"| {label} | {r['resid_stats']['n']} | {f3(r['resid_stats']['mean'])} / {f3(r['resid_stats']['sd'])} | "
                     f"{f3(r['nom_ptat_pp_mV'])} / {f3(r['ptat_pp_stats']['max_abs'])} | {f3(r['nom_ctat_pp_mV'])} / {f3(r['ctat_pp_stats']['max_abs'])} |")
        L += [""]
        worst_dc, worst_tran = rec["comparison"]["worst_static_sd_mV"], rec["comparison"]["worst_transient_sd_mV"]
        if worst_dc is not None or worst_tran is not None:
            bigger = "transient" if (worst_tran or 0) > (worst_dc or 0) else "static two-phase DC"
            L += [f"Same statistic and units on both legs (input-referred sample sd vs the no-mismatch reference at the same PVT): "
                  f"static {f3(worst_dc)} mV, transient {f3(worst_tran)} mV -> the reported residual is the larger, the **{bigger}** figure.", ""]
    else:
        L += ["**NOT AVAILABLE** (no transient point produced usable results); only the static figure is claimed.", ""]
    # fleet / not run
    if rec["not_run_units"]:
        L += [f"**PARTIAL: units NOT-RUN (fleet refusal/timeout): {', '.join(rec['not_run'])}.** Nothing was substituted by a local grid.", ""]
    # limits
    L += ["## Not measured / limits of this record", "",
          f"- **Sensitivity G**: referred through DR-007's dPTAT/dVos = {DR007_SENSITIVITY:g} V/V ((R2+R2TRIM)/R1), not re-extracted from this deck; the chopper adds no device in the R1/R2 path, but any error in that figure scales every input-referred number here linearly.",
          "- **Same-draw pairing**: the two-phase cancellation assumes klt's per-sample draw is a function of (seed, corner index, sample index) and the deck's device list, not of the deck's control-source literals. The measured cancellation ratio above is the empirical check; a broken pairing would read ~0.707 there.",
          "- **Switch model**: pass gates are sky130 g5v0d10v5 L=0.5 W=2 nfet+pfet halves; the pfet half is near threshold at the 0.6-0.9 V signal swing (control hi 2.5 V, lo 0 V). Charge injection and clock feedthrough are only as good as the compact model's transient behaviour of those devices; no layout parasitics, no clock wiring capacitance, and the clock is an ideal source, not a real clock generator.",
          "- **Auto-zero alternative not built**: DR-007 allows chop OR auto-zero; only the chopper is measured here.",
          f"- **Clocked coverage**: {len(tr)} corner point(s) at N = {rec['n_tran']}; the static figure covers the full 15-corner grid. The transient's mismatch draws are NOT the DC run's draws (different corner-axis shape); its reference is the no-mismatch transient at the same PVT, the same statistic in the same units.",
          f"- **Statistical resolution**: N = {N} pairs per corner (chi-square 95 % interval on a per-corner sd about -{1 - CHI_LO:.0%} / +{CHI_HI - 1:.0%}); N = {rec['n_tran']} transient samples per point.",
          "- **Everything the #105 campaign does not measure** (global process MC, systematic/gradient mismatch, trim ladder, readout chain) is unmeasured here too; the ripple reported must be filtered by whatever reads PTAT/CTAT downstream (not this experiment's business).",
          "- **klt capability gaps**: none hit -- the two-phase solve is two ordinary `klt sim` requests differing only in netlist literals, and the clocked check is a `tran` analysis with a PULSE-driven deck and a `monte_carlo` block (the same shape `sim/por-comparator-thresholds/` already submits); no gap to file at 2AMLogic/klayout-tools for this experiment.", ""]
    L += ["## Links", "",
          f"- driver `sim/{SLUG}/run_chop_offset.py`; variant + deck builder `sim/temp-core-accuracy-mc/run_accuracy_mc.py` (`--variant {VARIANT}`, `--phase`); json twin `records/{rid}.json`; decks and requests `netlist-snapshots/{rid}/`",
          f"- per-pair DC samples (`samples-dc.csv`) and transient rows (`samples-tran.csv`) are in the fleet artifact store: manifest `{rec['links']['artifact_manifest']}`, summary `{rec['links']['artifact_summary']}` (check with `klt artifact verify {rec['links']['artifact_manifest']}')" if rec["links"]["artifact_manifest"] else "- no staged samples (nothing was graded), so this record has no artifact manifest",
          "- DR-007 `spec/decision-records/DR-007-temp-core-accuracy-recommendation.md` (item 1, untouched); baseline record `sim/temp-core-accuracy-mc/records/20261011-165907-69d13ac.md`; mirror rewrite record `sim/temp-core-accuracy-mc/records/20261107-235128-679442ca.md`",
          f"- **Run id**: `{rec['run_id']}` (seed {rec['seed']}, N = {N}/corner/phase) -- #462's all-terms campaign reuses this variant and seed",
          f"- **Timestamp**: {rec['timestamp']}", f"- **Author**: {rec['author']}", "- **Supersedes**: (none)"]
    return "\n".join(L)


def render_prov_lines(rec):
    prov = rec["provenance"]
    jobs = ", ".join(f"{u}={j.get('job_id')}" for u, j in sorted(rec["fleet_jobs"].items()) if j.get("job_id"))
    return [f"- **PDK**: {rec['pdk']['variant']} @ open_pdks `{rec['pdk']['installed_commit']}` ({sim_common.pin_state(rec['pdk']['matches_pin'])}) on the host that wrote this record"
            + "; fleet side: " + sim_common.fleet_pdk_sentence(prov, "this record has no evidence on the runner's model library itself", mid_sentence=True),
            f"- **Tools**: {rec['klt']} (client); backend `{rec['backend']}`; fleet engine {prov['fleet_engine']}; fleet jobs: {jobs or 'none usable'}"]


def cmd_record(args):
    evidence_store.preflight_or_exit()
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    last = meta.get("resumes", [None])[-1] or meta
    git = last["git"]
    if git.get("dirty") and not args.allow_dirty:
        sys.exit("the run was made from a DIRTY tree: this record would not be provenance-clean")
    grade_git = cr.git_state()
    if grade_git.get("dirty") and not args.allow_dirty:
        sys.exit("the grading tree is DIRTY: commit the analysis code first so the record is provenance-clean")
    pdk = cr.resolve_pdk(cr.load_pin())
    now = datetime.now(timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{git['sha']}"
    rec_dir = SIM_DIR / SLUG
    sim_common.refuse_existing((rec_dir / "records" / f"{rid}.md", rec_dir / "records" / f"{rid}.json",
                                rec_dir / "netlist-snapshots" / rid,
                                evidence_store.stage_dir_for(SLUG, rid), evidence_store.manifest_path(SLUG, rid)))
    ents = load_dc(run_dir)
    # --- grading: phase-paired residual
    pairing = pair_phases({ph: ents[ph]["amp"] for ph in PHASES}, {ph: ents[ph]["nominal"] for ph in PHASES})
    resid = residual_mV(pairing)
    single = single_phase_residual_mV({ph: ents[ph]["amp"] for ph in PHASES}, {ph: ents[ph]["nominal"] for ph in PHASES})
    per_corner, canc_rows = {}, []
    for key, cs in pairing.items():
        r = resid.get(key)
        row = {"n_total": cs["n_total"], "n_pairs": cs["n_pairs"], "n_incomplete": len(cs["incomplete"]),
               "n_invalid": len(cs["invalid"]),
               "nominal_invalid": {p: v for p, v in cs["nominal_invalid"].items() if v}}
        sts = {t: _stat_from_dict(r[t]) for t in m.TEMPS} if r else {}
        sts = {t: s for t, s in sts.items() if s}
        if sts:
            ws = max(sts, key=lambda t: sts[t]["sd"])
            wm = max(sts, key=lambda t: abs(sts[t]["mean"]))
            wk = max(sts, key=lambda t: sts[t]["max_abs"])
            row.update({"worst_sd": sts[ws]["sd"], "worst_sd_T": ws, "worst_mean": sts[wm]["mean"], "worst_mean_T": wm,
                        "worst_max": sts[wk]["max_abs"], "worst_max_T": wk,
                        "stats": {str(t): s for t, s in sts.items()}})
        else:
            row.update({"worst_sd": None, "worst_sd_T": None, "worst_mean": None, "worst_mean_T": None,
                        "worst_max": None, "worst_max_T": None, "stats": {}})
        per_corner[key] = row
        s = single.get(key)
        if s and sts:
            ssd = max((stat_mV(xs)["sd"] for xs in s.values() if xs), default=float("nan"))
            psd = row["worst_sd"]
            if not math.isnan(ssd) and ssd > 0 and psd is not None and not math.isnan(psd):
                canc_rows.append({"corner": f"{key[0]}_{key[1]:.2f}V", "single_sd": ssd, "paired_sd": psd, "ratio": psd / ssd})
    ratios = [c["ratio"] for c in canc_rows]
    cancellation = {"rows": sorted(canc_rows, key=lambda c: c["corner"]),
                    "worst_ratio": max(ratios) if ratios else None}
    keys_with = [k for k in per_corner if per_corner[k]["worst_sd"] is not None]
    headline = None
    if keys_with:
        wk_sd = max(keys_with, key=lambda k: per_corner[k]["worst_sd"])
        wk_mean = max(keys_with, key=lambda k: abs(per_corner[k]["worst_mean"]))
        wk_max = max(keys_with, key=lambda k: per_corner[k]["worst_max"])

        def tt_stat(k, f):
            s = per_corner[k]["stats"].get("27")
            return s[f] if s else None
        headline = {"worst_sd": {"corner": f"{wk_sd[0]}_{wk_sd[1]:.2f}V", "value": per_corner[wk_sd]["worst_sd"], "T": per_corner[wk_sd]["worst_sd_T"]},
                    "worst_mean": {"corner": f"{wk_mean[0]}_{wk_mean[1]:.2f}V", "value": per_corner[wk_mean]["worst_mean"], "T": per_corner[wk_mean]["worst_mean_T"]},
                    "worst_k3sd": {"corner": f"{wk_sd[0]}_{wk_sd[1]:.2f}V", "value": 3 * per_corner[wk_sd]["worst_sd"], "T": per_corner[wk_sd]["worst_sd_T"]},
                    "worst_max": {"corner": f"{wk_max[0]}_{wk_max[1]:.2f}V", "value": per_corner[wk_max]["worst_max"], "T": per_corner[wk_max]["worst_max_T"]},
                    "tt_sd": tt_stat(("tt", 3.3), "sd"), "tt_mean": tt_stat(("tt", 3.3), "mean"),
                    "tt_k3sd": 3 * tt_stat(("tt", 3.3), "sd") if tt_stat(("tt", 3.3), "sd") is not None else None,
                    "tt_max": tt_stat(("tt", 3.3), "max_abs"), "n_at_worst": per_corner[wk_sd]["n_pairs"]}
    nominal_bad = sorted({f"{k[0]}_{k[1]:.2f}V" for k, r in per_corner.items() if r["nominal_invalid"]})
    # --- controls, transient, provenance
    ctrl = {}
    for ph in PHASES:
        a_none = m.analyse_term(ents[ph]["none"], ents[ph]["nominal"]) if ents[ph]["none"]["report"] and ents[ph]["nominal"]["report"] else None
        ctrl[ph] = m.none_control(a_none) if a_none else None
    tran = tran_residual_mV(load_tran(run_dir))
    flat_ents = {f"{ph}/{t}": ents[ph][t] for ph in PHASES for t in TERMS}
    prov = m.observed_provenance(flat_ents, pdk.pin)
    fleet_jobs = {f"{ph}/{t}/{pr or 'all'}": env for ph in PHASES for t in TERMS
                  for pr, env in ((ents[ph][t].get("jobs") or {}).items())}
    not_run = [f"{ph}/{t}" for ph in PHASES for t in TERMS if ents[ph][t]["report"] is None]
    # --- stage csvs + snapshots, then store
    snap, cdir = rec_dir / "netlist-snapshots" / rid, evidence_store.stage_dir_for(SLUG, rid)
    (rec_dir / "records").mkdir(exist_ok=True)
    snap.mkdir(parents=True)
    cdir.mkdir(parents=True)
    for ph in PHASES:
        for t in TERMS:
            for pr, d in ([(None, run_dir / "dc" / f"phase-{ph}" / t)] if t == "nominal"
                          else [(p, run_dir / "dc" / f"phase-{ph}" / t / p) for p in m.PROCS]):
                if (d / "netlist.spice").is_file():
                    tag = t if pr is None else f"{t}.{pr}"
                    (snap / f"phase-{ph}-{tag}.spice").write_text(sim_common.scrub((d / "netlist.spice").read_text(), run_dir, REPO_ROOT))
                    (snap / f"phase-{ph}-{tag}.request.json").write_text(sim_common.scrub((d / "request.json").read_text(), run_dir, REPO_ROOT))
    if (run_dir / "tran").is_dir():
        for d in sorted((run_dir / "tran").iterdir()):
            for t in ("nominal", "amp"):
                if (d / t / "netlist.spice").is_file():
                    (snap / f"tran-{d.name}-{t}.spice").write_text(sim_common.scrub((d / t / "netlist.spice").read_text(), run_dir, REPO_ROOT))
                    (snap / f"tran-{d.name}-{t}.request.json").write_text(sim_common.scrub((d / t / "request.json").read_text(), run_dir, REPO_ROOT))
    write_dc_csv(cdir / "samples-dc.csv", pairing, resid)
    write_tran_csv(cdir / "samples-tran.csv", tran)
    art_manifest, art_summary = evidence_store.store_or_exit(SLUG, rid, cdir)
    comparison = {"worst_static_sd_mV": headline["worst_sd"]["value"] if headline else None,
                  "worst_transient_sd_mV": max((r["resid_stats"]["sd"] for r in tran.values()
                                                if not math.isnan(r["resid_stats"]["sd"])), default=None)}
    rec = {"record_id": rid, "experiment": SLUG, "issue": 461, "variant": VARIANT,
           "links": {"record": f"sim/{SLUG}/records/{rid}.md", "json": f"sim/{SLUG}/records/{rid}.json",
                     "driver": f"sim/{SLUG}/run_chop_offset.py", "deck_builder": "sim/temp-core-accuracy-mc/run_accuracy_mc.py",
                     "netlist_snapshots": f"sim/{SLUG}/netlist-snapshots/{rid}/",
                     "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)),
                     "artifact_summary": str(art_summary.relative_to(REPO_ROOT))},
           "variant_description": m.VARIANT_DESC[VARIANT], "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "run_id": args.run_id, "git": git, "graded_at_git": grade_git, "klt": last.get("klt_client"),
           "backend": last.get("klt_sim_backend_env"), "n_per_corner": meta.get("n", DEFAULT_N),
           "seed": meta.get("seed", DEFAULT_SEED), "n_tran": meta.get("n_tran", N_TRAN),
           "sensitivity_v_per_v": DR007_SENSITIVITY, "dr007_residual_mV": DR007_RESIDUAL_MV,
           "headline_static": headline, "cancellation": cancellation,
           "per_corner": {f"{k[0]}_{k[1]:.2f}V": {kk: vv for kk, vv in v.items() if kk != "nominal_invalid"} | {"nominal_invalid": v["nominal_invalid"]}
                          for k, v in per_corner.items()},
           "nominal_bad_corners": nominal_bad, "none_control": ctrl, "transient": {f"{p[0]}_{p[1]:.2f}V_{p[2]:g}C": v for p, v in tran.items()},
           "comparison": comparison, "provenance": prov,
           "fleet_jobs": {u: {k: j.get(k) for k in ("job_id", "instance_type", "lifecycle", "state", "elapsed_seconds")} for u, j in fleet_jobs.items()},
           "not_run_units": not_run, "resumes": meta.get("resumes", []),
           "pdk": {"variant": pdk.variant, "installed_commit": pdk.installed_commit, "matches_pin": pdk.matches_pin, "pin": pdk.pin},
           "author": cr.default_author()}
    (rec_dir / "records" / f"{rid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    (rec_dir / "records" / f"{rid}.md").write_text(render_md(rec) + "\n")
    print(rid)
    return 0


def write_dc_csv(path, pairing, resid):
    cols = []
    for t in m.TEMPS:
        g = m.tagT(t)
        cols += [f"ptat_avg_{g}", f"ctat_avg_{g}", f"resid_in_mV_{g}"]
    lines = ["corner,sample,valid,reason," + ",".join(cols)]
    for key, cs in sorted(pairing.items()):
        r = resid.get(key) or {}
        inv = {i["sample"]: ";".join(f"phase {p}: {'; '.join(w)}" for p, w in i["reasons"].items()) for i in cs["invalid"]}
        sids = sorted(set(cs["pairs"]) | set(cs["incomplete"]) | set(inv), key=lambda s: (s is None, s))
        for smp in sids:
            v = cs["pairs"].get(smp)
            if smp in cs["incomplete"]:
                ok, why = 0, "incomplete pair (other phase missing)"
            elif smp in inv:
                ok, why = 0, inv[smp]
            else:
                ok, why = 1, ""
            row = [f"{key[0]}_{key[1]:.2f}V", str(smp), str(ok), why.replace(",", ";")]
            for t in m.TEMPS:
                g = m.tagT(t)
                if v:
                    rv = r.get(t, {}).get(smp)
                    row += [f"{v[f'ptat_{g}']:.7g}", f"{v[f'ctat_{g}']:.7g}", "" if rv is None else f"{rv:.6g}"]
                else:
                    row += ["", "", ""]
            lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n")


def write_tran_csv(path, tran):
    lines = ["point,sample,valid,resid_in_mV,ptat_pp_mV,ctat_pp_mV,ctat_resid_mV"]
    for pt, r in sorted(tran.items()):
        for row in r["rows"]:
            lines.append(",".join([f"{pt[0]}_{pt[1]:.2f}V_{pt[2]:g}C", str(row["sample"]), str(int(bool(row.get("valid")))),
                                   "" if not row.get("valid") else f"{row['resid_in_mV']:.6g}",
                                   "" if not row.get("valid") else f"{row['ptat_pp_mV']:.6g}",
                                   "" if not row.get("valid") else f"{row['ctat_pp_mV']:.6g}",
                                   "" if not row.get("valid") else f"{row['ctat_resid_mV']:.6g}"]))
    path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--run-id")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--stage", choices=["dc", "tran", "both"], default="both")
    r.add_argument("--tran-pt", action="append", default=None, metavar="PROC,SUPPLY,TEMP",
                   help="transient corner point (repeatable); default tt,3.30,27 and ss,3.63,-40")
    r.add_argument("--term", action="append", choices=TERMS)
    r.add_argument("--n", type=int, default=DEFAULT_N)
    r.add_argument("--n-tran", type=int, default=N_TRAN)
    r.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r.add_argument("--jobs", type=int, default=2)
    r.add_argument("--allow-dirty", action="store_true")
    sim_common.add_capacity_wait_arg(r)
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("probe")
    p.add_argument("--run-id", required=True)
    p.add_argument("--term", action="append", required=True, choices=TERMS)
    p.add_argument("--mode", choices=["dc", "tran"], default="dc")
    p.add_argument("--phase", choices=PHASES, default="a")
    p.add_argument("--point", default="tt,3.30,27")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.set_defaults(fn=cmd_probe)
    rc = sub.add_parser("record")
    rc.add_argument("--run-id", required=True)
    rc.add_argument("--allow-dirty", action="store_true")
    rc.set_defaults(fn=cmd_record)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
