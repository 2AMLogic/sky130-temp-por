#!/usr/bin/env python3
"""Brown-out waveform checker for the assembled temp_por_top (issue #116).

Pure standard library.  Grades ONE brown-out point from the full-resolution
waveform that ``klt sim`` writes for a corner.  Every threshold below is an
EXPLORATORY measurement definition declared in experiment.json (``grading``);
none is a ratified bound.  No gf180mcu number is used (CLAUDE.md: thresholds do
not port; DR-003 Sec8: no numeric brown-out envelope is ratified).

Stimulus (see ``timeline``): power-up ramp, a settled baseline, then ONE dip
with independent axes -- floor ``vlow``, falling slew ``sf``, hold ``th``,
recovery slew ``sr`` -- and ``t0`` the dip start.  Edge durations are derived:
``ex/sf`` and ``ex/sr`` with ``ex = vf - vlow``.

Verdicts (precedence, highest first)
------------------------------------
ERROR        a required waveform channel is missing, the data is non-finite /
             too short / not monotonic, or there is no waveform at all.
NONPHYSICAL  a saved node leaves [-0.3, vf+0.5] V after t=0, the settled supply
             current is not positive, or the delivered bias branch has the
             wrong sign.  A non-physical point can never PASS (and its
             behavioural verdict is not graded).
UNRESOLVED   the baseline before the dip is not viable (RESETn not released
             exactly once and settled high, delivered bias not settled), OR no
             failure was detected but the evidence is insufficient (sample gap
             in the dip window too large, stimulus not as declared, the
             observation window truncated).
FAIL         a resolved physical failure; the codes say which.
PASS         none of the above.

Failure codes
-------------
missed_assertion        the dip was *required-to-assert* (VDD below V_MUST for
                        at least T_REQ) yet RESETn never fell below V_IL.
no_recovery             RESETn asserted but did not release inside the
                        (complete) observation window.
premature_release       POR_RAW fell through V_MID in the dip and RESETn
                        released with no POR_RAW rise in between.
reassert_after_recovery an assertion starts after VDD has recovered.
reassert_chatter        two or more assertions for one dip.
not_high_at_end         RESETn is not >= V_IH over the last SETTLE_WINDOW.
bias_not_recovered      delivered bias at the end is outside BIAS_BAND x the
                        pre-dip baseline.
spurious_assertion_control   (no-dip control only) RESETn fell below V_IL.

Delivered bias: the drain current ``[id]`` of bias_core's XMPIB (PMOS whose
drain is the IBIAS node), saved by the testbench and appearing in the klt
waveform as ``i(@m.xdut.xbias.xmpib.msky130_fd_pr__pfet_g5v0d10v5[id])``.  ngspice
BSIM4 reports ``id`` POSITIVE for normal conduction in both polarities (verified
in the local probe by KCL: XMPIB id equals the sum of the consumer-side diode
devices' ids), so the delivered branch current is ``+id`` and a negative
baseline value is a sign-convention violation -> NONPHYSICAL.  The IBIAS NODE
voltage ``v(xdut.ibias)`` is recorded separately and is never used as a current.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from sim_common import load_wave  # noqa: E402,F401

# --- exploratory grading constants (mirrored in experiment.json "grading") ---
FRAC_IL, FRAC_IH, FRAC_MID = 0.2, 0.8, 0.5
FRAC_MUST = 0.5  # V_MUST = 0.5*vf : "required to assert" level
T_REQ = 50e-6  # s dwell below V_MUST that makes an assertion required
FRAC_VREC = 0.98  # VDD recovered when >= 0.98*vf
BASE_WIN = 2e-3  # s baseline window before t0
SETTLE_WINDOW = 1e-3  # s trailing window for "end" values
BASE_BIAS_RIPPLE = 0.05  # baseline delivered bias must be within +-5 % of its mean
BIAS_BAND = (0.8, 1.25)  # end/baseline delivered-bias ratio
MAX_DT_CAP = 20e-6  # s absolute cap on the sample gap in the dip window
VDD_TOL = 0.02  # V: sampled VDD vs the declared stimulus
PHYS_LO, PHYS_HI_MARGIN = -0.3, 0.5

I_DELIVERED = "i(@m.xdut.xbias.xmpib.msky130_fd_pr__pfet_g5v0d10v5[id])"
I_SINKS = (
    "i(@m.xdut.xcmp.xmbd.msky130_fd_pr__nfet_g5v0d10v5[id])",
    "i(@m.xdut.xpor.xmbd.msky130_fd_pr__nfet_g5v0d10v5[id])",
    "i(@m.xdut.xtemp.xmbd.msky130_fd_pr__nfet_g5v0d10v5[id])",
)
CORE = ("time", "v(vdd)", "v(resetn)", "v(xdut.por_raw)", "v(xdut.ibias)", "i(bvdd)", I_DELIVERED)
PHYS_NODES = (
    "v(resetn)", "v(xdut.por_raw)", "v(xdut.ibias)", "v(xdut.vref)", "v(xdut.bias_ok)", "v(ptat)", "v(ctat)",
    "v(xdut.xbias.na)", "v(xdut.xbias.nb)", "v(xdut.xbias.nbg)", "v(xdut.xbias.pb)", "v(xdut.xbias.pg)",
    "v(xdut.xtemp.na)", "v(xdut.xtemp.nb)",
)


# --------------------------------------------------------------------------
# stimulus construction (shared with the runner; the testbench BVDD expression
# is the SPICE twin of vdd_expected)
# --------------------------------------------------------------------------


def timeline(vf: float, st: dict) -> dict:
    """Segment times of the dip.  ``st``: vlow, sf, th, sr, t0 (control: vlow >= vf)."""
    ex = max(vf - st["vlow"], 0.0)
    exd = max(ex, 1e-3)
    tf = exd / st["sf"]
    tr = exd / st["sr"]
    t_f1 = st["t0"] + tf
    t_r0 = t_f1 + st["th"]
    return {"ex": ex, "t_fall": tf, "t_rec": tr, "t_fall_end": t_f1, "t_rec_start": t_r0, "t_rec_end": t_r0 + tr, "control": ex <= 0.0}


def _clip01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def vdd_expected(t: float, vf: float, st: dict) -> float:
    tl = timeline(vf, st)
    ex = tl["ex"]
    exd = max(ex, 1e-3)
    frac = _clip01((t - st["t0"]) * st["sf"] / exd) - _clip01((t - st["t0"] - exd / st["sf"] - st["th"]) * st["sr"] / exd)
    return min(vf, st["rup"] * t) - ex * frac


def tstop_for(vf: float, st: dict, t_obs: float) -> float:
    return timeline(vf, st)["t_rec_end"] + t_obs


def tmax_for(st: dict, vf_min: float, th_cap: float = 5e-6) -> float:
    """Max time step: <= 5 us, <= hold/10, <= 1/20 of the shortest derived edge (smallest start supply)."""
    ex_min = max(vf_min - st["vlow"], 0.0)
    if ex_min <= 0:
        return th_cap
    edges = min(ex_min / st["sf"], ex_min / st["sr"])
    return min(th_cap, st["th"] / 10.0, edges / 20.0)


def required_max_dt(vf: float, st: dict) -> float:
    """Largest tolerated sample gap in the dip window (the sample-resolution criterion)."""
    tl = timeline(vf, st)
    if tl["control"]:
        return MAX_DT_CAP
    return min(MAX_DT_CAP, st["th"] / 5.0, min(tl["t_fall"], tl["t_rec"]) / 10.0)


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def _x(t0, y0, t1, y1, level):
    return t1 if y1 == y0 else t0 + (level - y0) * (t1 - t0) / (y1 - y0)


def crossings(t, y, level, direction, t_from=0.0):
    out = []
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        a, b = y[i - 1], y[i]
        if direction == "rise" and a < level <= b:
            out.append(_x(t[i - 1], a, t[i], b, level))
        elif direction == "fall" and a > level >= b:
            out.append(_x(t[i - 1], a, t[i], b, level))
    return out


def schmitt(t, y, lo, hi, init_high, t_from):
    """(rises, falls) of a two-threshold detector over t > t_from, starting in ``init_high``."""
    state = init_high
    rises, falls = [], []
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        a, b = y[i - 1], y[i]
        if not state and b >= hi:
            rises.append(_x(t[i - 1], a, t[i], b, hi) if a < hi else t[i])
            state = True
        elif state and b <= lo:
            falls.append(_x(t[i - 1], a, t[i], b, lo) if a > lo else t[i])
            state = False
    return rises, falls


def interp_at(t, y, when):
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


def dwell_below(t, y, level, t_from=0.0):
    """Time (s) the piecewise-linear signal spends below ``level`` for t > t_from."""
    total = 0.0
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        t0, t1, a, b = max(t[i - 1], t_from), t[i], y[i - 1], y[i]
        if t0 != t[i - 1]:
            a = y[i - 1] + (t0 - t[i - 1]) * (b - a) / (t[i] - t[i - 1])
        if a < level and b < level:
            total += t1 - t0
        elif a < level <= b or b < level <= a:
            tc = _x(t0, a, t1, b, level)
            total += (tc - t0) if a < level else (t1 - tc)
    return total


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


# --------------------------------------------------------------------------
# point analysis
# --------------------------------------------------------------------------


def _err(detail, **extra):
    return {"verdict": "ERROR", "fail_codes": [], "unresolved_reasons": [], "detail": detail, **extra}


def analyze(w, vf: float, st: dict, t_obs: float) -> dict:
    """Grade one brown-out point.  ``w`` None or lacking a channel -> ERROR."""
    if w is None:
        return _err("no waveform retrieved")
    missing = [n for n in CORE if n not in w]
    if missing:
        return _err(f"waveform lacks {missing}")
    t = w["time"]
    n = len(t)
    if n < 3 or any(not math.isfinite(x) for name in CORE for x in w[name]):
        return _err("too few or non-finite samples")
    if any(t[i + 1] <= t[i] for i in range(n - 1)):
        return _err("time axis not strictly increasing")

    vdd, rst, raw, ib = w["v(vdd)"], w["v(resetn)"], w["v(xdut.por_raw)"], w["v(xdut.ibias)"]
    idel = list(w[I_DELIVERED])  # delivered branch current (A); BSIM4 [id] is positive for normal conduction (see docstring)
    tl = timeline(vf, st)
    t0, control = st["t0"], tl["control"]
    v_il, v_ih, v_mid, v_must = FRAC_IL * vf, FRAC_IH * vf, FRAC_MID * vf, FRAC_MUST * vf
    need_end = tl["t_rec_end"] + t_obs
    truncated = t[-1] < need_end * (1 - 1e-6)

    # --- physicality ---
    hi = vf + PHYS_HI_MARGIN
    viol = {}
    for name in PHYS_NODES:
        col = w.get(name)
        if col is None:
            continue
        bad = [x for tt, x in zip(t, col) if tt > 0 and not (PHYS_LO <= x <= hi)]
        if bad:
            viol[name] = {"count": len(bad), "min": min(bad), "max": max(bad)}
    last = [i for i in range(n) if t[i] >= t[-1] - SETTLE_WINDOW]
    isup_end = _mean([-w["i(bvdd)"][i] for i in last])
    base_i = [i for i in range(n) if t0 - BASE_WIN <= t[i] <= t0]
    ibase = _mean([idel[i] for i in base_i]) if base_i else float("nan")
    sign_ok = (not base_i) or (math.isfinite(ibase) and ibase > 0.0)  # no baseline samples = unknowable here, reported by the baseline check
    physical = (not viol) and math.isfinite(isup_end) and isup_end > 0.0 and sign_ok
    phys = {"ok": physical, "isup_end_a": isup_end, "violations_after_t0": viol, "delivered_bias_sign_ok": sign_ok}

    # --- baseline viability (before t0) ---
    rel_b, fall_b = schmitt(t, rst, v_il, v_ih, False, 0.0)
    pre_rel = [x for x in rel_b if x < t0]
    pre_fall = [x for x in fall_b if x < t0]
    rst_base = [rst[i] for i in base_i]
    ripple = (max(idel[i] for i in base_i) - min(idel[i] for i in base_i)) / ibase if (base_i and sign_ok) else float("inf")
    base_issues = []
    if t[-1] < t0 or not base_i:
        base_issues.append("observation ends before the dip start")
    else:
        if len(pre_rel) != 1 or pre_fall:
            base_issues.append(f"baseline RESETn releases={len(pre_rel)} re-asserts={len(pre_fall)} (need exactly 1 / 0)")
        if not rst_base or min(rst_base) < v_ih:
            base_issues.append("RESETn not settled high over the baseline window")
        if not sign_ok:
            base_issues.append("delivered bias not positive at baseline")
        elif ripple > BASE_BIAS_RIPPLE:
            base_issues.append(f"delivered bias not settled (p2p {ripple:.3g} of mean > {BASE_BIAS_RIPPLE})")
    baseline = {"ok": not base_issues, "issues": base_issues, "n_release": len(pre_rel), "n_reassert": len(pre_fall),
                "t_release_s": pre_rel[0] if pre_rel else None, "delivered_bias_a": ibase, "delivered_bias_ripple": ripple,
                "ibias_node_v": _mean([ib[i] for i in base_i]) if base_i else None}

    # --- dip response (RESETn starts HIGH at t0) ---
    rel, fall = schmitt(t, rst, v_il, v_ih, True, t0)
    t_vrec = None
    if control:
        t_vrec = t0
    else:
        up = crossings(t, vdd, FRAC_VREC * vf, "rise", tl["t_rec_start"])
        t_vrec = up[0] if up else None
    dwell = 0.0 if control else dwell_below(t, vdd, v_must, t0 - 1e-9)
    required = (not control) and dwell >= T_REQ
    raw_dn = crossings(t, raw, v_mid, "fall", t0)
    raw_up = crossings(t, raw, v_mid, "rise", t0)
    vdd_at_assert = interp_at(t, vdd, fall[0]) if fall else None
    post = [i for i in range(n) if t[i] >= t0]
    p_vdd_min = min(vdd[i] for i in post) if post else None

    fails = []
    if control and fall:
        fails.append("spurious_assertion_control")
    if required and not fall:
        fails.append("missed_assertion")
    if len(fall) >= 2:
        fails.append("reassert_chatter")
    if t_vrec is not None and any(f > t_vrec for f in fall):
        fails.append("reassert_after_recovery")
    if fall and not rel and not truncated:
        fails.append("no_recovery")
    if raw_dn:
        for r in rel:
            if r > raw_dn[0] and not any(raw_dn[0] < u <= r for u in raw_up):
                fails.append("premature_release")
                break
    end_hi = [rst[i] for i in last]
    if not truncated and end_hi and min(end_hi) < v_ih:
        if "no_recovery" not in fails:
            fails.append("not_high_at_end")
    ibend = _mean([idel[i] for i in last])
    ratio = ibend / ibase if (sign_ok and ibase > 0) else None
    if not truncated and ratio is not None and not (BIAS_BAND[0] <= ratio <= BIAS_BAND[1]):
        fails.append("bias_not_recovered")

    # --- resolution / construction ---
    win_lo = t0 - 10e-6
    win_hi = (t_vrec if t_vrec is not None else tl["t_rec_end"]) + 100e-6
    win = [i for i in range(n) if win_lo <= t[i] <= win_hi or (i and win_lo <= t[i - 1] <= win_hi)]
    max_dt = max((t[i] - t[i - 1] for i in win if i > 0), default=float("inf"))
    need_dt = required_max_dt(vf, st)
    vdd_err = max(abs(vdd[i] - vdd_expected(t[i], vf, st)) for i in range(n))
    issues = []
    if max_dt > need_dt:
        issues.append(f"max sample gap {max_dt:.3g} s in the dip window > {need_dt:.3g} s")
    if vdd_err > VDD_TOL:
        issues.append(f"sampled VDD deviates from the declared stimulus by {vdd_err:.3g} V")
    if truncated:
        issues.append(f"observation ends at {t[-1]:.6g} s < required {need_end:.6g} s (truncated)")
    if t_vrec is None and not control:
        issues.append("VDD never recovered to the declared level inside the record")

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
    reasons = (["baseline: " + s for s in base_issues] if (physical and not baseline["ok"]) else []) + issues
    return {
        "verdict": verdict,
        "fail_codes": fails if (physical and baseline["ok"]) else [],
        "detected_codes_ungraded": fails if not (physical and baseline["ok"]) else [],
        "unresolved_reasons": reasons,
        "physical": phys,
        "baseline": baseline,
        "control": control,
        "stimulus": {"vf": vf, **{k: st[k] for k in ("vlow", "sf", "th", "sr", "t0", "rup")}, **{k: tl[k] for k in ("ex", "t_fall", "t_rec", "t_rec_end")}},
        "levels_v": {"V_IL": v_il, "V_IH": v_ih, "V_MID": v_mid, "V_MUST": v_must},
        "detectability": {"dwell_below_vmust_s": dwell, "t_req_s": T_REQ, "required_to_assert": required},
        "resetn": {"n_release_after_t0": len(rel), "n_assert": len(fall), "t_assert_s": fall[0] if fall else None, "t_release_s": rel[0] if rel else None,
                   "vdd_at_assert_v": vdd_at_assert, "assertion_rail_limited": (vdd_at_assert is not None and vdd_at_assert <= v_il),
                   "min_after_t0_v": min(rst[i] for i in post) if post else None, "end_v": rst[-1]},
        "por_raw": {"n_fall_after_t0": len(raw_dn), "n_rise_after_t0": len(raw_up)},
        "vdd": {"min_after_t0_v": p_vdd_min, "t_recovered_s": t_vrec},
        "delivered_bias": {"baseline_a": ibase, "min_after_t0_a": min(idel[i] for i in post) if post else None, "end_a": ibend, "end_over_baseline": ratio,
                           "at_assert_a": interp_at(t, idel, fall[0]) if fall else None,
                           "sink_ids_end_a": {s: _mean([w[s][i] for i in last]) for s in I_SINKS if s in w},
                           "sink_sum_over_delivered_end": (sum(_mean([w[s][i] for i in last]) for s in I_SINKS) / ibend) if (all(s in w for s in I_SINKS) and ibend > 0) else None},
        "ibias_node": {"baseline_v": baseline["ibias_node_v"], "min_after_t0_v": min(ib[i] for i in post) if post else None, "end_v": _mean([ib[i] for i in last]),
                       "at_assert_v": interp_at(t, ib, fall[0]) if fall else None},
        "resolution": {"n_samples": n, "max_dt_dip_window_s": max_dt, "required_max_dt_s": need_dt, "vdd_stimulus_error_v": vdd_err, "t_end_s": t[-1], "required_t_end_s": need_end, "truncated": truncated},
    }


# --------------------------------------------------------------------------
# event-preserving trace compression (what gets committed)
# --------------------------------------------------------------------------

STORE_COLS = ("time", "v(vdd)", "v(resetn)", "v(xdut.por_raw)", "v(xdut.ibias)", "ibias_delivered_a")
KEEP_DV, KEEP_DT, KEEP_DI_FRAC = 2e-3, 1e-3, 0.02


def compress(w: dict) -> list[list[float]]:
    """Change-triggered decimation: keep a row when any voltage moved >= 2 mV, the delivered bias moved >= 2 % of its max, or 1 ms elapsed."""
    cols = [w["time"], w["v(vdd)"], w["v(resetn)"], w["v(xdut.por_raw)"], w["v(xdut.ibias)"], list(w[I_DELIVERED])]
    n = len(cols[0])
    di = KEEP_DI_FRAC * max(abs(x) for x in cols[5]) or 1e-12
    rows = [[c[0] for c in cols]]
    last = rows[0]
    for i in range(1, n - 1):
        cur = [c[i] for c in cols]
        if cur[0] - last[0] >= KEEP_DT or any(abs(cur[k] - last[k]) >= KEEP_DV for k in range(1, 5)) or abs(cur[5] - last[5]) >= di:
            rows.append(cur)
            last = cur
    rows.append([c[n - 1] for c in cols])
    return rows


def transitions_from_stored(rows, vf: float, t0: float) -> dict:
    t = [r[0] for r in rows]
    rel, fall = schmitt(t, [r[2] for r in rows], FRAC_IL * vf, FRAC_IH * vf, True, t0)
    return {"n_release": len(rel), "n_assert": len(fall)}


def write_trace(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# t_s,vdd_v,resetn_v,por_raw_v,ibias_node_v,ibias_delivered_a  (+id of bias_core XMPIB; change-triggered)"]
    lines += [",".join(f"{x:.6g}" for x in r) for r in rows]
    with gzip.open(path, "wt", compresslevel=9) as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# synthetic waveforms with known answers (self-test)
# --------------------------------------------------------------------------

REF_ST = {"rup": 1e4, "t0": 20e-3, "vlow": 1.2, "sf": 1e5, "th": 100e-6, "sr": 1e5}
T_OBS_REF = 20e-3


def _grid(vf, st, t_obs, dt_base=50e-6, dt_dip=1e-6, coarse=None, tstop=None):
    tl = timeline(vf, st)
    end = tstop if tstop is not None else tl["t_rec_end"] + t_obs
    ts = [0.0]
    lo, hi = st["t0"] - 200e-6, tl["t_rec_end"] + 200e-6
    while ts[-1] < end:
        cur = ts[-1]
        step = coarse or (dt_dip if lo <= cur <= hi else dt_base)
        ts.append(min(end, cur + step))
    return ts


def synth(vf=3.3, st=None, t_obs=T_OBS_REF, behavior="ok", coarse=None, tstop=None, bad_node=None, drop_channel=None):
    """Behavioural stand-in for the DUT.  behavior in ok | missed | premature | chatter | no_recovery | no_baseline | bias_lost | control_assert."""
    st = dict(st or REF_ST)
    tl = timeline(vf, st)
    ts = _grid(vf, st, t_obs, coarse=coarse, tstop=tstop)
    t_raw0 = 0.3e-3  # POR_RAW first rise during power-up
    t_rel0 = 2.5e-3  # baseline release
    v_must = FRAC_MUST * vf
    vdd = [vdd_expected(x, vf, st) for x in ts]
    # when does the rail first go under V_MUST / recover (analytic search on the dense grid)
    t_dn = next((x for x, v in zip(ts, vdd) if x > st["t0"] and v < v_must), None)
    t_up = next((x for x, v in zip(ts, vdd) if x > tl["t_rec_start"] and v >= FRAC_VREC * vf), None)
    t_assert = t_dn
    t_release = (t_up + 2e-3) if t_up is not None else None
    t_raw_up = (t_up + 1.9e-3) if t_up is not None else None
    if behavior == "premature" and t_up is not None:
        t_raw_up = t_up + 2.5e-3
    if behavior == "chatter" and t_release is not None:
        pass
    cols = {c: [] for c in CORE}
    for x, v in zip(ts, vdd):
        rs = 0.0
        if behavior == "no_baseline":
            rs = 0.0  # never released
        elif x >= t_rel0:
            rs = v
            if behavior != "missed" and not (behavior == "control_assert" and False):
                if t_assert is not None and x >= t_assert and st["vlow"] < vf:
                    rs = 0.0
                    if t_release is not None and x >= t_release and behavior != "no_recovery":
                        rs = v
        if behavior == "chatter" and t_release is not None and t_release + 0.5e-3 <= x < t_release + 1.0e-3:
            rs = 0.0
        if behavior == "control_assert" and 25e-3 <= x < 26e-3:
            rs = 0.0
        pr = v if (x >= t_raw0) else 0.0
        if t_assert is not None and behavior not in ("missed",) and st["vlow"] < vf and x >= t_assert:
            pr = 0.0 if (t_raw_up is None or x < t_raw_up) else v
        cols["time"].append(x)
        cols["v(vdd)"].append(v)
        cols["v(resetn)"].append(rs)
        cols["v(xdut.por_raw)"].append(pr)
        cols["v(xdut.ibias)"].append(0.85 if rs > 0 else 0.4)
        cols["i(bvdd)"].append(-2.3e-5)
        i_nom = 5e-6
        if behavior == "bias_lost" and t_up is not None and x > t_up + 5e-3:
            i_nom = 1e-6
        if t_assert is not None and t_assert <= x <= (t_up or x) and v < 1.0:
            i_nom = 0.2e-6
        cols[I_DELIVERED].append(i_nom)
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


def selftest_cases():
    base = dict(REF_ST)
    shallow = dict(REF_ST, vlow=2.4, sf=1e4, sr=1e4)
    control = dict(REF_ST, vlow=99.0)
    short = dict(REF_ST, th=10e-6)
    return {
        "recovery_ok": (lambda: synth(st=base), "PASS", []),
        "missed_assertion": (lambda: synth(st=base, behavior="missed"), "FAIL", ["missed_assertion"]),
        "premature_release": (lambda: synth(st=base, behavior="premature"), "FAIL", ["premature_release"]),
        "reassert_chatter": (lambda: synth(st=base, behavior="chatter"), "FAIL", ["reassert_chatter", "reassert_after_recovery"]),
        "no_recovery": (lambda: synth(st=base, behavior="no_recovery"), "FAIL", ["no_recovery"]),
        "bias_not_recovered": (lambda: synth(st=base, behavior="bias_lost"), "FAIL", ["bias_not_recovered"]),
        "truncated_observation": (lambda: synth(st=base, tstop=base["t0"] + 1e-3), "UNRESOLVED", []),
        "truncated_no_release": (lambda: synth(st=base, behavior="no_recovery", tstop=timeline(3.3, base)["t_rec_end"] + 1e-3), "UNRESOLVED", []),
        "sparse_samples": (lambda: synth(st=base, coarse=100e-6), "UNRESOLVED", []),
        "nonphysical_node": (lambda: synth(st=base, bad_node=("v(xdut.xtemp.nb)", -50.0)), "NONPHYSICAL", []),
        "missing_current_channel": (lambda: synth(st=base, drop_channel=I_DELIVERED), "ERROR", []),
        "unready_baseline": (lambda: synth(st=base, behavior="no_baseline"), "UNRESOLVED", []),
        "nodip_control_ok": (lambda: synth(st=control), "PASS", []),
        "nodip_control_spurious_assertion": (lambda: synth(st=control, behavior="control_assert"), "FAIL", ["spurious_assertion_control"]),
        "shallow_dip_not_required": (lambda: synth(st=shallow), "PASS", []),
        "short_hold_ok": (lambda: synth(st=short), "PASS", []),
    }


def run_selftest(fixture_dir: Path | None = None) -> list[dict]:
    out = []
    for name, (build, want, want_codes) in selftest_cases().items():
        wave, st = build()
        res = analyze(wave, 3.3, st, T_OBS_REF)
        got = res["verdict"]
        codes = res.get("fail_codes", [])
        ok = got == want and all(c in codes for c in want_codes)
        out.append({"case": name, "expected_verdict": want, "expected_codes_subset": want_codes, "verdict": got, "fail_codes": codes,
                    "unresolved_reasons": res.get("unresolved_reasons", []), "ok": ok})
        if fixture_dir is not None and name in ("recovery_ok", "missed_assertion"):
            fixture_dir.mkdir(parents=True, exist_ok=True)
            names = [c for c in wave if c in CORE]
            doc = {"plotname": "Synthetic (controlled) -- sim/brownout-top/brownout_checker.py", "stimulus": st,
                   "variables": [{"index": i, "name": c} for i, c in enumerate(names)],
                   "points": [[wave[c][k] for c in names] for k in range(len(wave["time"]))]}
            with gzip.open(fixture_dir / f"{name}.wave.json.gz", "wt", compresslevel=9) as fh:
                json.dump(doc, fh, separators=(",", ":"))
    return out


if __name__ == "__main__":
    res = run_selftest()
    for r in res:
        print(f"{r['case']:<34} expected {r['expected_verdict']:<12} got {r['verdict']:<12} codes={r['fail_codes']} {'OK' if r['ok'] else 'MISMATCH'}")
    sys.exit(0 if all(r["ok"] for r in res) else 1)
