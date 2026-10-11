#!/usr/bin/env python3
"""Glitch waveform checker for the assembled temp_por_top (issue #117).

Pure standard library.  Two structurally distinct glitch classes are graded
SEPARATELY (spec/porting-plan.md Sec3.5; the deglitch dwell can only filter a
disturbance presented at POR_RAW, it cannot reject one injected at VDD):

``por_raw_inject``  class A.  The supply is a clean power-up ramp.  A finite-
                    impedance pulse is injected into the POR_RAW node by an
                    INSTRUMENT element spliced into the DUT netlist (see
                    run_glitch_campaign.build_netlist).  Instrumented assembly
                    evidence -- NOT as-drawn evidence.
``vdd_level``       class B.  The DUT netlist is unmodified; the supply source
                    makes one symmetric-edge dip (sf = sr).

Every number below is an EXPLORATORY measurement definition (experiment.json
``grading``); none is a ratified bound and none is a gf180mcu figure
(CLAUDE.md: thresholds do not port).

Verdicts (precedence, highest first), shared by both classes
ERROR        required channel missing / non-finite / no waveform, or the
             deck that was simulated is not the declared one (attribution).
NONPHYSICAL  a saved node outside [-0.3, vf+0.5] V after t=0, settled supply
             current not positive, or delivered bias branch of wrong sign.
UNRESOLVED   baseline not viable (RESETn released exactly once and settled
             high, POR_RAW high, delivered bias settled), or no failure was
             detected but the evidence is insufficient (sample gap too coarse
             for the requested width/edge, stimulus not as declared, window
             truncated, or -- class A -- the injection never took POR_RAW below
             V_MID so the dwell was not exercised).
FAIL         a resolved physical failure; the codes say which.
PASS         none of the above.

Expectation per stimulus (what the point *calls for*; stated, not ratified)
  class A: from the full-resolution POR_RAW dwell below V_MID
      dwell <  D_REJ (50 us)   -> ``rejection``         RESETn must stay above V_IL
      dwell >= D_REQ (1 ms)    -> ``assertion_required``  RESETn must assert, then release
      otherwise                -> ``assertion_optional``   assert or not; an assertion must release
      no injection (control)   -> ``no_glitch``          RESETn must not assert
  class B: from the full-resolution VDD dwell below V_MUST = 0.5 vf
      dwell >= T_REQ (50 us)   -> ``assertion_required``
      otherwise                -> ``assertion_optional`` (rejection by the dwell is recorded as
                                  ``dwell_rejection_visible`` when POR_RAW fell but RESETn did not)
      VDD below V_IL at the floor -> ``rail_collapse`` is also recorded (the rail itself cannot
                                  hold state; no immunity is claimed there)

Failure codes
  unwanted_assertion        (A) rejection-class glitch yet RESETn fell below V_IL.
  missed_assertion          assertion required, RESETn never fell below V_IL.
  no_recovery               RESETn asserted, no release in the complete window.
  premature_release         POR_RAW fell through V_MID and RESETn released with no
                            POR_RAW rise in between (a spurious release).
  reassert_chatter          two or more RESETn assertions for one glitch.
  reassert_after_recovery   (B) an assertion starts after VDD has recovered.
  not_high_at_end           RESETn not >= V_IH over the last SETTLE_WINDOW.
  bias_not_recovered        delivered bias at the end outside BIAS_BAND x baseline.
  spurious_assertion_control  (control only) RESETn fell below V_IL.

Delivered bias: +id of bias_core XMPIB (PMOS whose drain IS the IBIAS node), the
same explicit branch as sim/brownout-top.  BSIM4 reports id positive for normal
conduction in both polarities, so the delivered current is +id and a non-positive
baseline value is NONPHYSICAL.  The IBIAS NODE voltage is recorded separately and
never used as a current.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "bin"))
sys.path.insert(0, str(HERE.parent / "brownout-top"))
import brownout_checker as bc  # noqa: E402  (primitives + class-B grading core; stimulus twin of the SPICE BVDD)
from sim_common import load_wave  # noqa: E402,F401

schmitt, crossings, dwell_below, interp_at, _mean = bc.schmitt, bc.crossings, bc.dwell_below, bc.interp_at, bc._mean
FRAC_IL, FRAC_IH, FRAC_MID, FRAC_MUST = bc.FRAC_IL, bc.FRAC_IH, bc.FRAC_MID, bc.FRAC_MUST
T_REQ = bc.T_REQ
BASE_WIN, SETTLE_WINDOW, BASE_BIAS_RIPPLE, BIAS_BAND = bc.BASE_WIN, bc.SETTLE_WINDOW, bc.BASE_BIAS_RIPPLE, bc.BIAS_BAND
MAX_DT_CAP, VDD_TOL, PHYS_LO, PHYS_HI_MARGIN = bc.MAX_DT_CAP, bc.VDD_TOL, bc.PHYS_LO, bc.PHYS_HI_MARGIN
I_DELIVERED, I_SINKS, PHYS_NODES = bc.I_DELIVERED, bc.I_SINKS, bc.PHYS_NODES

D_REJ = 50e-6  # s: POR_RAW dwell below V_MID under which a class-A pulse calls for REJECTION
D_REQ = 1e-3  # s: POR_RAW dwell below V_MID at/above which a class-A pulse calls for ASSERTION
G_TOL = 0.02  # tolerance of the sampled injection drive GINJ against the declared trapezoid (0..1)
EDGE_DIV = 8.0  # class A: the checker's sample-gap limit is <= edge/EDGE_DIV
WIDTH_DIV_GAP = 5.0  # class A: sample-gap limit <= width/5
TMAX_EDGE_DIV = 10.0  # class A: the simulator step bound tmax <= edge/10 (strictly tighter than the gap limit: a step AT the limit would be rejected)
TMAX_WIDTH_DIV = 10.0  # class A: tmax <= width/10
GAP_RTOL = 1e-3  # relative float tolerance on the gap comparison (step sizes are rounded by the simulator)

V_GINJ = "v(ginj)"
I_INJ = "i(@r.xdut.rinj[i])"  # current through RINJ (A); ngspice sign: positive = INJD -> POR_RAW, so a pull-down injection reads NEGATIVE (verified in a local probe); only the magnitude is graded
CORE_A = bc.CORE + (V_GINJ,)
CORE_B = bc.CORE

CLASS_A, CLASS_B = "por_raw_inject", "vdd_level"


# --------------------------------------------------------------------------
# class A stimulus: trapezoid drive g(t)
# --------------------------------------------------------------------------


def timeline_a(st: dict) -> dict:
    """``st``: t0, te (edge), tw (flat width), gen (0 = no-injection control)."""
    te = max(st["te"], 1e-9)
    t1 = st["t0"] + te
    t2 = t1 + st["tw"]
    t3 = t2 + te
    return {"t_rise_end": t1, "t_fall_start": t2, "t_end": t3, "control": not st.get("gen", 1), "fwhm": st["tw"] + te}


def _clip01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def g_expected(t: float, st: dict) -> float:
    """SPICE twin: gen*(clip01((t-t0)/te) - clip01((t-t0-te-tw)/te)) -- the BGINJ source in the testbench."""
    te = max(st["te"], 1e-9)
    return st.get("gen", 1) * (_clip01((t - st["t0"]) / te) - _clip01((t - st["t0"] - te - st["tw"]) / te))


def vdd_expected_a(t: float, vf: float, st: dict) -> float:
    return min(vf, st["rup"] * t)


def tstop_a(st: dict, t_obs: float) -> float:
    return timeline_a(st)["t_end"] + t_obs


def tmax_a(st: dict, th_cap: float = 10e-6) -> float:
    return min(th_cap, st["tw"] / TMAX_WIDTH_DIV, max(st["te"], 1e-9) / TMAX_EDGE_DIV)


def required_max_dt_a(st: dict) -> float:
    if timeline_a(st)["control"]:
        return MAX_DT_CAP
    return min(MAX_DT_CAP, st["tw"] / WIDTH_DIV_GAP, max(st["te"], 1e-9) / EDGE_DIV)


# class B stimulus is brownout's with sf = sr.  ``st`` keys: rup t0 vlow th sf (sr is forced = sf)
def b_stim(st: dict) -> dict:
    d = dict(st)
    d["sr"] = d["sf"]
    return d


def tstop_b(vf: float, st: dict, t_obs: float) -> float:
    return bc.tstop_for(vf, b_stim(st), t_obs)


def tmax_b(st: dict, vf_min: float, th_cap: float = 10e-6) -> float:
    """Brown-out step bound (<= 10 us, <= hold/6, <= edge/12 at the smallest starting supply) with sf = sr."""
    return bc.tmax_for(b_stim(st), vf_min, th_cap)


def required_max_dt_b(vf: float, st: dict) -> float:
    """Brown-out sample-gap rule (<= 20 us, <= hold/5, <= edge/10); the glitch holds here are 20-200 us."""
    return bc.required_max_dt(vf, b_stim(st))


# --------------------------------------------------------------------------
# class A analysis
# --------------------------------------------------------------------------


def _err(detail, **extra):
    return {"verdict": "ERROR", "fail_codes": [], "unresolved_reasons": [], "detail": detail, **extra}


def expectation_a(dwell_mid: float, control: bool) -> str:
    if control:
        return "no_glitch"
    if dwell_mid < D_REJ:
        return "rejection"
    if dwell_mid >= D_REQ:
        return "assertion_required"
    return "assertion_optional"


def analyze_a(w, vf: float, st: dict, t_obs: float) -> dict:
    """Grade one POR_RAW-injection point (class A).  ``w`` None / missing channel -> ERROR."""
    if w is None:
        return _err("no waveform retrieved")
    tl = timeline_a(st)
    control = tl["control"]
    need = CORE_A + (() if control else (I_INJ,))
    missing = [n for n in need if n not in w]
    if missing:
        return _err(f"waveform lacks {missing}")
    t = w["time"]
    n = len(t)
    if n < 3 or any(not math.isfinite(x) for name in need for x in w[name]):
        return _err("too few or non-finite samples")
    if any(t[i + 1] <= t[i] for i in range(n - 1)):
        return _err("time axis not strictly increasing")

    vdd, rst, raw, ib, gin = w["v(vdd)"], w["v(resetn)"], w["v(xdut.por_raw)"], w["v(xdut.ibias)"], w[V_GINJ]
    idel = list(w[I_DELIVERED])
    t0 = st["t0"]
    v_il, v_ih, v_mid = FRAC_IL * vf, FRAC_IH * vf, FRAC_MID * vf
    need_end = tl["t_end"] + t_obs
    truncated = t[-1] < need_end * (1 - 1e-6)

    # --- physicality ---
    hi = vf + PHYS_HI_MARGIN
    viol = {}
    for name in PHYS_NODES:
        col = w.get(name)
        if col is None:
            continue
        badi = [i for i in range(n) if t[i] > 0 and not (PHYS_LO <= col[i] <= hi)]
        if badi:
            bad = [col[i] for i in badi]
            viol[name] = {"count": len(bad), "min": min(bad), "max": max(bad), "t_first_s": t[badi[0]]}
    last = [i for i in range(n) if t[i] >= t[-1] - SETTLE_WINDOW]
    isup_end = _mean([-w["i(bvdd)"][i] for i in last])
    base_i = [i for i in range(n) if t0 - BASE_WIN <= t[i] <= t0]
    ibase = _mean([idel[i] for i in base_i]) if base_i else float("nan")
    sign_ok = (not base_i) or (math.isfinite(ibase) and ibase > 0.0)
    physical = (not viol) and math.isfinite(isup_end) and isup_end > 0.0 and sign_ok
    onset = min([v["t_first_s"] for v in viol.values()], default=None)
    isup_base = _mean([-w["i(bvdd)"][i] for i in base_i]) if base_i else None
    phys = {"ok": physical, "isup_end_a": isup_end, "isup_baseline_a": isup_base, "violations_after_t0": viol, "delivered_bias_sign_ok": sign_ok,
            "node_violation_onset_s": onset, "node_violation_phase": (None if onset is None else ("pre-glitch" if onset < t0 else "post-glitch")),
            "supply_current_reversed_at_end": bool(math.isfinite(isup_end) and isup_end <= 0.0),
            "supply_current_reversed_at_baseline": (None if isup_base is None else bool(isup_base <= 0.0))}

    # --- baseline ---
    rel_b, fall_b = schmitt(t, rst, v_il, v_ih, False, 0.0)
    pre_rel = [x for x in rel_b if x < t0]
    pre_fall = [x for x in fall_b if x < t0]
    rst_base = [rst[i] for i in base_i]
    raw_base = [raw[i] for i in base_i]
    ripple = (max(idel[i] for i in base_i) - min(idel[i] for i in base_i)) / ibase if (base_i and sign_ok) else float("inf")
    base_issues = []
    if t[-1] < t0 or not base_i:
        base_issues.append("observation ends before the glitch start")
    else:
        if len(pre_rel) != 1 or pre_fall:
            base_issues.append(f"baseline RESETn releases={len(pre_rel)} re-asserts={len(pre_fall)} (need exactly 1 / 0)")
        if not rst_base or min(rst_base) < v_ih:
            base_issues.append("RESETn not settled high over the baseline window")
        if not raw_base or min(raw_base) < v_mid:
            base_issues.append("POR_RAW not high over the baseline window")
        if not sign_ok:
            base_issues.append("delivered bias not positive at baseline")
        elif ripple > BASE_BIAS_RIPPLE:
            base_issues.append(f"delivered bias not settled (p2p {ripple:.3g} of mean > {BASE_BIAS_RIPPLE})")
    baseline = {"ok": not base_issues, "issues": base_issues, "n_release": len(pre_rel), "n_reassert": len(pre_fall), "t_release_s": pre_rel[0] if pre_rel else None,
                "delivered_bias_a": ibase, "delivered_bias_ripple": ripple, "ibias_node_v": _mean([ib[i] for i in base_i]) if base_i else None}

    # --- response ---
    rel, fall = schmitt(t, rst, v_il, v_ih, True, t0)
    dwell_mid = dwell_below(t, raw, v_mid, t0 - 1e-9)
    raw_dn = crossings(t, raw, v_mid, "fall", t0)
    raw_up = crossings(t, raw, v_mid, "rise", t0)
    post = [i for i in range(n) if t[i] >= t0]
    win = [i for i in post if t[i] <= tl["t_end"] + 100e-6]
    raw_min = min(raw[i] for i in win) if win else None
    exercised = bool(raw_dn)
    expect = expectation_a(dwell_mid, control)
    inj_peak = max((abs(w[I_INJ][i]) for i in win), default=None) if not control else 0.0
    g_err = max(abs(gin[i] - g_expected(t[i], st)) for i in range(n))
    vdd_err = max(abs(vdd[i] - vdd_expected_a(t[i], vf, st)) for i in range(n))

    fails = []
    if control and fall:
        fails.append("spurious_assertion_control")
    if expect == "rejection" and exercised and fall:
        fails.append("unwanted_assertion")
    if expect == "assertion_required" and not fall:
        fails.append("missed_assertion")
    if len(fall) >= 2:
        fails.append("reassert_chatter")
    if fall and not rel and not truncated:
        fails.append("no_recovery")
    if raw_dn:
        for r in rel:
            if r > raw_dn[0] and not any(raw_dn[0] < u <= r for u in raw_up):
                fails.append("premature_release")
                break
    end_hi = [rst[i] for i in last]
    if not truncated and end_hi and min(end_hi) < v_ih and "no_recovery" not in fails:
        fails.append("not_high_at_end")
    ibend = _mean([idel[i] for i in last])
    ratio = ibend / ibase if (sign_ok and ibase > 0) else None
    if not truncated and ratio is not None and not (BIAS_BAND[0] <= ratio <= BIAS_BAND[1]):
        fails.append("bias_not_recovered")

    # --- resolution / construction ---
    win_lo, win_hi = t0 - 10e-6, tl["t_end"] + 100e-6
    wi = [i for i in range(n) if win_lo <= t[i] <= win_hi or (i and win_lo <= t[i - 1] <= win_hi)]
    max_dt = max((t[i] - t[i - 1] for i in wi if i > 0), default=float("inf"))
    need_dt = required_max_dt_a(st)
    issues = []
    if max_dt > need_dt * (1 + GAP_RTOL):
        issues.append(f"max sample gap {max_dt:.3g} s in the glitch window > {need_dt:.3g} s (requested width/edge not resolvable)")
    if g_err > G_TOL:
        issues.append(f"sampled injection drive deviates from the declared trapezoid by {g_err:.3g}")
    if vdd_err > VDD_TOL:
        issues.append(f"sampled VDD deviates from the declared supply by {vdd_err:.3g} V")
    if truncated:
        issues.append(f"observation ends at {t[-1]:.6g} s < required {need_end:.6g} s (truncated)")
    if (not control) and not exercised:
        issues.append("injection never took POR_RAW below V_MID: the deglitch dwell was not exercised (no immunity claimed)")

    if not physical:
        verdict = "NONPHYSICAL"
    elif not baseline["ok"]:
        verdict = "UNRESOLVED"
    elif fails:
        verdict = "FAIL"
    elif issues:
        verdict = "UNRESOLVED"
    else:
        verdict = "PASS"
    ok_g = physical and baseline["ok"]
    reasons = (["baseline: " + s for s in base_issues] if (physical and not baseline["ok"]) else []) + issues
    t_assert = fall[0] if fall else None
    return {
        "class": CLASS_A,
        "verdict": verdict,
        "fail_codes": fails if ok_g else [],
        "detected_codes_ungraded": fails if not ok_g else [],
        "unresolved_reasons": reasons,
        "physical": phys,
        "baseline": baseline,
        "control": control,
        "stimulus": {"vf": vf, **{k: st[k] for k in ("t0", "te", "tw", "rinj", "gen", "rup")}, "t_end": tl["t_end"]},
        "levels_v": {"V_IL": v_il, "V_IH": v_ih, "V_MID": v_mid},
        "expectation": {"call": expect, "dwell_raw_below_vmid_s": dwell_mid, "d_rej_s": D_REJ, "d_req_s": D_REQ},
        "injection": {"exercised": exercised, "por_raw_min_v": raw_min, "peak_injected_current_a": inj_peak, "n_raw_fall": len(raw_dn), "n_raw_rise": len(raw_up),
                      "t_raw_fall_s": raw_dn[0] if raw_dn else None, "t_raw_rise_s": raw_up[0] if raw_up else None, "drive_error": g_err,
                      "pins_node_below_v_il": bool(raw_min is not None and raw_min <= v_il)},
        "resetn": {"n_assert": len(fall), "n_release_after_t0": len(rel), "t_assert_s": t_assert, "t_release_s": rel[0] if rel else None,
                   "min_after_t0_v": min(rst[i] for i in post) if post else None, "end_v": rst[-1],
                   "recovery_delay_after_pulse_end_s": (rel[-1] - tl["t_end"]) if rel else None,
                   "spurious_releases": 1 if "premature_release" in fails else 0},
        "vdd": {"stimulus_error_v": vdd_err},
        "delivered_bias": {"baseline_a": ibase, "min_after_t0_a": min(idel[i] for i in post) if post else None, "end_a": ibend, "end_over_baseline": ratio,
                           "at_assert_a": interp_at(t, idel, t_assert) if t_assert else None,
                           "sink_ids_end_a": {s: _mean([w[s][i] for i in last]) for s in I_SINKS if s in w},
                           "sink_sum_over_delivered_end": (sum(_mean([w[s][i] for i in last]) for s in I_SINKS) / ibend) if (all(s in w for s in I_SINKS) and ibend > 0) else None},
        "ibias_node": {"baseline_v": baseline["ibias_node_v"], "min_after_t0_v": min(ib[i] for i in post) if post else None, "end_v": _mean([ib[i] for i in last])},
        "resolution": {"n_samples": n, "max_dt_glitch_window_s": max_dt, "required_max_dt_s": need_dt, "t_end_s": t[-1], "required_t_end_s": need_end, "truncated": truncated},
    }


# --------------------------------------------------------------------------
# class B analysis: the brown-out core, relabelled and extended
# --------------------------------------------------------------------------


def analyze_b(w, vf: float, st: dict, t_obs: float) -> dict:
    """Grade one VDD-level glitch point (class B) with the proven brown-out core, sf = sr, and add the regime labels."""
    s = b_stim(st)
    res = bc.analyze(w, vf, s, t_obs)
    res["class"] = CLASS_B
    if res["verdict"] == "ERROR":
        return res
    # the sample-gap rule is the brown-out core's (bc.required_max_dt), unchanged: hold/5, edge/10, 20 us
    res["detectability"]["call"] = "no_glitch" if res["control"] else ("assertion_required" if res["detectability"]["required_to_assert"] else "assertion_optional")
    vmin = res["vdd"]["min_after_t0_v"]
    asserted = res["resetn"]["n_assert"] > 0
    res["regime"] = {
        "rail_collapse": bool(vmin is not None and not res["control"] and vmin <= res["levels_v"]["V_IL"]),
        "dwell_rejection_visible": bool((not res["control"]) and res["por_raw"]["n_fall_after_t0"] > 0 and not asserted),
        "resetn_asserted": asserted,
    }
    return res


def analyze(cls: str, w, vf: float, st: dict, t_obs: float) -> dict:
    return analyze_a(w, vf, st, t_obs) if cls == CLASS_A else analyze_b(w, vf, st, t_obs)


# --------------------------------------------------------------------------
# event-preserving trace compression (what gets committed)
# --------------------------------------------------------------------------

KEEP_DV, KEEP_DT, KEEP_DI_FRAC = bc.KEEP_DV, bc.KEEP_DT, bc.KEEP_DI_FRAC


def compress(w: dict, with_inj: bool) -> list[list[float]]:
    """Change-triggered decimation (any voltage >= 2 mV, delivered bias >= 2 % of max, injection current, or 1 ms)."""
    cols = [w["time"], w["v(vdd)"], w["v(resetn)"], w["v(xdut.por_raw)"], w["v(xdut.ibias)"], list(w[I_DELIVERED])]
    if with_inj:
        cols += [list(w[V_GINJ]), list(w[I_INJ])]
    n = len(cols[0])
    di = KEEP_DI_FRAC * max(abs(x) for x in cols[5]) or 1e-12
    dj = (KEEP_DI_FRAC * max(abs(x) for x in cols[7]) or 1e-12) if with_inj else None
    rows = [[c[0] for c in cols]]
    last = rows[0]
    for i in range(1, n - 1):
        cur = [c[i] for c in cols]
        ch = cur[0] - last[0] >= KEEP_DT or any(abs(cur[k] - last[k]) >= KEEP_DV for k in range(1, 5)) or abs(cur[5] - last[5]) >= di
        if with_inj:
            ch = ch or abs(cur[6] - last[6]) >= 0.01 or abs(cur[7] - last[7]) >= dj
        if ch:
            rows.append(cur)
            last = cur
    rows.append([c[n - 1] for c in cols])
    return rows


def transitions_from_stored(rows, vf: float, t0: float) -> dict:
    return bc.transitions_from_stored(rows, vf, t0)


def write_trace(path: Path, rows, with_inj: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "# t_s,vdd_v,resetn_v,por_raw_v,ibias_node_v,ibias_delivered_a" + (",ginj_drive,i_inj_a" if with_inj else "")
    lines = [head + "  (ibias_delivered = +id of bias_core XMPIB; i_inj = current in RINJ; change-triggered)"]
    lines += [",".join(f"{x:.6g}" for x in r) for r in rows]
    with gzip.open(path, "wt", compresslevel=9) as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# synthetic waveforms with known answers (self-test)
# --------------------------------------------------------------------------

REF_A = {"rup": 1e5, "t0": 8e-3, "te": 20e-6, "tw": 200e-6, "rinj": 1e3, "gen": 1}
REF_B = {"rup": 1e5, "t0": 8e-3, "vlow": 1.2, "sf": 5e4, "th": 200e-6}
T_OBS_REF = 8e-3


def _grid_a(st, t_obs, coarse=None, tstop=None):
    tl = timeline_a(st)
    end = tstop if tstop is not None else tl["t_end"] + t_obs
    lo, hi = st["t0"] - 200e-6, tl["t_end"] + 200e-6
    ts = [0.0]
    while ts[-1] < end:
        cur = ts[-1]
        ts.append(min(end, cur + (coarse or (0.5e-6 if lo <= cur <= hi else 50e-6))))
    return ts


def synth_a(vf=3.3, st=None, t_obs=T_OBS_REF, behavior="ok", coarse=None, tstop=None, bad_node=None, drop_channel=None):
    """Behavioural stand-in for the DUT under class-A injection.

    behavior: ok (POR_RAW dips; RESETn per the expectation of the dwell) | force_assert (assert even on a rejection-class pulse) |
    missed (no assertion on an assertion-required pulse) | premature | chatter | no_recovery | no_baseline | bias_lost |
    no_effect (POR_RAW never dips) | control_assert.
    """
    st = dict(st or REF_A)
    tl = timeline_a(st)
    ts = _grid_a(st, t_obs, coarse, tstop)
    v_mid, v_il = FRAC_MID * vf, FRAC_IL * vf
    t_on = st["t0"] + st["te"] * 0.5  # POR_RAW crosses V_MID half way up the injection edge
    t_off = tl["t_fall_start"] + st["te"] * 0.5 + 30e-6  # POR_RAW recovers a little after the injection ends
    dwell = (t_off - t_on) if (not tl["control"] and behavior != "no_effect") else 0.0
    assert_ = behavior in ("force_assert", "premature", "chatter", "no_recovery") or (dwell >= D_REQ and behavior != "missed") or (behavior == "ok" and dwell >= D_REQ)
    if behavior == "ok" and D_REJ <= dwell < D_REQ:
        assert_ = False
    t_a = t_on + 5e-6
    t_r = t_off + 1.0e-3
    cols = {c: [] for c in CORE_A + (I_INJ,)}
    for x in ts:
        v = min(vf, st["rup"] * x)
        rs = 0.0 if behavior == "no_baseline" else (v if x >= 2.5e-3 else 0.0)
        if x >= 2.5e-3 and behavior != "no_baseline":
            if assert_ and t_a <= x:
                rs = 0.0
                if behavior == "premature":
                    t_pre = t_on + 40e-6
                    rs = v if x >= t_pre else 0.0
                elif behavior != "no_recovery" and x >= t_r:
                    rs = v
            if behavior == "chatter" and t_r + 0.3e-3 <= x < t_r + 0.6e-3:
                rs = 0.0
            if behavior == "control_assert" and st["t0"] + 3e-3 <= x < st["t0"] + 4e-3:
                rs = 0.0
        pr = v if x >= 0.3e-3 else 0.0
        if dwell > 0 and t_on <= x < t_off:
            pr = 0.05 * v
        g = g_expected(x, st)
        cols["time"].append(x)
        cols["v(vdd)"].append(v)
        cols["v(resetn)"].append(rs)
        cols["v(xdut.por_raw)"].append(pr)
        cols["v(xdut.ibias)"].append(0.85)
        cols["i(bvdd)"].append(-2.3e-5)
        i_nom = 5e-6
        if behavior == "bias_lost" and x > t_off + 3e-3:
            i_nom = 1e-6
        cols[I_DELIVERED].append(i_nom)
        cols[V_GINJ].append(g)
        cols[I_INJ].append(g * v / max(st["rinj"], 1.0) * 0.8)
    for name in PHYS_NODES:
        cols.setdefault(name, [0.5] * len(ts))
    for s in I_SINKS:
        cols[s] = [1e-6] * len(ts)
    if bad_node:
        name, val = bad_node
        cols[name] = [0.5] + [val] * 50 + [0.5] * (len(ts) - 51)
    if drop_channel:
        cols.pop(drop_channel, None)
    return cols, st


def synth_b(vf=3.3, st=None, t_obs=T_OBS_REF, behavior="ok", **kw):
    """Class-B stand-in: the brown-out synthetic DUT with sf = sr.  ``behavior`` as in bc.synth."""
    s = b_stim(dict(st or REF_B))
    return bc.synth(vf, s, t_obs, behavior, **kw)


def selftest_cases():
    a_rej = dict(REF_A, tw=10e-6, te=5e-6)  # dwell < D_REJ  -> rejection
    a_mid = dict(REF_A, tw=300e-6)  # D_REJ <= dwell < D_REQ -> optional
    a_req = dict(REF_A, tw=2e-3)  # dwell >= D_REQ -> assertion required
    a_ctl = dict(REF_A, gen=0)
    b_req = dict(REF_B)
    b_shallow = dict(REF_B, vlow=2.4, sf=2e4, th=20e-6)
    b_ctl = dict(REF_B, vlow=99.0)
    b_collapse = dict(REF_B, vlow=0.2)
    A, B = CLASS_A, CLASS_B
    return {
        # --- class A
        "A_rejected_pulse": (A, lambda: synth_a(st=a_rej), "PASS", []),
        "A_optional_pulse_no_assert": (A, lambda: synth_a(st=a_mid), "PASS", []),
        "A_required_assertion_recovers": (A, lambda: synth_a(st=a_req), "PASS", []),
        "A_missed_assertion": (A, lambda: synth_a(st=a_req, behavior="missed"), "FAIL", ["missed_assertion"]),
        "A_unwanted_assertion": (A, lambda: synth_a(st=a_rej, behavior="force_assert"), "FAIL", ["unwanted_assertion"]),
        "A_premature_release": (A, lambda: synth_a(st=a_req, behavior="premature"), "FAIL", ["premature_release"]),
        "A_multiple_releases_chatter": (A, lambda: synth_a(st=a_req, behavior="chatter"), "FAIL", ["reassert_chatter"]),
        "A_no_recovery": (A, lambda: synth_a(st=a_req, behavior="no_recovery"), "FAIL", ["no_recovery"]),
        "A_bias_not_recovered": (A, lambda: synth_a(st=a_req, behavior="bias_lost"), "FAIL", ["bias_not_recovered"]),
        "A_injection_not_exercised": (A, lambda: synth_a(st=a_rej, behavior="no_effect"), "UNRESOLVED", []),
        "A_sparse_samples": (A, lambda: synth_a(st=a_req, coarse=100e-6), "UNRESOLVED", []),
        "A_truncated_observation": (A, lambda: synth_a(st=a_req, tstop=a_req["t0"] + 1e-3), "UNRESOLVED", []),
        "A_unsettled_baseline": (A, lambda: synth_a(st=a_req, behavior="no_baseline"), "UNRESOLVED", []),
        "A_nonphysical_node": (A, lambda: synth_a(st=a_req, bad_node=("v(xdut.xtemp.nb)", -50.0)), "NONPHYSICAL", []),
        "A_missing_current_channel": (A, lambda: synth_a(st=a_req, drop_channel=I_DELIVERED), "ERROR", []),
        "A_missing_injection_channel": (A, lambda: synth_a(st=a_req, drop_channel=I_INJ), "ERROR", []),
        "A_control_ok": (A, lambda: synth_a(st=a_ctl), "PASS", []),
        "A_control_spurious_assertion": (A, lambda: synth_a(st=a_ctl, behavior="control_assert"), "FAIL", ["spurious_assertion_control"]),
        # --- class B
        "B_required_assertion_recovers": (B, lambda: synth_b(st=b_req), "PASS", []),
        "B_shallow_glitch_rejected": (B, lambda: synth_b(st=b_shallow), "PASS", []),
        "B_missed_assertion": (B, lambda: synth_b(st=b_req, behavior="missed"), "FAIL", ["missed_assertion"]),
        "B_premature_release": (B, lambda: synth_b(st=b_req, behavior="premature"), "FAIL", ["premature_release"]),
        "B_multiple_releases_chatter": (B, lambda: synth_b(st=b_req, behavior="chatter"), "FAIL", ["reassert_chatter"]),
        "B_sparse_samples": (B, lambda: synth_b(st=b_req, coarse=100e-6), "UNRESOLVED", []),
        "B_unsettled_baseline": (B, lambda: synth_b(st=b_req, behavior="no_baseline"), "UNRESOLVED", []),
        "B_rail_collapse_nonphysical": (B, lambda: synth_b(st=b_collapse, bad_node=("v(xdut.xtemp.na)", -80.0)), "NONPHYSICAL", []),
        "B_missing_waveform_channel": (B, lambda: synth_b(st=b_req, drop_channel="v(xdut.por_raw)"), "ERROR", []),
        "B_control_ok": (B, lambda: synth_b(st=b_ctl), "PASS", []),
        "B_control_spurious_assertion": (B, lambda: synth_b(st=b_ctl, behavior="control_assert"), "FAIL", ["spurious_assertion_control"]),
    }


def run_selftest(fixture_dir: Path | None = None) -> list[dict]:
    out = []
    for name, (cls, build, want, want_codes) in selftest_cases().items():
        wave, st = build()
        res = analyze(cls, wave, 3.3, st, T_OBS_REF)
        got = res["verdict"]
        codes = res.get("fail_codes", [])
        ok = got == want and all(c in codes for c in want_codes)
        out.append({"case": name, "class": cls, "expected_verdict": want, "expected_codes_subset": want_codes, "verdict": got, "fail_codes": codes,
                    "unresolved_reasons": res.get("unresolved_reasons", []), "ok": ok})
        if fixture_dir is not None and name in ("A_required_assertion_recovers", "A_missed_assertion", "B_required_assertion_recovers"):
            fixture_dir.mkdir(parents=True, exist_ok=True)
            names = [c for c in wave if c in CORE_A or c == I_INJ or c in CORE_B]
            doc = {"plotname": "Synthetic (controlled) -- sim/glitch-top/glitch_checker.py", "class": cls, "stimulus": st,
                   "variables": [{"index": i, "name": c} for i, c in enumerate(names)],
                   "points": [[wave[c][k] for c in names] for k in range(len(wave["time"]))]}
            with open(fixture_dir / f"{name}.wave.json.gz", "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
                gz.write(json.dumps(doc, separators=(",", ":")).encode())
    return out


if __name__ == "__main__":
    res = run_selftest()
    for r in res:
        print(f"{r['case']:<34} expected {r['expected_verdict']:<12} got {r['verdict']:<12} codes={r['fail_codes']} {'OK' if r['ok'] else 'MISMATCH'}")
    sys.exit(0 if all(r["ok"] for r in res) else 1)
