#!/usr/bin/env python3
"""Transition checker for the assembled temp_por_top supply-ramp campaign (issue #98).

Pure standard library.  Consumes the waveform JSON that ``klt sim`` writes for
each corner (``{"variables": [{"name": ...}], "points": [[...], ...]}``) and
grades one supply-ramp point from the *full-resolution* trace -- never from
end-point measurements alone.

Every definition below is exploratory: it grades the shape of the behaviour
(``RESETn`` low from 0 V, released once and only once, no glitch, no double
pulse -- spec/porting-plan.md Sec3.3) against thresholds expressed as
fractions of the swept final supply.  None of the fractions or tolerances is a
ratified specification bound (DR-003 Sec8: no numeric ramp envelope exists).

Definitions (``vf`` = final supply of the point, ``rate`` = constant dVDD/dt)
-----------------------------------------------------------------------------
* Levels: ``V_IL = 0.2 vf``, ``V_IH = 0.8 vf``, ``V_RUNT = 0.1 vf``,
  ``V_MID = 0.5 vf``.
* Release / re-assert: a two-threshold (Schmitt) state machine on ``RESETn``,
  starting LOW.  A *release* is a rising crossing of ``V_IH``; a *re-assert* is
  a falling crossing of ``V_IL`` while HIGH.  ``n_release`` and ``n_reassert``
  count them.
* Runt: an episode where ``RESETn`` exceeds ``V_RUNT``, then returns to or
  below ``V_RUNT`` without ever reaching ``V_IH``.  Runts are counted
  separately so a partial excursion cannot hide below the Schmitt band.
* Mid crossings: independent count of rising/falling ``V_MID`` crossings of
  ``RESETn`` (a second, state-free transition counter).
* no release: ``n_release == 0`` over the whole observation window (the window
  length is part of the record; "no release within window" is the claim).
* premature release: the first release happens before ``POR_RAW`` first
  rises through ``V_MID`` (the release has no comparator authority behind it),
  or ``POR_RAW`` never rises at all.
* repeated release: ``n_release > 1``.
* Resolution: the grading is only trusted when the largest sample gap is
  ``<= MAX_DT`` (the minimum detectable glitch width) and the sampled supply
  follows ``min(vf, rate*t)`` to within ``RAMP_TOL``.  Otherwise a point that
  shows no detected failure is ``UNRESOLVED`` rather than ``PASS``.  A failure
  that *was* detected stays ``FAIL``.
* Physicality: every saved node must stay within ``[-0.3, vf + 0.5]`` V for
  ``t > 0`` and the settled supply current ``-i(BVDD)`` must be positive and
  finite.  The ``t = 0`` sample (a degenerate all-zero-supply solve) is
  reported separately and does not enter the verdict.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from sim_common import load_wave  # noqa: E402,F401  (shared hardened loader)

# --- exploratory grading constants (NOT ratified bounds) -------------------
FRAC_IL = 0.2
FRAC_IH = 0.8
FRAC_RUNT = 0.1
FRAC_MID = 0.5
MAX_DT = 20e-6  # s: largest tolerated sample gap (= min detectable glitch width)
RAMP_TOL = 0.02  # V: allowed |VDD - min(vf, rate*t)|
MIN_RAMP_SAMPLES = 20  # samples on the ramp needed to quote a VDD-at-crossing
PHYS_LO = -0.3  # V
PHYS_HI_MARGIN = 0.5  # V above vf
IB_SWING = 5e-3  # V: IBIAS reversal amplitude counted as chatter
SETTLE_WINDOW = 1e-3  # s: trailing window used for "end" values

CORE = ("time", "v(vdd)", "v(resetn)", "v(xdut.por_raw)", "v(xdut.ibias)", "i(bvdd)")
PHYS_NODES = (
    "v(resetn)",
    "v(xdut.por_raw)",
    "v(xdut.ibias)",
    "v(xdut.vref)",
    "v(xdut.bias_ok)",
    "v(ptat)",
    "v(ctat)",
    "v(xdut.xbias.na)",
    "v(xdut.xbias.nb)",
    "v(xdut.xbias.nbg)",
    "v(xdut.xbias.pb)",
    "v(xdut.xbias.pg)",
    "v(xdut.xtemp.na)",
    "v(xdut.xtemp.nb)",
)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def _interp_cross(t0, y0, t1, y1, level):
    if y1 == y0:
        return t1
    return t0 + (level - y0) * (t1 - t0) / (y1 - y0)


def crossings(t, y, level, direction):
    """Interpolated crossing times of ``level`` ('rise' or 'fall'), t > 0."""
    out = []
    for i in range(1, len(t)):
        if t[i] <= 0:
            continue
        a, b = y[i - 1], y[i]
        if direction == "rise" and a < level <= b:
            out.append(_interp_cross(t[i - 1], a, t[i], b, level))
        elif direction == "fall" and a > level >= b:
            out.append(_interp_cross(t[i - 1], a, t[i], b, level))
    return out


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


def schmitt(t, y, lo, hi):
    """Return (rise_times, fall_times) of a LOW-initial two-threshold detector."""
    state = False
    rises, falls = [], []
    for i in range(1, len(t)):
        if t[i] <= 0:
            continue
        a, b = y[i - 1], y[i]
        if not state and b >= hi:
            rises.append(_interp_cross(t[i - 1], a, t[i], b, hi) if a < hi else t[i])
            state = True
        elif state and b <= lo:
            falls.append(_interp_cross(t[i - 1], a, t[i], b, lo) if a > lo else t[i])
            state = False
    return rises, falls


def runt_episodes(t, y, v_runt, v_ih):
    """Episodes above v_runt that return <= v_runt. Returns (n_returned, n_runts)."""
    n_ret = n_runt = 0
    inside = False
    peak = 0.0
    for i in range(1, len(t)):
        if t[i] <= 0:
            continue
        if not inside and y[i] > v_runt:
            inside, peak = True, y[i]
        elif inside:
            peak = max(peak, y[i])
            if y[i] <= v_runt:
                n_ret += 1
                if peak < v_ih:
                    n_runt += 1
                inside = False
    return n_ret, n_runt


def reversals(y, swing):
    """Count direction reversals larger than ``swing`` (hysteretic turning points)."""
    if not y:
        return 0
    n = 0
    ext = y[0]
    direction = 0  # +1 rising, -1 falling
    for v in y[1:]:
        if direction >= 0 and v > ext:
            ext = v
            if direction == 0 and v - y[0] > swing:
                direction = 1
        elif direction >= 0 and ext - v > swing:
            if direction == 1:
                n += 1
            direction = -1
            ext = v
        elif direction <= 0 and v < ext:
            ext = v
            if direction == 0 and y[0] - v > swing:
                direction = -1
        elif direction <= 0 and v - ext > swing:
            if direction == -1:
                n += 1
            direction = 1
            ext = v
    return n


# --------------------------------------------------------------------------
# point analysis
# --------------------------------------------------------------------------


def analyze(w: dict[str, list[float]], vf: float, rate: float) -> dict:
    """Grade one ramp point from its full-resolution waveform."""
    missing = [n for n in CORE if n not in w]
    if missing:
        return {"verdict": "ERROR", "fail_codes": [], "detail": f"waveform lacks {missing}"}
    t = w["time"]
    vdd = w["v(vdd)"]
    rst = w["v(resetn)"]
    raw = w["v(xdut.por_raw)"]
    ib = w["v(xdut.ibias)"]
    isup_s = [-x for x in w["i(bvdd)"]]
    n = len(t)
    if n < 3 or any(not math.isfinite(x) for name in CORE for x in w[name]):
        return {"verdict": "ERROR", "fail_codes": [], "detail": "too few or non-finite samples"}
    if any(t[i + 1] <= t[i] for i in range(n - 1)):
        return {"verdict": "ERROR", "fail_codes": [], "detail": "time axis not strictly increasing"}

    tramp = vf / rate
    v_il, v_ih = FRAC_IL * vf, FRAC_IH * vf
    v_runt, v_mid = FRAC_RUNT * vf, FRAC_MID * vf

    # --- resolution / construction checks ---
    max_dt = max(t[i + 1] - t[i] for i in range(n - 1))
    ramp_err = max(abs(vdd[i] - min(vf, rate * t[i])) for i in range(n))
    n_ramp = sum(1 for x in t if 0 < x <= tramp)
    resolution_ok = max_dt <= MAX_DT
    ramp_ok = ramp_err <= RAMP_TOL

    # --- RESETn transition accounting ---
    rel, fall = schmitt(t, rst, v_il, v_ih)
    n_ret, n_runt = runt_episodes(t, rst, v_runt, v_ih)
    up50 = crossings(t, rst, v_mid, "rise")
    dn50 = crossings(t, rst, v_mid, "fall")
    raw_up50 = crossings(t, raw, v_mid, "rise")
    raw_rel, raw_fall = schmitt(t, raw, v_il, v_ih)
    t_raw = raw_up50[0] if raw_up50 else None
    t_rel50 = up50[0] if up50 else None
    t_rel = rel[0] if rel else None
    premature = bool(rel) and (t_raw is None or rel[0] < t_raw)

    # --- physicality ---
    hi = vf + PHYS_HI_MARGIN
    viol, t0_viol = {}, {}
    for name in PHYS_NODES:
        col = w.get(name)
        if col is None:
            continue
        bad = [x for tt, x in zip(t, col) if tt > 0 and not (PHYS_LO <= x <= hi)]
        if bad:
            viol[name] = {"count": len(bad), "min": min(bad), "max": max(bad)}
        if not (PHYS_LO <= col[0] <= hi):
            t0_viol[name] = col[0]
    last = [i for i in range(n) if t[i] >= t[-1] - SETTLE_WINDOW]
    isup_end = sum(isup_s[i] for i in last) / len(last)
    isup_ok = math.isfinite(isup_end) and isup_end > 0.0
    physical = not viol and isup_ok

    # --- IBIAS (shared node) ---
    pos = [i for i in range(n) if t[i] > 0]
    ib_pos = [ib[i] for i in pos]
    t_pos = [t[i] for i in pos]
    ib_end = sum(ib[i] for i in last) / len(last)
    ib_step = None
    ib_p2p_post = None
    if t_rel50 is not None:
        ib_step = interp_at(t, ib, t_rel50 + 200e-6) - interp_at(t, ib, t_rel50 - 20e-6)
        post = [ib[i] for i in range(n) if t[i] >= t_rel50 + 500e-6]
        ib_p2p_post = (max(post) - min(post)) if post else None
    start_sw = t_raw if t_raw is not None else 0.0
    ib_swings = reversals([ib[i] for i in range(n) if t[i] >= start_sw], IB_SWING)

    # --- verdict ---
    fails = []
    if len(rel) == 0:
        fails.append("no_release")
    if len(rel) > 1:
        fails.append("repeated_release")
    if len(fall) > 0:
        fails.append("reassert_after_release")
    if n_runt > 0:
        fails.append("runt_glitch")
    if premature:
        fails.append("premature_release")
    if len(rel) == 1 and (len(up50) != 1 or len(dn50) != 0) and "runt_glitch" not in fails:
        fails.append("extra_mid_crossings")
    transition_fails = list(fails)
    if not physical:
        fails.append("nonphysical")
    issues = []
    if not resolution_ok:
        issues.append(f"max sample gap {max_dt:.3g} s > {MAX_DT:.3g} s")
    if not ramp_ok:
        issues.append(f"supply deviates from min(vf,rate*t) by {ramp_err:.3g} V")
    verdict = "FAIL" if fails else ("UNRESOLVED" if issues else "PASS")
    transition_verdict = "FAIL" if transition_fails else ("UNRESOLVED" if issues else "PASS")

    # --- threshold-style measurements ---
    vdd_raw = interp_at(t, vdd, t_raw) if t_raw is not None else None
    raw_censored = t_raw is not None and t_raw > tramp
    return {
        "verdict": verdict,
        "transition_verdict": transition_verdict,
        "fail_codes": fails,
        "transition_fail_codes": transition_fails,
        "unresolved_reasons": issues,
        "n_samples": n,
        "max_dt_s": max_dt,
        "ramp_samples": n_ramp,
        "ramp_error_v": ramp_err,
        "resolution_ok": resolution_ok,
        "ramp_ok": ramp_ok,
        "tramp_s": tramp,
        "t_end_s": t[-1],
        "levels_v": {"V_IL": v_il, "V_IH": v_ih, "V_RUNT": v_runt, "V_MID": v_mid},
        "resetn": {
            "n_release": len(rel),
            "n_reassert": len(fall),
            "n_mid_up": len(up50),
            "n_mid_down": len(dn50),
            "n_episodes_returned": n_ret,
            "n_runt": n_runt,
            "t_release_s": t_rel,
            "t_release_mid_s": t_rel50,
            "vdd_at_release_v": interp_at(t, vdd, t_rel) if t_rel is not None else None,
            "released_during_ramp": (t_rel is not None and t_rel <= tramp),
            "max_during_ramp_v": max((rst[i] for i in range(n) if 0 < t[i] <= tramp), default=None),
            "max_v": max(rst),
            "end_v": rst[-1],
            "premature": premature,
        },
        "por_raw": {
            "n_rise": len(raw_rel),
            "n_fall": len(raw_fall),
            "t_rise_mid_s": t_raw,
            "vdd_at_rise_v": vdd_raw,
            "rise_after_ramp_end_censored": raw_censored,
            "vdd_at_rise_resolved": (n_ramp >= MIN_RAMP_SAMPLES and not raw_censored),
        },
        "release_delay_s": (t_rel50 - t_raw) if (t_rel50 is not None and t_raw is not None) else None,
        "ibias": {
            "min_v": min(ib_pos),
            "max_v": max(ib_pos),
            "end_v": ib_end,
            "release_step_v": ib_step,
            "post_release_p2p_v": ib_p2p_post,
            "swings_gt_5mV": ib_swings,
        },
        "physical": {
            "ok": physical,
            "isup_end_a": isup_end,
            "isup_positive": isup_ok,
            "violations_after_t0": viol,
            "violations_at_t0": t0_viol,
        },
        "end": {
            "vdd_v": vdd[-1],
            "ptat_v": w.get("v(ptat)", [None])[-1],
            "ctat_v": w.get("v(ctat)", [None])[-1],
            "vref_v": w.get("v(xdut.vref)", [None])[-1],
            "bias_ok_v": w.get("v(xdut.bias_ok)", [None])[-1],
        },
    }


# --------------------------------------------------------------------------
# event-preserving trace compression (what gets committed)
# --------------------------------------------------------------------------

STORE_COLS = ("time", "v(vdd)", "v(resetn)", "v(xdut.por_raw)", "v(xdut.ibias)")
KEEP_DV = 2e-3  # V: keep a sample when any stored channel moved this much
KEEP_DT = 1e-3  # s: and at least one anchor per this interval


def compress(w: dict[str, list[float]]) -> list[list[float]]:
    """Change-triggered decimation: every excursion >= KEEP_DV is retained."""
    cols = [w[c] for c in STORE_COLS]
    n = len(cols[0])
    rows = [[c[0] for c in cols]]
    last = rows[0]
    for i in range(1, n - 1):
        cur = [c[i] for c in cols]
        if cur[0] - last[0] >= KEEP_DT or any(abs(cur[k] - last[k]) >= KEEP_DV for k in range(1, len(cols))):
            rows.append(cur)
            last = cur
    rows.append([c[n - 1] for c in cols])
    return rows


def transitions_from_stored(rows: list[list[float]], vf: float) -> dict:
    """Re-derive the transition counts from the stored (compressed) trace only."""
    t = [r[0] for r in rows]
    rst = [r[2] for r in rows]
    raw = [r[3] for r in rows]
    rel, fall = schmitt(t, rst, FRAC_IL * vf, FRAC_IH * vf)
    _, n_runt = runt_episodes(t, rst, FRAC_RUNT * vf, FRAC_IH * vf)
    raw_up = crossings(t, raw, FRAC_MID * vf, "rise")
    premature = bool(rel) and (not raw_up or rel[0] < raw_up[0])
    return {
        "n_release": len(rel),
        "n_reassert": len(fall),
        "n_runt": n_runt,
        "premature": premature,
    }


def write_trace(path: Path, rows: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# t_s,vdd_v,resetn_v,por_raw_v,ibias_v  (change-triggered, dV>=2mV or dt>=1ms)"]
    lines += [",".join(f"{x:.6g}" for x in r) for r in rows]
    with gzip.open(path, "wt", compresslevel=9) as fh:
        fh.write("\n".join(lines) + "\n")


def read_trace(path: Path) -> list[list[float]]:
    with gzip.open(path, "rt") as fh:
        return [[float(x) for x in ln.split(",")] for ln in fh if ln.strip() and not ln.startswith("#")]


# --------------------------------------------------------------------------
# self-test fixtures: controlled waveforms with known answers
# --------------------------------------------------------------------------


def _synth(vf, rate, events, hold=15e-3, dt=5e-6, raw_t=None, coarse=None, bad_node=None):
    """Build a klt-format waveform dict. ``events``: [(t_up, t_down_or_None)] RESETn pulses."""
    tramp = vf / rate
    tend = tramp + hold
    step = coarse or dt
    ts = [0.0]
    while ts[-1] < tend:
        ts.append(min(tend, ts[-1] + step))
    raw_t = tramp * 0.9 if raw_t is None else raw_t

    def rst_at(x):
        v = 0.0
        for ev in events:
            up, down = ev[0], ev[1]
            amp = ev[2] if len(ev) > 2 else 1.0
            if x >= up and (down is None or x < down):
                v = amp * (min(vf, rate * x) if x < tramp else vf)
        return v

    cols = {c: [] for c in CORE}
    for x in ts:
        vdd = min(vf, rate * x)
        cols["time"].append(x)
        cols["v(vdd)"].append(vdd)
        cols["v(resetn)"].append(rst_at(x))
        cols["v(xdut.por_raw)"].append(vdd if x >= raw_t else 0.0)
        cols["v(xdut.ibias)"].append(0.85 if x < events[0][0] else 0.81) if events else cols["v(xdut.ibias)"].append(0.85)
        cols["i(bvdd)"].append(-2.3e-5)
    for name in PHYS_NODES:
        cols.setdefault(name, [0.5] * len(ts))
    if bad_node:
        name, val = bad_node
        cols[name] = [0.5] + [val] * 50 + [0.5] * (len(ts) - 51)
    return cols


def selftest_cases(vf=3.3, rate=1e4):
    tramp = vf / rate
    rel = tramp + 2.1e-3
    return {
        "single_release": (_synth(vf, rate, [(rel, None)]), "PASS", []),
        "double_release": (
            _synth(vf, rate, [(rel, rel + 3e-3), (rel + 6e-3, None)]),
            "FAIL",
            ["repeated_release", "reassert_after_release"],
        ),
        "reassert_only": (_synth(vf, rate, [(rel, rel + 3e-3)]), "FAIL", ["no_release_or_reassert"]),
        "no_release": (_synth(vf, rate, []), "FAIL", ["no_release"]),
        "premature_release": (
            _synth(vf, rate, [(tramp * 0.95, None)], raw_t=tramp + 1e-3),
            "FAIL",
            ["premature_release"],
        ),
        "runt_glitch": (
            _synth(vf, rate, [(rel - 1e-3, rel - 0.9e-3, 0.4), (rel, None)]),
            "FAIL",
            ["runt_glitch"],
        ),
        "nonphysical_node": (_synth(vf, rate, [(rel, None)], bad_node=("v(xdut.xtemp.nb)", -50.0)), "FAIL", ["nonphysical"]),
        "coarse_sampling": (_synth(vf, rate, [(rel, None)], coarse=100e-6), "UNRESOLVED", []),
    }


def run_selftest(fixture_dir: Path | None = None) -> list[dict]:
    """Run every controlled case; return one result dict per case."""
    out = []
    for name, (wave, want, want_codes) in selftest_cases().items():
        res = analyze(wave, 3.3, 1e4)
        got = res["verdict"]
        codes = res.get("fail_codes", [])
        if name == "reassert_only":  # released then re-asserted: n_release==1, n_reassert==1
            ok_codes = "reassert_after_release" in codes
        else:
            ok_codes = all(c in codes for c in want_codes)
        out.append(
            {
                "case": name,
                "expected_verdict": want,
                "expected_codes_subset": want_codes if name != "reassert_only" else ["reassert_after_release"],
                "verdict": got,
                "fail_codes": codes,
                "n_release": res["resetn"]["n_release"] if "resetn" in res else None,
                "n_reassert": res["resetn"]["n_reassert"] if "resetn" in res else None,
                "max_dt_s": res.get("max_dt_s"),
                "ok": got == want and ok_codes,
            }
        )
        if fixture_dir is not None:
            fixture_dir.mkdir(parents=True, exist_ok=True)
            names = [c for c in wave if c in CORE]
            doc = {
                "plotname": "Synthetic (controlled) -- sim/supply-ramp-top/ramp_checker.py",
                "variables": [{"index": i, "name": c} for i, c in enumerate(names)],
                "points": [[wave[c][k] for c in names] for k in range(len(wave["time"]))],
            }
            if name in ("double_release", "single_release"):
                with open(fixture_dir / f"{name}.wave.json", "w") as fh:
                    json.dump(doc, fh, separators=(",", ":"))
    return out


if __name__ == "__main__":
    res = run_selftest()
    for r in res:
        print(f"{r['case']:<18} expected {r['expected_verdict']:<10} got {r['verdict']:<10} "
              f"codes={r['fail_codes']} {'OK' if r['ok'] else 'MISMATCH'}")
    sys.exit(0 if all(r["ok"] for r in res) else 1)
